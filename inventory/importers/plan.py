"""What an import would do, then doing it.

``analyse`` writes nothing: it turns rows and the reviewer's decisions into
items, each either fine, blocked (``problem``), or an update to a pouch already
here. The review screen renders them; ``commit`` refuses while anything is
blocked and then writes everything in one transaction.

Decisions are keyed by source row (``SL!104``) because that is the one thing
about a row that the reviewer's edits cannot change.
"""
from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from accounts.capabilities import INV_MASTERS
from stock.services import ServiceError, log, require

from .. import rules, services
from ..models import UNRESOLVED_SWATCH, Batch, BoxColour, CodePart, Pouch, PriceEntry


@dataclass
class Item:
    row: object
    batch: str
    pouch_no: str
    skip: bool = False
    problem: str = None
    suggestion: str = ""
    existing: object = None
    held_pcs: int = None
    held_ct: object = None
    held_rate: object = None
    recount: bool = False


def _item(row, choice):
    batch = (choice.get("batch") or row.batch).strip().upper()
    pouch_no = choice["pouch_no"].strip() if "pouch_no" in choice else row.pouch_no
    return Item(row=row, batch=batch, pouch_no=pouch_no, skip=bool(choice.get("skip")))


def _order(item):
    sheet, number = item.row.src.split("!")
    return (item.batch, sheet, int(number))


def _suggest(items):
    """The next free number in each batch, above the highest numeric one in use.

    Starting above the maximum is what makes a suggestion collision-free
    against numbers; a text pouch no. like "3A" is not counted.
    """
    top = defaultdict(int)
    for code, pouch_no in Pouch.objects.exclude(pouch_no=None).values_list("batch__code", "pouch_no"):
        if pouch_no.isdigit():
            top[code] = max(top[code], int(pouch_no))
    for item in items:
        if item.pouch_no.isdigit():
            top[item.batch] = max(top[item.batch], int(item.pouch_no))
    for item in sorted((i for i in items if not i.pouch_no), key=_order):
        top[item.batch] += 1
        item.suggestion = str(top[item.batch])


def _match(items):
    """The pouch each row already is: by batch + pouch no., else a numberless one from the same row.

    The source-row fallback is what lets a reviewer number a pouch imported
    without one: the row now carries a number the pouch does not, and without
    the fallback it would open a second pouch. It must be the same batch too,
    or a row inserted above it in the register would re-target it.
    """
    keyed = {(p.batch.code, p.pouch_no): p for p in Pouch.objects.exclude(pouch_no=None).select_related("batch")}
    unkeyed = {p.src: p for p in Pouch.objects.filter(pouch_no=None).exclude(src="").select_related("batch")}
    for item in items:
        if not item.problem:
            hit = keyed.get((item.batch, item.pouch_no)) if item.pouch_no else None
            loose = None if hit else unkeyed.get(item.row.src)
            item.existing = hit or (loose if loose and loose.batch.code == item.batch else None)
    ids = [item.existing.pk for item in items if item.existing]
    held = {p.pk: p for p in services.stocked(Pouch.objects.filter(pk__in=ids))}
    for item in items:
        if item.existing:
            pouch = held[item.existing.pk]
            item.held_pcs, item.held_ct, item.held_rate = pouch.on_pcs, pouch.on_ct, pouch.rate
            item.recount = (
                (item.row.pcs is not None and item.row.pcs != (pouch.on_pcs or 0))
                or (item.row.ct is not None and item.row.ct != (pouch.on_ct or 0))
            )


def analyse(rows, decisions=None):
    decisions = decisions or {}
    items = [_item(row, decisions.get(row.src) or {}) for row in rows]
    live = [item for item in items if not item.skip]
    for item in live:
        row = item.row
        if not rules.parse_batch_code(item.batch):
            item.problem = "Batch code does not read as family · class · number · box colour"
        elif (row.ct is not None and row.ct < 0) or (row.pcs is not None and row.pcs < 0):
            item.problem = "Negative weight or pieces"
    first = {}
    for item in live:
        if item.problem or not item.pouch_no:
            continue
        key = (item.batch, item.pouch_no)
        if key in first:
            item.problem = f"{item.batch} · {item.pouch_no} is also {first[key]}"
        else:
            first[key] = item.row.src
    _match(live)
    _suggest(items)
    return items


