"""Costing, to the paisa.

The figures here are the SQL's own: rounding at ``line_rounding_dp`` before
summing, totals at ``total_rounding_dp``, PCS converting to zero grams, and
metal priced off the metal its purity belongs to.
"""
from decimal import Decimal

import pytest

from stock import services
from stock.enums import ChargeBasis, Uom
from stock.models import BomLine, Material, MaterialCategory, Piece, SystemSetting

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


def test_target_margin_asks_cost_plus_the_target_and_nothing_more(piece, scenarios):
    """The whole point of the rework: the asking price *is* cost + %.

    Metal and making are held, so what the stones absorb is the remainder
    worked backwards out of the target — never a markup added on top of it.
    """
    from stock.models import Scenario

    price = services.scenario_price(piece, Scenario.objects.get(code="VA100"))
    assert price.price == price.cost_today * 2  # +100%, exactly
    assert price.metal_sale == Decimal("47064")  # unchanged: metal passes through
    assert price.stone_sale == price.price - price.metal_sale - price.making_sale


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


# ── the scenario builder's four controls ─────────────────────────────────────
@pytest.fixture
def two_stone_piece(db, piece, materials, admin_user_):
    """The same piece with a second stone category on it, so a scenario that
    names one category can be told apart from one that names both."""
    setting = Material.objects.create(
        item_code="RUBY",
        item_name="Ruby",
        category=MaterialCategory.objects.get(pk="SETTING"),
        default_uom=Uom.CT,
    )
    services.set_bom(
        admin_user_,
        piece,
        [
            {"material": materials["gold"], "qty_value": Decimal("4"), "qty_uom": Uom.GM,
             "basis": ChargeBasis.BY_QTY, "cost_rate": Decimal("11611"), "sale_rate": Decimal("11766")},
            {"material": materials["diamond"], "qty_value": Decimal("1"), "qty_uom": Uom.CT,
             "basis": ChargeBasis.BY_QTY, "cost_rate": Decimal("10000"), "sale_rate": Decimal("12000")},
            {"material": setting, "qty_value": Decimal("2"), "qty_uom": Uom.CT,
             "basis": ChargeBasis.BY_QTY, "cost_rate": Decimal("5000"), "sale_rate": Decimal("6000")},
            {"material": materials["making"], "qty_value": None, "qty_uom": Uom.GM,
             "basis": ChargeBasis.BY_NET_METAL_WT, "cost_rate": Decimal("1200"), "sale_rate": Decimal("1500")},
        ],
    )
    return Piece.objects.get(pk=piece.pk)


def _target(**kwargs):
    from stock.models import Scenario

    return Scenario.objects.create(
        **{"code": "T", "name": "Target", "method": Scenario.VALUE_ADDED, "target_pct": Decimal("35")} | kwargs
    )


def test_spread_over_names_the_categories_that_absorb(two_stone_piece, chart):
    """Naming DIAMOND only leaves the setting stones on their own sale rate."""
    both = services.scenario_price(two_stone_piece, _target(code="BOTH", spread_over=["DIAMOND", "SETTING"]))
    diamond_only = services.scenario_price(
        two_stone_piece, _target(code="DIA", name="Diamond only", spread_over=["DIAMOND"])
    )
    # the total is the target either way — only who carries it changes
    target = services.round_to(both.cost_today * Decimal("1.35"), 0)
    assert both.price == diamond_only.price == target
    lines = {no: rate for no, rate in diamond_only.line_rates.items()}
    # the ruby line stays at its own 6000/ct; the diamond swallowed the rest
    assert Decimal("6000") in lines.values()
    assert Decimal("6000") not in both.line_rates.values()


def test_an_empty_spread_over_lets_every_stone_absorb(two_stone_piece, chart):
    """A scenario that names nothing still has to be able to price."""
    price = services.scenario_price(two_stone_piece, _target(code="ANY", spread_over=[]))
    assert price.price == services.round_to(price.cost_today * Decimal("1.35"), 0)
    assert len(price.line_rates) == 2  # both stone lines moved


def test_spread_by_weight_splits_on_grams_not_cost(two_stone_piece, chart):
    by_cost = services.scenario_price(two_stone_piece, _target(code="C", spread_by="COST"))
    by_weight = services.scenario_price(two_stone_piece, _target(code="W", name="W", spread_by="WEIGHT"))
    assert by_cost.price == by_weight.price  # the target is the target
    assert by_cost.line_rates != by_weight.line_rates  # but not carried the same way


@pytest.fixture
def heavy_piece(db, piece, materials, admin_user_):
    """The mockup's trap: 20 g of gold and one small stone. Metal and making
    already exceed a low target, so the stones would have to go below cost."""
    services.set_bom(
        admin_user_,
        piece,
        [
            {"material": materials["gold"], "qty_value": Decimal("20"), "qty_uom": Uom.GM,
             "basis": ChargeBasis.BY_QTY, "cost_rate": Decimal("11611"), "sale_rate": Decimal("11766")},
            {"material": materials["diamond"], "qty_value": Decimal("0.05"), "qty_uom": Uom.CT,
             "basis": ChargeBasis.BY_QTY, "cost_rate": Decimal("10000"), "sale_rate": Decimal("12000")},
            {"material": materials["making"], "qty_value": None, "qty_uom": Uom.GM,
             "basis": ChargeBasis.BY_NET_METAL_WT, "cost_rate": Decimal("1200"), "sale_rate": Decimal("1500")},
        ],
    )
    return Piece.objects.get(pk=piece.pk)


