"""The rail's data-quality filters: the pouches with one problem, in the batch page's table.

Internal only. Each list is the rail's own count, because both apply ``rows.CHECKS``
to the same rows.
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect

from . import rows
from .views import _client, _everything, _page

#: the rail's labels, which the pages share
TITLES = {"misfiled": "Misfiled colour", "no_pouch_no": "No pouch no.", "no_photo": "Missing photos",
          "no_size": "No size in mm"}
PAGE = 200


@login_required
def quality(request, check):
    if _client(request):
        return redirect("inventory:shelf")
    if check not in rows.CHECKS:
        raise Http404("No such check.")
    everything = _everything(request)
    found = [r for r in everything if rows.CHECKS[check](r)]
    return _page(request, "inventory/quality.html", everything, tab="quality", check=check, title=TITLES[check],
                 pouches=Paginator(found, PAGE).get_page(request.GET.get("page")), count=len(found),
                 money=bool(found) and "pouch_value" in found[0])
