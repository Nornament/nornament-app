"""Costing, to the paisa.

The figures here are the SQL's own: rounding at ``line_rounding_dp`` before
summing, totals at ``total_rounding_dp``, PCS converting to zero grams, and
metal priced off the metal its purity belongs to.
"""
from decimal import Decimal

import pytest

from stock import services
from stock.enums import ChargeBasis, Uom
from stock.models import BomLine, SystemSetting

pytestmark = pytest.mark.django_db


def test_metal_rate_follows_the_metal_not_the_gold_rate(rates):
    """The bug migration 0032b fixed: 925 silver priced at 0.925 × gold."""
    assert services.metal_rate("18K", "SALE") == Decimal("11766")
    assert services.metal_rate("18K", "COST") == Decimal("11611")
    # silver sells at the 999 rate and costs at its true 0.925
    assert services.metal_rate("925", "SALE") == Decimal("260")
    assert services.metal_rate("925", "COST") == Decimal("241")
    assert services.metal_rate("925", "SALE") < services.metal_rate("18K", "SALE") / 10


def test_line_weight_conversions(rates):
    assert services.line_weight_gm(Decimal("1.125"), Uom.CT) == Decimal("0.2250")
    assert services.line_weight_gm(Decimal("4"), Uom.GM) == Decimal("4.0")
    # PCS is deliberately zero grams: a finding has a price, not a weight
    assert services.line_weight_gm(Decimal("3"), Uom.PCS) == Decimal("0.0")


def test_recost_sets_every_derived_figure(piece, materials):
    version = piece.current_bom()
    # 4 g gold at 11611 + 1.125 ct at 150000 + making 1200 × 4 g
    assert version.net_metal_wt_gm == Decimal("4.000")
    assert version.total_cost_price == Decimal("4") * 11611 + Decimal("168750") + Decimal("4800")
    assert version.total_sale_price == Decimal("4") * 11766 + Decimal("202500") + Decimal("6000")
    assert version.making_value == Decimal("6000")
    assert version.goods_value == version.total_sale_price - version.making_value
    # BOM weight excludes labour and converts carats: 4 g + 1.125 ct × 0.2
    assert version.bom_weight_gm == Decimal("4.225")


def test_by_net_metal_weight_line_is_snapped_to_the_metal_weight(piece, materials):
    making = BomLine.objects.get(piece=piece, material=materials["making"])
    assert making.basis == ChargeBasis.BY_NET_METAL_WT
    assert making.qty_value == Decimal("4.0000")
    assert making.qty_uom == Uom.GM


def test_live_sale_price_uses_todays_metal_rate(piece, rates, admin_user_):
    before = services.live_sale_price(piece)
    services.set_metal_rate(admin_user_, "GOLD", Decimal("20000"))
    after = services.live_sale_price(piece)
    # only the metal line moves: 4 g at the new 18K sale rate
    assert after - before == (services.metal_rate("18K", "SALE") - Decimal("11766")) * 4


def test_current_cost_is_replacement_cost_not_the_frozen_one(piece, admin_user_):
    frozen = piece.current_bom().total_cost_price
    assert services.current_cost(piece) == frozen
    services.set_metal_rate(admin_user_, "GOLD", Decimal("20000"))
    piece.refresh_from_db()
    assert piece.current_bom().total_cost_price == frozen  # frozen stays frozen
    assert services.current_cost(piece) > frozen  # replacement cost moves


def test_rounding_decimals_come_from_settings(piece, materials, admin_user_):
    SystemSetting.objects.filter(pk="line_rounding_dp").update(value="2")
    line = BomLine.objects.get(piece=piece, material=materials["diamond"])
    line.cost_rate = Decimal("150000.4444")
    line.save(update_fields=["cost_rate"])
    services.recost_piece(piece, user=admin_user_)
    line.refresh_from_db()
    assert line.cost_amount == Decimal("168750.50")


def test_uom_guards_from_the_line_trigger(piece, materials, admin_user_):
    with pytest.raises(Exception, match="must be GM"):
        services.set_bom(
            admin_user_,
            piece,
            [{"material": materials["gold"], "qty_value": 1, "qty_uom": Uom.CT, "cost_rate": 1, "sale_rate": 1}],
        )
    with pytest.raises(Exception, match="must be CT or PCS"):
        services.set_bom(
            admin_user_,
            piece,
            [{"material": materials["diamond"], "qty_value": 1, "qty_uom": Uom.GM, "cost_rate": 1, "sale_rate": 1}],
        )


def test_scenario_chart_prices_stones_off_the_chart(piece, scenarios, chart):
    price = services.scenario_price(piece, scenarios)
    assert price.method == "CHART"
    assert price.metal_sale == Decimal("47064")  # 4 g × 11766, metal never marked up
    assert price.stone_sale == Decimal("202500")  # 1.125 ct at the chart's 180000
    assert price.price == price.metal_sale + price.making_sale + price.stone_sale


def test_scenario_value_added_targets_a_markup_on_everything_but_metal(piece, scenarios):
    from stock.models import Scenario

    price = services.scenario_price(piece, Scenario.objects.get(code="VA100"))
    # value added cost = stones 168750 + making 4800; the target doubles it,
    # and making's sale value comes off the top, leaving the stones to carry it
    assert price.stone_sale == (Decimal("168750") + Decimal("4800")) * 2 - Decimal("6000")
    assert price.metal_sale == Decimal("47064")  # unchanged: metal passes through


def test_value_added_floors_at_the_minimum_multiple(piece, materials, admin_user_):
    from stock.models import Scenario

    scenario = Scenario.objects.get(code="VA100")
    scenario.min_multiple = Decimal("2.5")
    scenario.save(update_fields=["min_multiple"])
    price = services.scenario_price(piece, scenario)
    assert price.capped == "floor"
    assert price.stone_sale == Decimal("168750") * Decimal("2.5")


def test_the_bom_sale_side_follows_the_piece_s_scenario(piece, scenarios, chart):
    """What the BOM tab totals is what the Pricing tab quotes for the row in use."""
    from stock.models import Scenario

    on_own_lines = services.live_sale_price(piece)
    for code in ("RETAIL", "VA100"):
        scenario = Scenario.objects.get(code=code)
        assert services.live_sale_price(piece, scenario=scenario) == services.scenario_price(piece, scenario).price
    # and with no scenario the piece stays on the rates written on its own lines
    assert services.live_sale_price(piece) == on_own_lines


def test_a_scenario_moves_the_stone_lines_and_nothing_else(piece, scenarios, chart):
    """Metal passes through at the live rate and making keeps its own line."""
    from stock.models import Scenario

    value_added = Scenario.objects.get(code="VA100")
    frozen = {row["line"].line_no: row for row in services.sale_lines(piece)}
    under = {row["line"].line_no: row for row in services.sale_lines(piece, scenario=value_added)}
    moved = {
        no
        for no, row in under.items()
        if row["sale_amount"] != frozen[no]["sale_amount"]
    }
    assert moved, "the chart scenario should reprice at least one stone line"
    for no in moved:
        assert not (under[no]["line"].material.is_metal or under[no]["line"].material.is_labour)
