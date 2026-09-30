"""What a diamond import would do, then doing it.

The register is re-exported and re-imported periodically, and diamond lines
have no clean key (many have no batch number). A row matches an existing line
by batch + item code + size; when that is not unique it falls back to the sheet
row, and when that is still ambiguous a human decides. Nothing is written until
``commit``, which refuses while anything is undecided. Once a line is open,
Settings owns its category, band and shape: a re-import updates only what the
file alone knows.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from accounts.capabilities import INV_MASTERS, VIEW_COST
from stock.services import ServiceError, log, require

from .. import dia_rules, dia_services
from ..models import DiamondCode, DiamondLine, DiamondRate, DiamondTerm


@dataclass
class NewCode:
    item_code: str
    shape: str = ""
    colour: str = ""
    clarity: str = ""
    note: str = ""
    confirmed: bool = False


@dataclass
class Item:
    row: object
    action: str = "new"
    existing: object = None
    problem: str = None
    candidates: list = field(default_factory=list)
    held_ct: object = None
    recount: bool = False
    empty: bool = False


@dataclass
class Plan:
    items: list
    codes: list
    missing: list

    def counts(self):
        live = [i for i in self.items if i.action != "skip"]
        return {
            "rows": len(self.items), "skip": len(self.items) - len(live),
            "new": sum(1 for i in live if i.action == "new" and not i.problem),
            "update": sum(1 for i in live if i.action == "update"),
            "blocked": sum(1 for i in live if i.problem),
            "recount": sum(1 for i in live if i.recount),
            "codes": len(self.codes), "missing": len(self.missing),
            "zero": sum(1 for _, action in self.missing if action == "zero"),
            "empty": sum(1 for i in self.items if i.empty),
        }


def _key(batch_no, item_code, size_text):
    return (batch_no, item_code, size_text)


def _codes(rows, decisions):
    known = set(DiamondCode.objects.values_list("item_code", flat=True))
    groups = {}
    for row in rows:
        if row.item_code not in known:
            groups.setdefault(row.item_code, []).append(row)

    proposals = {}
    for item_code, code_rows in groups.items():
        decoded = dia_rules.decode(item_code)
        choice = decisions.get(f"code:{item_code}") or {}
        notes, values, blank_field = [], {}, False
        for attr in ("shape", "colour", "clarity"):
            file_values = [getattr(r, attr) for r in code_rows]
            first_value, decoded_value = file_values[0], getattr(decoded, attr)
            chosen = first_value or decoded_value
            values[attr] = chosen
            others = [v for v in file_values if v and v != chosen]
            if others:
                notes.append(f"rows disagree on {attr}: {chosen} / {others[0]}")
            if not first_value:
                blank_field = True
            elif (decoded_value and not decoded_value.startswith("?") and decoded.shape != "Fancy Colour"
                  and not decoded.note and first_value != decoded_value):
                notes.append(f"{attr}: file says {first_value}, code reads {decoded_value}")
        if blank_field and decoded.note:
            notes.append(decoded.note)
        note = "; ".join(notes)
        confirmed = (not note and bool(values["shape"]) and bool(values["colour"])
                     and (bool(values["clarity"]) or values["colour"].startswith("Fancy")))
        proposals[item_code] = NewCode(
            item_code=item_code, note=note,
            shape=choice.get("shape", values["shape"]), colour=choice.get("colour", values["colour"]),
            clarity=choice.get("clarity", values["clarity"]),
            confirmed=choice["confirmed"] if "confirmed" in choice else confirmed,
        )
    return list(proposals.values())


def analyse(rows, decisions=None):
    decisions = decisions or {}
    existing = list(DiamondLine.objects.select_related("code"))
    by_key, by_src, by_ref = defaultdict(list), {}, {}
    for line in existing:
        by_key[_key(line.batch_no, line.code_id, line.size_text)].append(line)
        by_ref[line.ref] = line
        if line.src:
            by_src[line.src] = line
    in_sheet = Counter(_key(r.batch_no, r.item_code, r.size_text) for r in rows)

    items, taken = [], {}
    for row in rows:
        item = Item(row=row)
        if not row.item_code:
            item.problem = "No item code"
        choice = decisions.get(f"row:{row.src}") or {}
        candidates = by_key.get(_key(row.batch_no, row.item_code, row.size_text), [])
        if choice.get("action") == "skip":
            item.action = "skip"
        elif choice.get("action") == "new":
            item.action = "new"
        elif choice.get("action") == "map" and choice.get("line") in by_ref:
            item.action, item.existing = "update", by_ref[choice["line"]]
        elif len(candidates) == 1 and in_sheet[_key(row.batch_no, row.item_code, row.size_text)] == 1:
            item.action, item.existing = "update", candidates[0]
        elif candidates and by_src.get(row.src) in candidates:
            item.action, item.existing = "update", by_src[row.src]
        elif candidates:
            item.problem = f"{len(candidates)} lines share this batch, code and size"
            item.candidates = candidates
        if item.existing is not None:
            if item.existing.pk in taken:
                item.problem = f"{item.existing.ref} is already matched to {taken[item.existing.pk]}"
                item.candidates = candidates or [item.existing]
                item.existing, item.action = None, "new"
            else:
                taken[item.existing.pk] = row.src
        if row.ct == 0 and item.existing is None and item.problem is None and item.action != "skip":
            item.action, item.empty = "skip", True
        items.append(item)

    held = {line.pk: line.on_ct for line in dia_services.stocked_lines(
        DiamondLine.objects.filter(pk__in=[i.existing.pk for i in items if i.existing]))}
    for item in items:
        if item.existing is not None:
            item.held_ct = held.get(item.existing.pk)
            item.recount = item.row.ct != (item.held_ct or 0)

    missing = [(line, decisions.get(f"missing:{line.ref}", "keep"))
               for line in existing if line.pk not in taken]
    return Plan(items=items, codes=_codes(rows, decisions), missing=missing)


def read_decisions(post, plan, decisions):
    """The review form's answers, merged into what was already decided."""
    decisions = dict(decisions or {})
    for item in plan.items:
        name = f"row:{item.row.src}"
        if name in post:
            decisions[name] = {"action": post.get(name), "line": post.get(f"{name}:line", "")}
    for code in plan.codes:
        name = f"code:{code.item_code}"
        if f"{name}:shape" in post:
            decisions[name] = {"shape": post.get(f"{name}:shape", "").strip(),
                               "colour": post.get(f"{name}:colour", "").strip(),
                               "clarity": post.get(f"{name}:clarity", "").strip(),
                               "confirmed": bool(post.get(f"{name}:confirmed"))}
    for line, _ in plan.missing:
        name = f"missing:{line.ref}"
        if name in post:
            decisions[name] = "zero" if post.get(name) == "zero" else "keep"
    return decisions


