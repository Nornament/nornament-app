"""The diamond Movements tab and the line ledger — routed now so the tabs and Search can link to
them; built by its own task."""
from django.http import Http404


def movements(request):
    raise Http404("Not built yet.")


def line(request, ref):
    raise Http404("Not built yet.")
