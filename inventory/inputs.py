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
    if value.normalize().as_tuple().exponent < -4:     # the columns keep 4 places; never round silently
        raise ServiceError(f"{label}: {raw} has more than 4 decimal places.")
    return value


def whole(raw, label):
    value = decimal(raw, label)
    if value is None:
        return None
    if value != value.to_integral_value():
        raise ServiceError(f"{label} must be a whole number.")
    return int(value)


def fits(model, **fields):
    """Refuse typed text longer than its column, in words, rather than a database error."""
    for name, value in fields.items():
        limit = model._meta.get_field(name).max_length
        if isinstance(value, str) and limit and len(value) > limit:
            label = model._meta.get_field(name).verbose_name
            raise ServiceError(f"{label[:1].upper()}{label[1:]} is too long: at most {limit} characters.")


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
