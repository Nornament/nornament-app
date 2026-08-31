"""The quote calculator, server-side.

The standalone HTML calculator carried its own ``PURITY`` table — the very
hardcoding migration 0032b exists to warn about, where 925 silver was priced
off the gold rate. Here every rate comes from ``stock.MetalPurity`` and
``stock.Metal``, so a purity prices off the metal it actually belongs to and an
admin rate change moves the quote.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from stock.models import MetalPurity
from stock.services import chart_rate, metal_rate, round_to

ZERO = Decimal("0")


@dataclass
class Component:
    kind: str  # 'metal' | 'stone' | 'other'
    label: str
    weight: Decimal
    rate: Decimal
    unit: str = "g"
    karat: str | None = None
    detail: str = ""

    @property
    def amount(self):
        return round_to(self.weight * self.rate, 0)


@dataclass
class QuoteItem:
    name: str
    code: str = ""
    making_rate: Decimal = ZERO  # per gram of metal
    components: list = field(default_factory=list)

    @property
    def metal_grams(self):
        return sum((c.weight for c in self.components if c.kind == "metal"), ZERO)

    @property
    def making(self):
        return round_to(self.making_rate * self.metal_grams, 0)

    @property
    def goods(self):
        return sum((c.amount for c in self.components), ZERO)

    @property
    def total(self):
        return self.goods + self.making


def purity_rates():
    """Every purity with its live per-gram sale and cost rate.

    This replaces the hardcoded ``PURITY`` dict. Silver reads silver's rate.
    """
    return [
        {
            "karat": purity.karat,
            "metal": purity.metal_id,
            "metal_name": purity.metal.name,
            "sale_rate": metal_rate(purity.karat, "SALE"),
            "cost_rate": metal_rate(purity.karat, "COST"),
            "sale_factor": purity.sale_factor,
            "true_fineness": purity.true_fineness,
        }
        for purity in MetalPurity.objects.select_related("metal").order_by("metal_id", "sort_order")
    ]


def metal_component(label, karat, grams, side="SALE"):
    return Component(
        kind="metal",
        label=label,
        weight=Decimal(str(grams)),
        rate=metal_rate(karat, side),
        unit="g",
        karat=karat,
        detail=f"{grams} g {karat}",
    )


def stone_component(label, material_code, carats, size_band="", side="SALE", chart=None, rate=None):
    if rate is None:
        rate = chart_rate(material_code, size_band, side, chart) or ZERO
    return Component(
        kind="stone",
        label=label,
        weight=Decimal(str(carats)),
        rate=Decimal(str(rate)),
        unit="ct",
        detail=f"{carats} ct",
    )


def quote_total(items):
    return sum((item.total for item in items), ZERO)


def distribute_to_total(item, target):
    """Nudge an item to a round number by moving the making charge.

    The old calculator spread the difference across every component, which made
    a stone rate that no chart agrees with. Making is the honest place to
    absorb a rounding: it is the number that is negotiable.
    """
    target = Decimal(str(target))
    if item.metal_grams <= 0:
        return item
    item.making_rate = max(ZERO, round_to((target - item.goods) / item.metal_grams, 2))
    return item


def stone_rates(chart=None):
    """Every priced material on the default chart, for the calculator's picker.

    The legacy calculator had no such list — a stone rate was typed in from
    memory. These come off the same rate chart the BOM screens price against,
    so a quote and a costing cannot disagree about what a stone is worth.
    """
    from stock.models import RateChart, RateChartLine

    chart_id = chart.pk if isinstance(chart, RateChart) else chart
    if chart_id is None:
        default = RateChart.objects.filter(is_default=True).first()
        if default is None:
            return []
        chart_id = default.pk
    lines = (
        RateChartLine.objects.filter(chart_id=chart_id, sale_rate__isnull=False)
        .select_related("material")
        .order_by("material__item_code", "size_band")
    )
    return [
        {
            "code": line.material.item_code,
            "name": line.material.item_name,
            "band": line.size_band or "",
            "uom": line.rate_uom or line.material.default_uom or "ct",
            "sale_rate": float(line.sale_rate or 0),
            "cost_rate": float(line.cost_rate or 0),
        }
        for line in lines
    ]
