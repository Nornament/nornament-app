"""Template helpers the stock screens need."""
from django import template

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