def read_decisions(post, items, decisions):
    """The review form's answers, merged into what was already decided."""
    decisions = dict(decisions or {})
    fill = bool(post.get("fill_suggested"))
    for item in items:
        src = item.row.src
        if f"pouch_no:{src}" not in post:
            continue
        choice = {
            "batch": (post.get(f"batch:{src}") or "").strip(),
            "pouch_no": (post.get(f"pouch_no:{src}") or "").strip(),
            "skip": bool(post.get(f"skip:{src}")),
        }
        if fill and not choice["pouch_no"] and item.suggestion:
            choice["pouch_no"] = item.suggestion
        decisions[src] = choice
    return decisions


def attention(items):
    return [item for item in items if item.problem or item.skip or not item.pouch_no]


def counts(items):
    live = [item for item in items if not item.skip]
    return {
        "rows": len(items),
        "skip": len(items) - len(live),
        "blocked": sum(1 for i in live if i.problem),
        "create": sum(1 for i in live if not i.problem and not i.existing),
        "update": sum(1 for i in live if i.existing),
        "no_pouch_no": sum(1 for i in live if not i.pouch_no),
        "recount": sum(1 for i in live if i.recount),
    }


def _batch(code, cache):
    if code in cache:
        return cache[code]
    family, cls, seq, box = rules.parse_batch_code(code)
    colour, _ = BoxColour.objects.get_or_create(
        code=box, defaults={"label": "? unresolved", "swatch": UNRESOLVED_SWATCH, "confirmed": False}
    )
    for kind, part in ((CodePart.FAMILY, family), (CodePart.CLASS, cls)):
        CodePart.objects.get_or_create(kind=kind, code=part, defaults={"label": "? unknown", "confirmed": False})
    cache[code], _ = Batch.objects.get_or_create(
        code=code, defaults={"box_colour": colour, "family": family, "cls": cls, "seq": seq}
    )
    return cache[code]


def _fields(item):
    row = item.row
    return {
        "pouch_no": item.pouch_no or None, "carton": row.carton, "category": row.category,
        "stone_name": row.stone_name, "colour": row.colour, "shape": row.shape, "cut": row.cut,
        "quality": row.quality, "size_text": row.size_text, "remarks": row.remarks, "src": row.src,
        "countable": row.pcs is not None,
    }


@transaction.atomic
def commit(items, user, import_batch=None):
    require(user, INV_MASTERS, "Only a role that edits inventory records can import stock.")
    blocked = [item for item in items if item.problem and not item.skip]
    if blocked:
        raise ServiceError(f"{len(blocked)} rows still need a decision.")
    result = {"created": 0, "updated": 0, "recounted": 0, "skipped": 0}
    # a re-import touches every row, so nothing here may cost a query per unchanged row
    cache, fresh = Batch.objects.in_bulk(field_name="code"), []
    for item in items:
        if item.skip:
            result["skipped"] += 1
            continue
        if item.existing is None:
            fresh.append((_batch(item.batch, cache), _fields(item), item.row.pcs, item.row.ct, item.row.rate))
            continue
        pouch = item.existing
        fields = _fields(item)
        changed = [name for name, value in fields.items() if getattr(pouch, name) != value]
        for name in changed:
            setattr(pouch, name, fields[name])
        if changed:
            pouch.save(update_fields=changed)
        result["updated"] += 1
        if item.recount:
            services.recount(user, pouch, item.row.pcs, item.row.ct, note=f"re-imported from {item.row.src}")
            result["recounted"] += 1
        if item.row.rate is not None and item.row.rate != item.held_rate:
            services.add_price(user, pouch, PriceEntry.VALUATION, item.row.rate, timezone.localdate())
    result["created"] = len(services.open_pouches(user, fresh, import_batch=import_batch))
    log(user, "IMPORT", "inv_pouch", import_batch.pk if import_batch else "-", f"stones import {result}")
    return result
