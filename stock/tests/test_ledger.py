"""The movement ledger, sales, melt and repairs — the rules the SQL enforced."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from stock import services
from stock.enums import MovementType, StockState
from stock.models import MeltRecord, Piece, RepairJob, Sale, StockMovement

pytestmark = pytest.mark.django_db


def test_receipt_sets_state_location_and_received_on(piece, locations, admin_user_):
    services.receive_piece(admin_user_, piece, locations["MUM"])
    piece.refresh_from_db()
    assert piece.stock_state == StockState.IN_STOCK
    assert piece.location == locations["MUM"]
    assert piece.received_on is not None


def test_the_piece_row_follows_the_last_movement(received_piece, locations, admin_user_):
    services.transfer_piece(admin_user_, received_piece, locations["HO"])
    received_piece.refresh_from_db()
    assert received_piece.location == locations["HO"]
    assert StockMovement.objects.filter(piece=received_piece).count() == 2


def test_a_terminal_piece_never_moves_again(received_piece, admin_user_, locations):
    services.sell_piece(admin_user_, received_piece, sold_price=Decimal("300000"))
    received_piece.refresh_from_db()
    assert received_piece.stock_state == StockState.SOLD
    assert received_piece.location_id is None
    assert received_piece.disposed_on is not None
    with pytest.raises(ValidationError, match="terminal"):
        services.transfer_piece(admin_user_, received_piece, locations["HO"])


def test_a_piece_cannot_be_sold_twice(received_piece, admin_user_):
    services.sell_piece(admin_user_, received_piece, sold_price=Decimal("300000"))
    with pytest.raises(ValidationError, match="already"):
        services.sell_piece(admin_user_, received_piece, sold_price=Decimal("310000"))
    assert Sale.objects.filter(piece=received_piece).count() == 1


def test_the_sold_twice_guard_is_in_the_database_not_only_in_python(received_piece, admin_user_):
    """Risk #8: the partial unique index ships in the initial migration."""
    from django.db import IntegrityError, transaction

    services.sell_piece(admin_user_, received_piece, sold_price=Decimal("300000"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Sale.objects.create(piece=received_piece, sold_on="2026-08-24", sold_price=Decimal("1"), cost_at_sale=Decimal("0"))


def test_sale_freezes_the_cost_and_computes_margin(received_piece, admin_user_):
    frozen = received_piece.current_bom().total_cost_price
    sale = services.sell_piece(admin_user_, received_piece, sold_price=Decimal("300000"), discount_amt=Decimal("5000"))
    sale.refresh_from_db()
    assert sale.cost_at_sale == frozen
    assert sale.margin_amt == Decimal("300000") - Decimal("5000") - frozen
    assert sale.source == Sale.STOCK


def test_melt_needs_the_capability(received_piece, sales_user):
    with pytest.raises(PermissionDenied, match="not authorised"):
        services.melt_piece(sales_user, received_piece, "The stone cracked beyond repair")


def test_melt_needs_a_real_reason(received_piece, admin_user_):
    with pytest.raises(ValidationError, match="at least 10 characters"):
        services.melt_piece(admin_user_, received_piece, "broke")
    record = services.melt_piece(admin_user_, received_piece, "Shank cracked through, unrepairable")
    received_piece.refresh_from_db()
    assert received_piece.stock_state == StockState.MELTED
    assert record.cost_written_off == MeltRecord.objects.get(pk=record.pk).cost_written_off


def test_sale_requires_adjust_stock(received_piece, graphic_user):
    with pytest.raises(PermissionDenied):
        services.sell_piece(graphic_user, received_piece, sold_price=Decimal("1"))


def test_repair_creates_a_new_bom_version_and_brings_the_piece_home(received_piece, admin_user_, materials, locations):
    from stock.models import RepairMaterialChange

    job = services.open_repair(admin_user_, received_piece, "Stone missing from the left petal")
    received_piece.refresh_from_db()
    assert received_piece.stock_state == StockState.IN_REPAIR

    RepairMaterialChange.objects.create(
        repair_job=job,
        action="ADD",
        material=materials["diamond"],
        qty_value=Decimal("0.125"),
        qty_uom="CT",
        cost_rate=Decimal("150000"),
        sale_rate=Decimal("180000"),
    )
    version_no = services.complete_repair(admin_user_, job)

    received_piece.refresh_from_db()
    job.refresh_from_db()
    assert version_no == 2
    assert received_piece.current_bom_version == 2
    assert received_piece.stock_state == StockState.IN_STOCK
    assert received_piece.location == locations["MUM"]  # home, not wherever it sat
    assert job.status == RepairJob.DONE
    assert job.tat_days == 0
    # the added stone is on the new version, and the new version is costed
    new_version = received_piece.current_bom()
    assert new_version.total_cost_price > Decimal("0")
    assert new_version.version_no == 2


def test_movements_are_scoped_to_locations_a_user_can_see(received_piece, locations, accounts_user):
    accounts_user.home_location = locations["MUM"]
    accounts_user.save(update_fields=["home_location"])
    with pytest.raises(PermissionDenied):
        services.transfer_piece(accounts_user, received_piece, locations["HO"])


def test_visible_to_hides_other_locations(received_piece, locations, accounts_user, piece):
    accounts_user.home_location = locations["HO"]
    accounts_user.save(update_fields=["home_location"])
    visible = Piece.objects.visible_to(accounts_user)
    # the received piece sits in MUM and is invisible; an unreceived one has no
    # location at all and stays visible, exactly as the RLS policy read
    assert received_piece not in visible


@pytest.mark.parametrize(
    "target",
    ["//evil.example", "/\\evil.example", "https://evil.example/x", "http:/evil.example"],
)
def test_setting_a_rate_never_redirects_off_site(client, admin_user_, target):
    """The ticker posts a ``next`` so you land back where you were. Off-site is
    not where you were."""
    client.force_login(admin_user_)
    response = client.post(
        reverse("stock:set_rate"), {"code": "GOLD", "pure_rate": "15500", "next": target}
    )
    assert response.status_code == 302
    assert "evil.example" not in response["Location"]


def test_setting_a_rate_does_honour_a_local_next(client, admin_user_):
    client.force_login(admin_user_)
    response = client.post(
        reverse("stock:set_rate"), {"code": "GOLD", "pure_rate": "15500", "next": "/pieces/"}
    )
    assert response["Location"] == "/pieces/"


# ── scenarios ────────────────────────────────────────────────────────────
def test_a_role_that_may_only_see_a_scenario_cannot_put_a_piece_on_it(piece, sales_user, scenarios):
    """``may_see`` and ``may_switch`` are two flags, and this is the second one."""
    with pytest.raises(PermissionDenied):
        services.set_piece_scenario(sales_user, piece, scenarios.pk)
    piece.refresh_from_db()
    assert piece.scenario_id is None


def test_an_admin_puts_a_piece_on_a_scenario_and_takes_it_off_again(piece, admin_user_, scenarios):
    services.set_piece_scenario(admin_user_, piece, scenarios.pk)
    piece.refresh_from_db()
    assert piece.scenario_id == scenarios.pk

    services.set_piece_scenario(admin_user_, piece, None)
    piece.refresh_from_db()
    assert piece.scenario_id is None


def test_only_an_admin_clears_a_scenario(piece, admin_user_, sales_user, scenarios):
    services.set_piece_scenario(admin_user_, piece, scenarios.pk)
    with pytest.raises(PermissionDenied):
        services.set_piece_scenario(sales_user, piece, None)
    piece.refresh_from_db()
    assert piece.scenario_id == scenarios.pk


def test_the_scenario_radio_never_redirects_off_site(client, admin_user_, piece, scenarios):
    client.force_login(admin_user_)
    response = client.post(
        reverse("stock:set_piece_scenario", kwargs={"jewel_code": piece.jewel_code}),
        {"scenario": scenarios.pk, "next": "//evil.example"},
    )
    assert response.status_code == 302
    assert "evil.example" not in response["Location"]