def _term(kind, value):
    return dia_services.term(kind, value) if value else None


def _sized(row):
    """A size that fits no band is banded by the weight per stone, when the file gives pieces (the owner, 2026-09-30)."""
    sized = dia_rules.size_band(row.band_text or row.size_text)
    if sized.band == "?" and (row.pcs or 0) > 0 and (row.ct or 0) > 0:
        per_stone = (row.ct / row.pcs).quantize(Decimal("0.001"))
        return dia_rules.Sized("carat band", per_stone, per_stone)
    return sized


@transaction.atomic
def commit(plan, user, import_batch=None):
    require(user, INV_MASTERS, "Only a role that edits inventory records can import stock.")
    blocked = [i for i in plan.items if i.problem and i.action != "skip"]
    if blocked:
        raise ServiceError(f"{len(blocked)} rows still need a decision.")
    for code in plan.codes:
        DiamondCode.objects.create(
            item_code=code.item_code, shape=_term(DiamondTerm.SHAPE, code.shape),
            colour=_term(DiamondTerm.COLOUR, code.colour), clarity=_term(DiamondTerm.CLARITY, code.clarity),
            confirmed=code.confirmed, note=code.note,
        )
    result = {"created": 0, "updated": 0, "recounted": 0, "zeroed": 0, "skipped": 0, "empty": 0, "codes": len(plan.codes)}
    fresh = []
    for item in plan.items:
        row = item.row
        if item.action == "skip":
            result["empty" if item.empty else "skipped"] += 1
            continue
        sized = _sized(row)
        code = DiamondCode.objects.get(pk=row.item_code)
        fields = {"batch_no": row.batch_no, "size_text": row.size_text, "ct_lo": sized.ct_lo, "ct_hi": sized.ct_hi,
                  "src": row.src}
        if item.existing is None:
            fresh.append({
                "code": code, "ct": row.ct, "pcs": row.pcs, **fields,
                "category": dia_services.term(DiamondTerm.CATEGORY, row.category),
                "band": dia_services.term(DiamondTerm.BAND, sized.band),
                "shape_override": _term(DiamondTerm.SHAPE, sized.shape) if sized.shape and code.shape_id is None else None,
            })
            continue
        line = item.existing
        changed = [name for name, value in fields.items() if getattr(line, name) != value]
        for name in changed:
            setattr(line, name, fields[name])
        if changed:
            line.save(update_fields=changed)
        result["updated"] += 1
        if item.recount:
            dia_services.recount_line(user, line, row.ct, note=f"re-imported from {row.src}")
            result["recounted"] += 1
    result["created"] = len(dia_services.open_lines(user, fresh, import_batch=import_batch))
    for line, action in plan.missing:
        if action == "zero" and dia_services.recount_line(user, line, 0, note="not in the re-imported register"):
            result["zeroed"] += 1

    live = [i for i in plan.items if i.action != "skip"]
    can_cost = user.has_perm(VIEW_COST)
    result["prices_skipped"] = not can_cost and any(i.row.rate is not None for i in live)
    result["rates"] = 0
    if can_cost:
        rates = dia_services.rate_table()
        priced = {}
        for item in live:
            if item.row.rate is not None:
                priced[(item.row.item_code, item.row.size_text)] = item.row.rate     # last row of a key wins
        for (item_code, size_text), rate in priced.items():
            if rates.get((item_code, size_text), {}).get("cost") != rate:
                DiamondRate.objects.create(code_id=item_code, size_text=size_text, cost_rate=rate, set_by=user)
                result["rates"] += 1

    log(user, "IMPORT", "inv_dia_line", import_batch.pk if import_batch else "-", f"diamond import {result}")
    return result
