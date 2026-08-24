"""The stock count engine: resumable, idempotent, and frozen once closed."""
import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from stock import services
from stock.models import Piece, StockCount, StockCountScan

pytestmark = pytest.mark.django_db


def test_open_count_resumes_rather_than_starting_a_second(admin_user_, locations):
    first = services.open_count(admin_user_, "MUM")
    second = services.open_count(admin_user_, "MUM")
    assert first.pk == second.pk
    assert StockCount.objects.filter(location=locations["MUM"]).count() == 1


def test_one_open_count_per_location_is_a_database_rule(admin_user_, locations):
    from django.db import IntegrityError, transaction

    services.open_count(admin_user_, "MUM")
    with pytest.raises(IntegrityError), transaction.atomic():
        StockCount.objects.create(count_ref="SC-DUP", location=locations["MUM"], status=StockCount.OPEN)


def test_scan_verdicts(admin_user_, received_piece, locations):
    count = services.open_count(admin_user_, "MUM")
    found = services.scan_piece(admin_user_, count, "ER00738")
    assert found["verdict"] == "FOUND"

    again = services.scan_piece(admin_user_, count, "ER00738")
    assert again["verdict"] == "ALREADY"
    assert StockCountScan.objects.filter(count=count).count() == 1

    unknown = services.scan_piece(admin_user_, count, "NOSUCHCODE")
    assert unknown["verdict"] == "UNKNOWN"


def test_a_piece_the_books_place_elsewhere_says_so(admin_user_, received_piece, locations):
    count = services.open_count(admin_user_, "HO")
    result = services.scan_piece(admin_user_, count, "ER00738")
    assert result["verdict"] == "ELSEWHERE"
    assert "books say MUM" in result["note"]


def test_a_sold_piece_scanned_in_a_count_says_the_books_disagree(admin_user_, received_piece):
    from decimal import Decimal

    count = services.open_count(admin_user_, "MUM")
    services.sell_piece(admin_user_, received_piece, sold_price=Decimal("300000"))
    result = services.scan_piece(admin_user_, count, "ER00738")
    assert result["verdict"] == "NOT_STOCK"
    assert "books say sold" in result["note"]


def test_scanner_suffixes_are_stripped(admin_user_, received_piece):
    count = services.open_count(admin_user_, "MUM")
    result = services.scan_piece(admin_user_, count, "  er00738__2026-08-24T10:00  ")
    assert result["verdict"] == "FOUND"
    assert result["code"] == "ER00738"


def test_count_state_counts_expected_found_and_missing(admin_user_, received_piece, locations, piece):
    count = services.open_count(admin_user_, "MUM")
    state = services.count_state(admin_user_, count)
    assert state["expected"] == 1 and state["found"] == 0 and state["missing"] == 1

    services.scan_piece(admin_user_, count, "ER00738")
    state = services.count_state(admin_user_, count)
    assert state["found"] == 1 and state["missing"] == 0
    assert state["missing_list"] == []


def test_unscan_undoes_one_scan(admin_user_, received_piece):
    count = services.open_count(admin_user_, "MUM")
    services.scan_piece(admin_user_, count, "ER00738")
    state = services.unscan_piece(admin_user_, count, "ER00738")
    assert state["found"] == 0


def test_a_closed_count_is_frozen(admin_user_, received_piece, locations):
    count = services.open_count(admin_user_, "MUM")
    services.scan_piece(admin_user_, count, "ER00738")
    result = services.close_count(admin_user_, count, notes="End of month")
    assert result["status"] == StockCount.CLOSED and result["found"] == 1

    # the world moves on; the closed count does not
    received_piece.location = locations["HO"]
    received_piece.save(update_fields=["location"])
    count.refresh_from_db()
    assert services.count_state(admin_user_, count)["found"] == 1
    with pytest.raises(ValidationError, match="already closed"):
        services.scan_piece(admin_user_, count, "ER00738")


def test_counting_needs_the_privileged_capability(sales_user, locations):
    with pytest.raises(PermissionDenied, match="permission to run a stock count"):
        services.open_count(sales_user, "MUM")


def test_a_user_cannot_count_a_location_they_cannot_see(accounts_user, locations):
    accounts_user.home_location = locations["MUM"]
    accounts_user.save(update_fields=["home_location"])
    with pytest.raises(PermissionDenied):
        services.open_count(accounts_user, "HO")
