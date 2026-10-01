"""Diamond assortments — routed now so the diamond screens can link to one another; built by its own task."""
from django.http import Http404


def assorts(request):
    raise Http404("Not built yet.")


def assort_reverse(request, pk):
    raise Http404("Not built yet.")
