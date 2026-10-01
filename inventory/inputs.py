"""Reading the ledger forms' fields: blank is ``None``, anything else must read.

Every refusal names the field, so the message on the form says which box is wrong.
"""
from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_date

from stock.services import ServiceError


def decimal(raw, label):
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        value = None
    # the columns hold ten digits before the point; NaN and Infinity parse but are not numbers
    if value is None or not value.is_finite() or abs(value) >= 10 ** 10:
        raise ServiceError(f"{label}: {raw} is not a number.")
    return value


def whole(raw, label):
    value = decimal(raw, label)
    if value is None:
        return None
    if value != value.to_integral_value():
        raise ServiceError(f"{label} must be a whole number.")
    return int(value)


def day(raw, label="Date"):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = parse_date(raw)
    except ValueError:
        value = None
    if value is None:
        raise ServiceError(f"{label}: {raw} does not read as a date.")
    return value
