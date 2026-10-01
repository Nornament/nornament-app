"""Record a purchase — routed now so the other ledger screens can link to it; built by its own task."""
from django.http import Http404


def purchase(request):
    raise Http404("Not built yet.")
