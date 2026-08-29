"""The scenario builder, and the BOM editor's two making-charge options.

These are screens, not arithmetic — the arithmetic they drive is in
``test_costing.py``. What is asserted here is that a scenario can be built and
granted from ``settings/?tab=scen``, and that saving the BOM keeps the rates
and the charge basis that were on it.
"""
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from stock import services
from stock.enums import ChargeBasis, Uom
from stock.models import BomLine, Piece, Scenario, ScenarioRole

pytestmark = pytest.mark.django_db

SETTINGS = reverse("stock:settings")


@pytest.fixture
def admin_client(client, admin_user_):
    client.force_login(admin_user_)
    return client


def _post(client, data):
    return client.post(f"{SETTINGS}?tab=scen", data, follow=True)


def _new_scenario(**kwargs):
    """A complete builder POST, so a test only states what it is varying."""
    return {
        "code": "TARGET35",
        "name": "Target 35%",
        "method": Scenario.VALUE_ADDED,
        "target_pct": "35",
        "spread_by": "COST",
        "min_multiple": "1.0",
        "max_multiple": "8.0",
        "is_active": "on",
    } | kwargs


# ── the builder ──────────────────────────────────────────────────────────────
def test_the_scenarios_tab_renders_the_list_and_the_editor(admin_client, scenarios):
    listing = admin_client.get(f"{SETTINGS}?tab=scen")
    assert listing.status_code == 200
    assert b"Retail" in listing.content
    editor = admin_client.get(f"{SETTINGS}?tab=scen&scenario=new")
    assert editor.status_code == 200
    # the four controls of the design, plus the per-category absorbers
    for field in (b"id_method", b"id_target_pct", b"id_spread_by", b"id_spread_over_0"):
        assert field in editor.content


def test_an_admin_builds_a_scenario_with_the_categories_it_may_absorb(admin_client, materials):
    response = _post(admin_client, _new_scenario(spread_over=["DIAMOND", "SETTING"]))
    assert response.status_code == 200
    scenario = Scenario.objects.get(code="TARGET35")
    assert scenario.method == Scenario.VALUE_ADDED
    assert set(scenario.spread_over) == {"DIAMOND", "SETTING"}
    assert scenario.target_pct == Decimal("35.000")


def test_a_target_margin_scenario_without_a_percentage_is_refused(admin_client, materials):
    _post(admin_client, _new_scenario(target_pct=""))
    assert not Scenario.objects.filter(code="TARGET35").exists()


def test_a_multiplier_scenario_keeps_a_factor_per_category(admin_client, materials):
    _post(
        admin_client,
        _new_scenario(
            code="EXH", name="Exhibition", method=Scenario.MULTIPLIER, target_pct="", mult_DIAMOND="3", mult_SETTING="2"
        ),
    )
    scenario = Scenario.objects.get(code="EXH")
    assert scenario.multipliers == {"DIAMOND": "3", "SETTING": "2"}


def test_making_a_scenario_the_default_stands_the_old_one_down(admin_client, scenarios, materials):
    """A partial unique index enforces one default — clearing the old one has
    to happen in the same transaction or the save is a 500, not a message."""
    _post(admin_client, _new_scenario(is_default="on"))
    assert Scenario.objects.filter(is_default=True).count() == 1
    assert Scenario.objects.get(is_default=True).code == "TARGET35"


def test_granting_a_role_the_right_to_switch_implies_the_right_to_see(admin_client, materials):
    accounts = Group.objects.get(name="ACCOUNTS")
    _post(admin_client, _new_scenario(may_switch=[str(accounts.pk)]))
    role = ScenarioRole.objects.get(scenario__code="TARGET35", group=accounts)
    assert role.may_switch and role.may_see


def test_a_role_that_sees_no_prices_cannot_be_granted_a_scenario(admin_client, materials):
    graphic = Group.objects.get(name="GRAPHIC")
    _post(admin_client, _new_scenario(may_see=[str(graphic.pk)], may_switch=[str(graphic.pk)]))
    assert not ScenarioRole.objects.filter(scenario__code="TARGET35", group=graphic).exists()


def test_editing_a_scenario_keeps_its_code_and_drops_a_role_that_was_unticked(admin_client, materials):
    accounts = Group.objects.get(name="ACCOUNTS")
    _post(admin_client, _new_scenario(may_see=[str(accounts.pk)]))
    scenario = Scenario.objects.get(code="TARGET35")
    _post(admin_client, _new_scenario(pk=scenario.pk, code="RENAMED", name="Target 40%", target_pct="40"))
    scenario.refresh_from_db()
    assert scenario.code == "TARGET35"  # identity, not a label
    assert scenario.target_pct == Decimal("40.000")
    assert not scenario.roles.exists()


def test_a_scenario_pricing_live_pieces_is_not_deleted(admin_client, piece, scenarios):
    piece.scenario = scenarios
    piece.save(update_fields=["scenario"])
    _post(admin_client, {"pk": scenarios.pk, "delete": "1"})
    assert Scenario.objects.filter(pk=scenarios.pk).exists()


