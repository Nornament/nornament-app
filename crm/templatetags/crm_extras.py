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
