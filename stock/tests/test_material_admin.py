"""Editing and deleting a material, and what happens to what points at it.

Every relation onto Material is PROTECT, so the interesting behaviour is all
in reassignment: three of the five are unique on (owner, material, size_band)
and a straight repoint would collide.
"""
from decimal import Decimal

import pytest
from django.urls import reverse

from stock import services
from stock.enums import ChargeBasis, Uom
from stock.models import (
    BomLine, Material, MaterialInventory, RateCard, RateCardLine,
    RateChart, RateChartLine,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def spare(db, materials):
    """A second diamond to move things onto."""
    return Material.objects.create(
        item_code="DRKL2", item_name="Diamond RKL fine", category_id="DIAMOND", default_uom=Uom.CT
    )


def test_usage_counts_every_relation(piece, materials, admin_user_):
    diamond = materials["diamond"]
    usage = services.material_usage(diamond)
    assert usage["bom_lines"] >= 1
    assert usage["pieces"] >= 1
    assert usage["total"] == sum(
        usage[k] for k, _, _ in services.MATERIAL_USES
    )


def test_a_material_nothing_points_at_deletes_cleanly(spare, admin_user_):
    services.delete_material(admin_user_, spare)
    assert not Material.objects.filter(item_code="DRKL2").exists()


def test_a_material_in_use_refuses_to_delete(piece, materials, admin_user_):
    diamond = materials["diamond"]
    with pytest.raises(services.ServiceError) as caught:
        services.delete_material(admin_user_, diamond)
    assert "still used" in str(caught.value)
    assert Material.objects.filter(pk=diamond.pk).exists()


def test_reassigning_moves_bom_lines_and_then_it_deletes(piece, materials, spare, admin_user_):
    diamond = materials["diamond"]
    before = BomLine.objects.filter(material=diamond).count()
    assert before

    services.delete_material(admin_user_, diamond, reassign_to=spare)
    assert not Material.objects.filter(pk=diamond.pk).exists()
    assert BomLine.objects.filter(material=spare).count() == before


def test_a_chart_line_the_target_already_has_is_dropped_not_duplicated(
    materials, spare, chart, admin_user_
):
    """unique_together (chart, material, size_band) — a repoint would collide."""
    diamond = materials["diamond"]
    RateChartLine.objects.update_or_create(
        chart=chart, material=diamond, size_band="",
        defaults={"cost_rate": Decimal("100"), "sale_rate": Decimal("200")},
    )
    RateChartLine.objects.update_or_create(
        chart=chart, material=spare, size_band="",
        defaults={"cost_rate": Decimal("300"), "sale_rate": Decimal("400")},
    )
    services.reassign_material(admin_user_, diamond, spare)

    lines = RateChartLine.objects.filter(chart=chart, material=spare, size_band="")
    assert lines.count() == 1, "the collision must not create a second line"
    assert lines.first().cost_rate == Decimal("300"), "the target's own rate wins"
    assert not RateChartLine.objects.filter(material=diamond).exists()


def test_a_chart_line_the_target_lacks_is_carried_over(materials, spare, chart, admin_user_):
    diamond = materials["diamond"]
    RateChartLine.objects.update_or_create(
        chart=chart, material=diamond, size_band="+2",
        defaults={"cost_rate": Decimal("111"), "sale_rate": Decimal("222")},
    )
    services.reassign_material(admin_user_, diamond, spare)
    moved = RateChartLine.objects.get(chart=chart, material=spare, size_band="+2")
    assert moved.cost_rate == Decimal("111")


def test_loose_stock_in_the_same_place_is_added_together(materials, spare, locations, admin_user_):
    diamond = materials["diamond"]
    where = locations["HO"]
    MaterialInventory.objects.create(
        material=diamond, location=where, size_band="", qty_value=Decimal("3"), qty_uom=Uom.CT, pcs=6
    )
    MaterialInventory.objects.create(
        material=spare, location=where, size_band="", qty_value=Decimal("4"), qty_uom=Uom.CT, pcs=8
    )
    services.reassign_material(admin_user_, diamond, spare)

    held = MaterialInventory.objects.get(material=spare, location=where, size_band="")
    assert held.qty_value == Decimal("7"), "two piles of the same thing are one pile"
    assert held.pcs == 14
    assert not MaterialInventory.objects.filter(material=diamond).exists()


def test_loose_stock_in_mismatched_units_is_refused(materials, spare, locations, admin_user_):
    """Adding 3 carats to 4 grams would be inventing a conversion."""
    diamond = materials["diamond"]
    where = locations["HO"]
    MaterialInventory.objects.create(
        material=diamond, location=where, size_band="", qty_value=Decimal("3"), qty_uom=Uom.CT
    )
    MaterialInventory.objects.create(
        material=spare, location=where, size_band="", qty_value=Decimal("4"), qty_uom=Uom.GM
    )
    with pytest.raises(services.ServiceError) as caught:
        services.reassign_material(admin_user_, diamond, spare)
    assert "units" in str(caught.value)


def test_a_material_cannot_be_reassigned_to_itself(materials, admin_user_):
    with pytest.raises(services.ServiceError):
        services.reassign_material(admin_user_, materials["diamond"], materials["diamond"])


def test_a_failed_reassign_leaves_everything_as_it_was(
    materials, spare, locations, piece, admin_user_
):
    """The units clash aborts mid-way; the BOM lines must not have moved."""
    diamond = materials["diamond"]
    where = locations["HO"]
    MaterialInventory.objects.create(
        material=diamond, location=where, size_band="", qty_value=Decimal("3"), qty_uom=Uom.CT
    )
    MaterialInventory.objects.create(
        material=spare, location=where, size_band="", qty_value=Decimal("4"), qty_uom=Uom.GM
    )
    before = BomLine.objects.filter(material=diamond).count()
    with pytest.raises(services.ServiceError):
        services.delete_material(admin_user_, diamond, reassign_to=spare)
    assert BomLine.objects.filter(material=diamond).count() == before
    assert Material.objects.filter(pk=diamond.pk).exists()


# ── the screens ──────────────────────────────────────────────────────────
def test_the_checkpoint_shows_what_points_at_it(client, admin_user_, piece, materials):
    client.force_login(admin_user_)
    r = client.get(reverse("stock:material_delete", args=[materials["diamond"].item_code]))
    assert r.status_code == 200
    assert b"is in use" in r.content
    assert b"Bill of material lines" in r.content


def test_the_checkpoint_says_so_when_nothing_points_at_it(client, admin_user_, spare):
    client.force_login(admin_user_)
    r = client.get(reverse("stock:material_delete", args=["DRKL2"]))
    assert b"Nothing points at this material" in r.content


def test_deleting_through_the_screen_reassigns(client, admin_user_, piece, materials, spare):
    client.force_login(admin_user_)
    code = materials["diamond"].item_code
    r = client.post(reverse("stock:material_delete", args=[code]), {"reassign_to": "DRKL2"})
    assert r.status_code == 302
    assert not Material.objects.filter(item_code=code).exists()
    assert BomLine.objects.filter(material=spare).exists()


def test_an_unknown_reassign_target_is_refused(client, admin_user_, piece, materials):
    client.force_login(admin_user_)
    code = materials["diamond"].item_code
    client.post(reverse("stock:material_delete", args=[code]), {"reassign_to": "NOPE"}, follow=True)
    assert Material.objects.filter(item_code=code).exists(), "nothing should have been deleted"


def test_a_login_without_manage_materials_is_refused(client, graphic_user, materials):
    client.force_login(graphic_user)
    code = materials["diamond"].item_code
    assert client.get(reverse("stock:material_delete", args=[code])).status_code == 403
    assert client.get(reverse("stock:material_edit", args=[code])).status_code == 403


def test_editing_a_material_saves(client, admin_user_, materials):
    client.force_login(admin_user_)
    code = materials["diamond"].item_code
    r = client.post(reverse("stock:material_edit", args=[code]), {
        "item_code": code, "item_name": "Renamed diamond",
        "category": "DIAMOND", "default_uom": "CT", "is_active": "on",
    })
    assert r.status_code == 302
    assert Material.objects.get(item_code=code).item_name == "Renamed diamond"


# ── retiring: the reversible half of removing a material ─────────────────
def test_a_retired_material_cannot_be_added_to_a_bom(piece, materials, spare, admin_user_):
    """The picker hides it; this is the half a direct POST cannot get past."""
    spare.is_active = False
    spare.save(update_fields=["is_active"])
    with pytest.raises(services.ServiceError) as caught:
        services.set_bom(admin_user_, piece, [
            {"material": spare, "qty_value": Decimal("1"), "qty_uom": Uom.CT},
        ])
    assert "retired" in str(caught.value)


def test_a_retired_material_already_on_a_piece_stays_editable(piece, materials, admin_user_):
    """Retiring is not retroactive — what was priced keeps pricing."""
    diamond = materials["diamond"]
    diamond.is_active = False
    diamond.save(update_fields=["is_active"])

    # the piece already carries it, so re-saving its BOM is allowed
    services.set_bom(admin_user_, piece, [
        {"material": diamond, "qty_value": Decimal("2"), "qty_uom": Uom.CT, "cost_rate": Decimal("5")},
    ])
    line = BomLine.objects.get(piece=piece, version_no=piece.current_bom_version)
    assert line.material_id == diamond.pk
    assert line.qty_value == Decimal("2.0000")


def test_an_import_will_not_revive_a_retired_material(materials, spare):
    """A workbook naming a retired code must stop, not quietly reuse it."""
    from stock.importers import ivy
    from stock.importers.analyse import analyse
    from stock.tests.fixtures_ivy import THREE_PRODUCTS, build_workbook as build

    Material.objects.filter(item_code="DRFGH VS-SI").update(is_active=False)
    Material.objects.get_or_create(
        item_code="DRFGH VS-SI",
        defaults={"item_name": "Diamond", "category_id": "DIAMOND", "default_uom": Uom.CT,
                  "is_active": False},
    )
    Material.objects.filter(item_code="DRFGH VS-SI").update(is_active=False)

    header, block = THREE_PRODUCTS[0]
    plan = analyse(ivy.parse(build(products=[(dict(header), block)])))
    row = next(r for r in plan.materials if r.key == "DRFGH VS-SI")
    assert row.problem and "retired" in row.problem


def test_the_settings_tab_marks_a_retired_material(client, admin_user_, materials, settings):
    settings.ALLOWED_HOSTS = ["testserver"]
    materials["diamond"].is_active = False
    materials["diamond"].save(update_fields=["is_active"])
    client.force_login(admin_user_)
    r = client.get(reverse("stock:settings") + "?tab=mats")
    assert b">retired</span>" in r.content
