"""The metal-rate ticker that sits in the stock app's top bar.

`SimpleLazyObject` so the query only runs when a template actually reads it —
the CRM shell never does.
"""
from django.utils.functional import SimpleLazyObject


def _metals():
    from .models import Metal

    return list(Metal.objects.order_by("code"))


def ticker(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"nav_metals": SimpleLazyObject(_metals)}
