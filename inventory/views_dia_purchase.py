"""Diamond purchases — routed now so the diamond screens can link to one another; built by its own task."""
from django.http import Http404


def purchase(request):
    raise Http404("Not built yet.")


def purchase_reverse(request, pk):
    raise Http404("Not built yet.")
