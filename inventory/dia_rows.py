"""Diamond rows, built once and masked once — the stones' rule, for lines.

Cost, sale and margin carry the stock app's gated names, so ``mask`` removes
them for a role without the right and the table simply has no such column.
"""
from collections import defaultdict
from decimal import Decimal

from stock.masking import mask

from . import dia_services
from .models import DiamondCode, DiamondLine, DiamondTerm


def line_row(user, line, rates):
    code = line.code
    shape, colour, clarity = line.shape, code.colour, code.clarity
    cost, sale = dia_services.price(line, rates)
    ct = line.on_ct
    row = {
        "pk": line.pk, "ref": line.ref, "category": line.category.value,
        "shape": shape.value if shape else "(unresolved)",
        "colour": colour.value if colour else "", "clarity": clarity.value if clarity else "",
        "cols": colour.grades() if colour else [], "clars": clarity.grades() if clarity else [],
        "band": line.band.value, "size_text": line.size_text, "batch": line.batch_no,
        "item_code": code.item_code, "confirmed": code.confirmed, "note": code.note,
        "ct": ct, "ct_lo": line.ct_lo, "ct_hi": line.ct_hi,
        "cost_rate": cost, "sale_rate": sale,
        "cost_amount": ct * cost if ct is not None and cost is not None else None,
        "sale_amount": ct * sale if ct is not None and sale is not None else None,
        "margin": (sale - cost) / cost * 100 if cost and sale is not None else None,
    }
    return mask(user, row)


def line_rows(user, queryset=None):
    rates = dia_services.rate_table()
    return [line_row(user, line, rates) for line in dia_services.stocked_lines(queryset)]


def term_usage(lines):
    """Lines and carats per term, for the Settings lists' "In use" and "Carats" columns."""
    usage = defaultdict(lambda: [0, Decimal("0")])
    for line in lines:
        shape = line.shape
        for t in (line.category, line.band, shape, line.code.colour, line.code.clarity):
            if t is not None:
                usage[t.pk][0] += 1
                usage[t.pk][1] += line.on_ct or 0
    return usage


def rail_counts():
    by_kind = defaultdict(int)
    for kind in DiamondTerm.objects.values_list("kind", flat=True):
        by_kind[kind] += 1
    return {"lines": DiamondLine.objects.count(), "codes": DiamondCode.objects.count(),
            "categories": by_kind["category"], "shapes": by_kind["shape"], "colours": by_kind["colour"],
            "clarities": by_kind["clarity"], "bands": by_kind["band"]}
