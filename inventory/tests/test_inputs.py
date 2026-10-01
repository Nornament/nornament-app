from datetime import date
from decimal import Decimal

import pytest

from inventory import inputs
from stock.services import ServiceError


def test_blank_is_none():
    assert inputs.decimal("  ", "Weight") is None
    assert inputs.whole("", "Pieces") is None
    assert inputs.day(None) is None


def test_numbers_read_with_or_without_grouping():
    assert inputs.decimal("1,800.50", "Cost / ct") == Decimal("1800.50")
    assert inputs.whole("12", "Pieces") == 12


@pytest.mark.parametrize("raw", ["abc", "NaN", "Infinity", "1e12"])
def test_anything_else_is_refused_by_its_label(raw):
    with pytest.raises(ServiceError, match="Weight"):
        inputs.decimal(raw, "Weight")


def test_more_than_four_decimal_places_is_refused_not_rounded():
    with pytest.raises(ServiceError, match="Weight: 0.00001 has more than 4 decimal places"):
        inputs.decimal("0.00001", "Weight")
    assert inputs.decimal("0.0001", "Weight") == Decimal("0.0001")
    assert inputs.decimal("12.50000", "Weight") == Decimal("12.5")         # trailing zeros are not places


def test_pieces_are_whole():
    with pytest.raises(ServiceError, match="whole number"):
        inputs.whole("2.5", "Pieces")


def test_dates():
    assert inputs.day("2026-10-01") == date(2026, 10, 1)
    with pytest.raises(ServiceError, match="Expected back"):
        inputs.day("2026-02-30", "Expected back")
