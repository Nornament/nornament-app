"""The rows every inventory screen renders, built once and masked once.

A row is a plain dict. Money goes through ``stock.masking.mask`` like every
other screen in the app; client mode also strips the shelf layout, so the
server never sends what the client must not see. Templates test for a key
(``'pouch_value' in row``), never for a capability.

ponytail: every screen reads every pouch (≈3,000) and groups in Python —
one query, well under a second. Aggregate in SQL if the shelf passes ~50,000.
"""
from collections import Counter, defaultdict

from mediahub.models import MediaAsset
from stock.enums import MediaKind
from stock.masking import mask

from . import rules, services

#: what a client is never sent: where it is filed, what it cost, what is wrong with it
CLIENT_HIDDEN = {
    "batch_code", "pouch_no", "no_pouch_no", "carton", "family", "cls", "seq", "remarks", "src",
    "stone_rate", "pouch_value", "purchase_date", "supplier_name", "misfiled", "box_confirmed",
}


def _photos(pouch_ids):
    """First photo per pouch, by rank. One query."""
    first = {}
    assets = (
        MediaAsset.objects.filter(scope="pouch", scope_id__in=[str(i) for i in pouch_ids],
                                  kind=MediaKind.PHOTO, is_archived=False)
        .order_by("rank_order", "pk").values_list("scope_id", "pk")
    )
    for scope_id, pk in assets:
        first.setdefault(int(scope_id), pk)
    return first


def pouch_row(user, pouch, client=False, photo_id=None):
    box = pouch.batch.box_colour
    size_kind, size_display, _, _ = rules.parse_size(pouch.size_text)
    row = {
        "pk": pouch.pk, "ref": pouch.ref, "batch_pk": pouch.batch_id,
        "batch_code": pouch.batch.code, "pouch_no": pouch.pouch_no or "", "no_pouch_no": not pouch.pouch_no,
        "carton": pouch.carton, "box_colour": box.code, "box_label": box.label, "box_swatch": box.swatch,
        "box_confirmed": box.confirmed, "family": pouch.batch.family, "cls": pouch.batch.cls, "seq": pouch.batch.seq,
        "category": pouch.category, "stone_name": pouch.stone_name, "colour": pouch.colour,
        "shape": pouch.shape, "cut": pouch.cut, "quality": pouch.quality,
        "size_kind": size_kind, "size_display": size_display,
        "countable": pouch.countable, "pcs": pouch.on_pcs if pouch.countable else None, "ct": pouch.on_ct,
        "colour_hex": rules.colour_hex(pouch.colour), "misfiled": rules.is_misfiled(pouch.colour, box.label),
        "remarks": pouch.remarks, "src": pouch.src,
        "treatment": pouch.treatment, "origin": pouch.origin, "purchase_date": pouch.purchase_date,
        "supplier_name": pouch.supplier.name if pouch.supplier_id else None,
        "stone_rate": pouch.rate, "pouch_value": services.value_of(pouch),
        "photo_id": photo_id,
    }
    if client:
        row = {key: value for key, value in row.items() if key not in CLIENT_HIDDEN}
    return mask(user, row)


def pouch_rows(user, pouches, client=False):
    pouches = list(pouches)
    photos = _photos([p.pk for p in pouches])
    return [pouch_row(user, p, client=client, photo_id=photos.get(p.pk)) for p in pouches]


def _has(rows, key):
    return bool(rows) and key in rows[0]


def summarise(rows):
    """Totals for any set of rows — the whole shelf, one box colour, one batch.

    A total of something masked is itself masked: the key is left out, exactly
    as ``mask`` leaves out the field.
    """
    out = {
        "pouches": len(rows),
        "batches": len({r["batch_pk"] for r in rows}),
        "colours": len({r["box_colour"] for r in rows}),
        "ct": sum((r["ct"] or 0) for r in rows),
        "no_size": sum(1 for r in rows if r["size_kind"] in ("free", "none")),
        "no_photo": sum(1 for r in rows if not r["photo_id"]),
    }
    if _has(rows, "pouch_value"):
        out["value"] = sum((r["pouch_value"] or 0) for r in rows)
        out["unpriced"] = sum(1 for r in rows if r["pouch_value"] is None)
    if _has(rows, "misfiled"):
        out["misfiled"] = sum(1 for r in rows if r["misfiled"])
    if _has(rows, "no_pouch_no"):
        out["no_pouch_no"] = sum(1 for r in rows if r["no_pouch_no"])
        out["keyed"] = out["pouches"] - out["no_pouch_no"]
    if _has(rows, "carton"):
        out["boxes"] = sorted({r["carton"] for r in rows if r["carton"]}, key=lambda b: (len(b), b))
    return out


def by_colour(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["box_colour"]].append(row)
    colours = []
    for code, group in groups.items():
        first = group[0]
        colours.append({
            "code": code, "label": first["box_label"], "swatch": first["box_swatch"],
            "confirmed": first.get("box_confirmed", True), **summarise(group),
        })
    colours.sort(key=lambda c: -(c.get("value") if c.get("value") is not None else c["ct"]))
    return colours


def label(labels, kind, code):
    part = labels.get((kind, code))
    return part.label if part else "? unknown"


def by_batch(rows, labels):
    """One card per batch, in batch-code order (the rows arrive that way)."""
    groups = {}
    for row in rows:
        groups.setdefault(row["batch_pk"], []).append(row)
    batches = []
    for pk, group in groups.items():
        first = group[0]
        names = Counter(r["stone_name"] or "—" for r in group).most_common(2)
        card = {
            "pk": pk, "names": ", ".join(name for name, _ in names), "shape": first["shape"],
            "hex": first["colour_hex"], "photo_id": next((r["photo_id"] for r in group if r["photo_id"]), None),
            **summarise(group),
        }
        if "batch_code" in first:
            card["code"] = first["batch_code"]
            card["family_label"] = label(labels, "family", first["family"])
            card["class_label"] = label(labels, "class", first["cls"])
        batches.append(card)
    return batches


def shares(row, rows):
    """This pouch's value as a share of its batch, its box colour and all stock."""
    def pct(part, whole, places):
        return "—" if not part or not whole else f"{100 * part / whole:.{places}f}"

    value = row["pouch_value"]
    batch = sum((r["pouch_value"] or 0) for r in rows if r["batch_pk"] == row["batch_pk"])
    colour = sum((r["pouch_value"] or 0) for r in rows if r["box_colour"] == row["box_colour"])
    total = sum((r["pouch_value"] or 0) for r in rows)
    return {"batch": pct(value, batch, 0), "colour": pct(value, colour, 1), "all": pct(value, total, 2)}


def decoder(batch, labels):
    """The batch-code strip: what each segment of ``SR01Y`` means, and which are doubtful."""
    box = batch.box_colour
    family, cls = labels.get(("family", batch.family)), labels.get(("class", batch.cls))
    return [
        {"char": batch.family, "label": "material family", "value": family.label if family else "? unknown",
         "doubt": not (family and family.confirmed)},
        {"char": batch.cls, "label": "class", "value": cls.label if cls else "? unknown",
         "doubt": not (cls and cls.confirmed)},
        {"char": batch.seq, "label": "batch no.", "value": "sequence within colour", "doubt": False},
        {"char": box.code, "label": "box colour", "value": box.label, "doubt": not box.confirmed},
    ]