def test_a_sales_user_cannot_reach_the_builder(client, sales_user, materials):
    client.force_login(sales_user)
    assert client.get(f"{SETTINGS}?tab=scen").status_code == 403
    assert client.post(f"{SETTINGS}?tab=scen", _new_scenario()).status_code == 403
    assert not Scenario.objects.filter(code="TARGET35").exists()


# ── the BOM editor's making charges ──────────────────────────────────────────
def _bom_post(piece, rows):
    data = {"line-TOTAL_FORMS": str(len(rows)), "line-INITIAL_FORMS": str(len(rows)),
            "line-MIN_NUM_FORMS": "0", "line-MAX_NUM_FORMS": "1000", "note": "test"}
    for index, row in enumerate(rows):
        for key, value in row.items():
            data[f"line-{index}-{key}"] = value
    return data


def test_saving_the_bom_keeps_the_rates_and_the_charge_basis(admin_client, piece, materials):
    """The bug this screen shipped with: it rebuilt every line from four
    fields, so correcting one stone silently zeroed the making charge."""
    url = reverse("stock:piece_bom_edit", args=[piece.jewel_code])
    response = admin_client.post(
        url,
        _bom_post(
            piece,
            [
                {"material": "G", "qty_value": "4", "qty_uom": Uom.GM, "cost_rate": "11611", "sale_rate": "11766"},
                {"material": "DRKL", "qty_value": "1.5", "qty_uom": Uom.CT, "cost_rate": "150000", "sale_rate": "180000"},
                {"material": "MAKING", "qty_uom": Uom.GM, "basis": ChargeBasis.BY_NET_METAL_WT,
                 "cost_rate": "1200", "sale_rate": "1500"},
            ],
        ),
        follow=True,
    )
    assert response.status_code == 200
    piece.refresh_from_db()
    making = BomLine.objects.get(piece=piece, version_no=piece.current_bom_version, material__item_code="MAKING")
    assert making.basis == ChargeBasis.BY_NET_METAL_WT
    assert making.sale_rate == Decimal("1500")
    assert making.sale_amount == Decimal("6000")  # 1500 × 4 g of net metal, not of gross
    diamond = BomLine.objects.get(piece=piece, version_no=piece.current_bom_version, material__item_code="DRKL")
    assert diamond.qty_value == Decimal("1.5")  # the correction landed
    assert diamond.sale_rate == Decimal("180000")


def test_a_making_line_can_be_switched_to_a_fixed_charge(admin_client, piece, materials):
    url = reverse("stock:piece_bom_edit", args=[piece.jewel_code])
    admin_client.post(
        url,
        _bom_post(
            piece,
            [
                {"material": "G", "qty_value": "4", "qty_uom": Uom.GM, "cost_rate": "11611", "sale_rate": "11766"},
                {"material": "DRKL", "qty_value": "1.125", "qty_uom": Uom.CT, "cost_rate": "150000", "sale_rate": "180000"},
                {"material": "MAKING", "qty_uom": Uom.GM, "basis": ChargeBasis.FLAT,
                 "cost_rate": "4000", "sale_rate": "7500"},
            ],
        ),
        follow=True,
    )
    piece.refresh_from_db()
    making = BomLine.objects.get(piece=piece, version_no=piece.current_bom_version, material__item_code="MAKING")
    assert making.basis == ChargeBasis.FLAT
    assert making.sale_amount == Decimal("7500")  # the charge, not the charge × 4 g


def test_a_production_user_cannot_wipe_a_rate_it_may_not_see(client, piece, materials, django_user_model):
    """Production may edit the BOM but sees neither cost nor sale — the two
    columns are not on its form, so they are carried forward, not blanked."""
    user = django_user_model.objects.create_user(username="prod", password="x")
    user.must_change_password = False
    user.save(update_fields=["must_change_password"])
    user.groups.add(Group.objects.get(name="PRODUCTION"))
    client.force_login(user)
    url = reverse("stock:piece_bom_edit", args=[piece.jewel_code])
    assert client.get(url).status_code == 200
    client.post(
        url,
        _bom_post(
            piece,
            [
                {"material": "G", "qty_value": "4", "qty_uom": Uom.GM},
                {"material": "DRKL", "qty_value": "2", "qty_uom": Uom.CT},
                {"material": "MAKING", "qty_uom": Uom.GM, "basis": ChargeBasis.BY_NET_METAL_WT},
            ],
        ),
        follow=True,
    )
    piece.refresh_from_db()
    lines = {
        l.material.item_code: l
        for l in BomLine.objects.filter(piece=piece, version_no=piece.current_bom_version).select_related("material")
    }
    assert lines["DRKL"].qty_value == Decimal("2")  # the weight it may edit changed
    assert lines["DRKL"].sale_rate == Decimal("180000")  # the rate it may not see survived
    assert lines["MAKING"].sale_rate == Decimal("1500")


def test_the_pricing_tab_and_the_bom_tab_quote_the_same_figure(admin_client, piece, scenarios, chart):
    """One engine behind both, so they cannot drift apart."""
    for scenario in Scenario.objects.all():
        assert services.live_sale_price(piece, scenario=scenario) == services.scenario_price(piece, scenario).price
    response = admin_client.get(reverse("stock:piece_detail", args=[piece.jewel_code]) + "?tab=pricing")
    assert response.status_code == 200
