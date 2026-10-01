"""Diamond job cards — routed now so the diamond screens can link to one another; built by its own task."""
from django.http import Http404


def jobs(request):
    raise Http404("Not built yet.")


def job_new(request):
    raise Http404("Not built yet.")


def job_post(request, pk):
    raise Http404("Not built yet.")


def job_close(request, pk):
    raise Http404("Not built yet.")


def job_undo(request, pk):
    raise Http404("Not built yet.")


def job_reverse(request, pk):
    raise Http404("Not built yet.")
