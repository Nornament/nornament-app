"""The data-quality filters — routed now so the rail can link to them; built by its own task."""
from django.http import Http404


def quality(request, check):
    raise Http404("Not built yet.")
