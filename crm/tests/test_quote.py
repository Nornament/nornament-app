"""The quote calculator reads live rates, not a table baked into the page."""
from decimal import Decimal

import pytest

from crm import quote

pytestmark = pytest.mark.django_db


def test_purity_rates_come_from_the_database(rates):
    by_karat = {row["karat"]: row for row in quote.purity_rates()}
    assert by_karat["18K"]["sale_rate"] == Decimal("11766")
    # the hardcoded PURITY table in the old calculator had no silver at all,
    # so 925 would have been priced off gold. Here it reads silver.
    assert by_karat["925"]["metal"] == "SILVER"
    assert by_karat["925"]["sale_rate"] == Decimal("260")


def test_an_admin_rate_change_moves_the_quote(rates, admin_user_):
    from stock import services

    before = quote.metal_component("Metal", "18K", 4).amount
    services.set_metal_rate(admin_user_, "GOLD", Decimal("20000"))
    after = quote.metal_component("Metal", "18K", 4).amount
    assert after > before


def test_a_quote_item_totals_goods_plus_making(rates, materials, chart):
    item = quote.QuoteItem(
        name="Earrings",
        making_rate=Decimal("1500"),
        components=[
            quote.metal_component("Metal (18K)", "18K", 4),
            quote.stone_component("Diamond RKL", "DRKL", Decimal("1.125")),
        ],
    )
    assert item.metal_grams == Decimal("4")
    assert item.making == Decimal("6000")
    assert item.total == item.goods + item.making
    # the stone priced off the chart, not off a number typed into the page
    assert item.components[1].rate == Decimal("180000")


def test_rounding_to_a_total_moves_making_and_never_a_stone_rate(rates, materials, chart):
    item = quote.QuoteItem(
        name="Earrings",
        making_rate=Decimal("1500"),
        components=[
            quote.metal_component("Metal (18K)", "18K", 4),
            quote.stone_component("Diamond RKL", "DRKL", Decimal("1.125")),
        ],
    )
    stone_rate = item.components[1].rate
    quote.distribute_to_total(item, Decimal("260000"))
    assert item.components[1].rate == stone_rate
    assert item.total == Decimal("260000")


def test_a_target_below_the_goods_value_zeroes_making_rather_than_going_negative(rates, materials, chart):
    item = quote.QuoteItem(
        name="Earrings", making_rate=Decimal("1500"), components=[quote.metal_component("Metal (18K)", "18K", 4)]
    )
    quote.distribute_to_total(item, Decimal("1"))
    assert item.making_rate == Decimal("0")
