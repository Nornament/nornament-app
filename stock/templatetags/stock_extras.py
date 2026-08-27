"""Template helpers the stock screens need."""
from django import template

from crm.templatetags import crm_extras

register = template.Library()


@register.filter
def get(mapping, key):
    """``{{ thumbs|get:piece.pk }}`` — a dict lookup by variable key.

    Django templates cannot index a dict with a variable, and the thumbnail maps
    are keyed by primary key.
    """
    try:
        return mapping.get(key)
    except AttributeError:
        return None


# ``₹12,34,567`` — the legacy ``inr()``. Already written for the CRM screens;
# the stock pricing card wants the same grouping, so it is registered, not
# rewritten.
register.filter(crm_extras.inr)


@register.filter
def grouped(amount):
    """Indian grouping without the ``₹`` — the legacy's rate columns."""
    return crm_extras.inr(amount).replace("₹", "")
