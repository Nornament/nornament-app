"""The document page and its actions — routed now so the other ledger screens can link to it."""
from django.http import Http404


def document(request, pk):
    raise Http404("Not built yet.")


def document_settle(request, pk):
    raise Http404("Not built yet.")


def document_undo(request, pk):
    raise Http404("Not built yet.")


def document_reverse(request, pk):
    raise Http404("Not built yet.")
