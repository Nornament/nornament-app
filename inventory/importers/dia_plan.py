"""What a diamond import would do, then doing it.

The register is re-exported and re-imported periodically, and diamond lines
have no clean key (many have no batch number). A row matches an existing line
by batch + item code + size; when that is not unique it falls back to the sheet
row, and when that is still ambiguous a human decides. Nothing is written until
``commit``, which refuses while anything is undecided.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.db import transaction

from accounts.capabilities import INV_MASTERS
from stock.services import ServiceError, log, require

from .. import dia_rules, dia_services
from ..models import DiamondCode, DiamondLine, DiamondTerm


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
        }


def _key(batch_no, item_code, size_text):
    return (batch_no, item_code, size_text)


def _codes(rows, decisions):
    known = set(DiamondCode.objects.values_list("item_code", flat=True))
    proposals = {}
    for row in rows:
        if row.item_code in known or row.item_code in proposals:
            continue
        decoded = dia_rules.decode(row.item_code)
        choice = decisions.get(f"code:{row.item_code}") or {}
        proposals[row.item_code] = NewCode(
            item_code=row.item_code, note=decoded.note,
            shape=choice.get("shape", decoded.shape), colour=choice.get("colour", decoded.colour),
            clarity=choice.get("clarity", decoded.clarity),
            confirmed=choice["confirmed"] if "confirmed" in choice else decoded.confirmed,
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
    result = {"created": 0, "updated": 0, "recounted": 0, "zeroed": 0, "skipped": 0, "codes": len(plan.codes)}
    fresh = []
    for item in plan.items:
        row = item.row
        if item.action == "skip":
            result["skipped"] += 1
            continue
        sized = dia_rules.size_band(row.size_text)
        code = DiamondCode.objects.get(pk=row.item_code)
        fields = {
            "category": dia_services.term(DiamondTerm.CATEGORY, row.category),
            "batch_no": row.batch_no, "size_text": row.size_text,
            "band": dia_services.term(DiamondTerm.BAND, sized.band),
            "ct_lo": sized.ct_lo, "ct_hi": sized.ct_hi, "src": row.src,
            "shape_override": _term(DiamondTerm.SHAPE, sized.shape) if sized.shape and code.shape_id is None else None,
        }
        if item.existing is None:
            fresh.append({"code": code, "ct": row.ct, **fields})
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
    log(user, "IMPORT", "inv_dia_line", import_batch.pk if import_batch else "-", f"diamond import {result}")
    return result
