"""Template helpers the CRM screens need."""
from django import template

register = template.Library()


@register.filter
def lookup(mapping, key):
    """``{{ payout.billing|lookup:key }}`` — a dict lookup by variable key.

    Django templates cannot index a dict with a variable; the FoN tables are
    driven by the category list, so they need this.
    """
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def wa_number(phone):
    """A phone as wa.me digits — the legacy CRM's ``waNumber``, ported as-is.

    Digits only; an 11-digit number loses a leading 0; a bare 10-digit local
    number gains the 91 country code.
    """
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    return digits