def test_the_target_refuses_a_percentage_the_piece_cannot_carry(heavy_piece, chart):
    """Metal and making alone can already exceed a low target — say so, and
    say what the lowest one this piece can carry actually is."""
    price = services.scenario_price(heavy_piece, _target(code="LOW", target_pct=Decimal("1")))
    assert price.capped == "below cost"
    assert price.min_pct is not None and price.min_pct > 1
    # and the stones are never priced under what they cost
    assert price.stone_sale >= price.stone_cost


def test_category_multipliers_price_each_category_off_its_own_cost(two_stone_piece, chart):
    from stock.models import Scenario

    scenario = Scenario.objects.create(
        code="EXH",
        name="Exhibition",
        method=Scenario.MULTIPLIER,
        multipliers={"DIAMOND": "3", "SETTING": "2"},
    )
    price = services.scenario_price(two_stone_piece, scenario)
    assert price.stone_sale == Decimal("10000") * 3 + Decimal("10000") * 2  # 1ct@10000, 2ct@5000
    assert price.metal_sale == Decimal("47064")  # metal still passes through


# ── making charges ───────────────────────────────────────────────────────────
def test_making_per_gram_uses_net_metal_weight_only(piece, scenarios, materials, admin_user_):
    """Adding a stone must not change what the making charge comes to."""
    before = services.scenario_price(piece, scenarios)
    services.set_bom(
        admin_user_,
        piece,
        [
            {"material": materials["gold"], "qty_value": Decimal("4"), "qty_uom": Uom.GM,
             "basis": ChargeBasis.BY_QTY, "cost_rate": Decimal("11611"), "sale_rate": Decimal("11766")},
            {"material": materials["diamond"], "qty_value": Decimal("5"), "qty_uom": Uom.CT,
             "basis": ChargeBasis.BY_QTY, "cost_rate": Decimal("150000"), "sale_rate": Decimal("180000")},
            {"material": materials["making"], "qty_value": None, "qty_uom": Uom.GM,
             "basis": ChargeBasis.BY_NET_METAL_WT, "cost_rate": Decimal("1200"), "sale_rate": Decimal("1500")},
        ],
    )
    after = services.scenario_price(Piece.objects.get(pk=piece.pk), scenarios)
    assert after.making_sale == before.making_sale == Decimal("1500") * 4
    assert after.stone_sale > before.stone_sale  # the stones moved, making did not


def test_making_can_be_a_fixed_charge_instead(piece, scenarios, materials, admin_user_):
    services.set_bom(
        admin_user_,
        piece,
        [
            {"material": materials["gold"], "qty_value": Decimal("4"), "qty_uom": Uom.GM,
             "basis": ChargeBasis.BY_QTY, "cost_rate": Decimal("11611"), "sale_rate": Decimal("11766")},
            {"material": materials["making"], "qty_value": Decimal("1"), "qty_uom": Uom.GM,
             "basis": ChargeBasis.FLAT, "cost_rate": Decimal("4000"), "sale_rate": Decimal("7500")},
        ],
    )
    price = services.scenario_price(Piece.objects.get(pk=piece.pk), scenarios)
    assert price.making_sale == Decimal("7500")  # flat, not 7500 × 4 g
    assert price.making_cost == Decimal("4000")


def test_the_two_tabs_agree_to_the_rupee_on_a_multi_stone_piece(two_stone_piece, chart):
    """The rounding trap: one bucket, several lines.

    Rounding a sum once and summing per-line roundings are different numbers,
    so the Pricing tab and the BOM tab have to reach their totals the same way
    — and the remainder has to be apportioned so the lines add back up to it.
    """
    from stock.models import Scenario

    for scenario in (
        _target(code="R1", spread_by="COST"),
        _target(code="R2", name="R2", spread_by="WEIGHT"),
        _target(code="R3", name="R3", target_pct=Decimal("37")),
        Scenario.objects.create(code="R4", name="R4", method=Scenario.MULTIPLIER, multipliers={"DIAMOND": "2.7"}),
    ):
        price = services.scenario_price(two_stone_piece, scenario)
        assert services.live_sale_price(two_stone_piece, scenario=scenario) == price.price
        assert price.price == price.metal_sale + price.making_sale + price.stone_sale
        assert sum(price.line_amounts.values()) == price.stone_sale
        if scenario.method == Scenario.VALUE_ADDED and not price.capped:
            assert price.price == services.round_to(price.cost_today * (1 + scenario.target_pct / 100), 0)


def test_the_scenario_cost_is_the_same_figure_the_margin_is_measured_against(two_stone_piece, scenarios):
    """``cost_today`` on the row and ``current_cost`` in the margin column were
    two roundings of one number, and could differ by a rupee."""
    assert services.scenario_price(two_stone_piece, scenarios).cost_today == services.current_cost(two_stone_piece)
