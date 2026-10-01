"""A pouch's Movements page and its Record movement form.

Until the Record movement task builds this module the page is part 1's, and the
post route answers 404 — routed now so the other ledger screens can link to it.
"""
from django.http import Http404

from .views import movements  # noqa: F401  (the route's view until this module is built)


def movement_post(request, ref):
    raise Http404("Not built yet.")
