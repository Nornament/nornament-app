"""Diamond Search stock, and what every diamond page shares.

The "Viewing as" selector is the prototype's; here it is real only for an
admin, who sees the page exactly as another role would — the masking runs for
a stand-in holding that role's permissions. Everyone else sees their own role.
"""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.shortcuts import render

from accounts.capabilities import ROLE_GROUPS, VIEW_COST, VIEW_MARGIN, VIEW_SALE
from accounts.context_processors import _role_code

from . import dia_rows, dia_search, dia_seed
from .models import DiamondTerm

TABLE_CAP = 300


class PreviewUser:
    """Just enough of a user for masking: authenticated, holding one role's rights."""

    is_authenticated = True
    is_superuser = False

    def __init__(self, role):
        group = Group.objects.get(name=role)
        self.perms = {f"{p.content_type.app_label}.{p.codename}"
                      for p in group.permissions.select_related("content_type")}

    def has_perm(self, perm, obj=None):
        return perm in self.perms


def viewer(request):
    """(who the page is built for, their role code). Only an admin may borrow another role."""
    wanted = request.GET.get("as", "")
    if wanted in ROLE_GROUPS and request.user.is_admin() and wanted != "ADMIN":
        return PreviewUser(wanted), wanted
    return request.user, _role_code(request.user)


def dia_page(request, template, **context):
    """Every diamond page: the diamond rail, the diamond tabs, no client toggle."""
    context.update(side="diamonds", drail=dia_rows.rail_counts())
    return render(request, template, context)


def _order(kind):
    return list(DiamondTerm.objects.filter(kind=kind).order_by("sort", "value").values_list("value", flat=True))


def _totals(rows, everything):
    """Totals of what is in view; which money keys exist is read off any row, so an
    empty selection still shows ₹0 to a role that may see money, not "Hidden"."""
    sample = everything[0] if everything else {}
    out = {"ct": sum((r["ct"] or 0) for r in rows), "n": len(rows)}
    for key in ("cost_amount", "sale_amount"):
        if key in sample:
            out[key] = sum((r[key] or 0) for r in rows)
    if "cost_amount" in out and "sale_amount" in out and "margin" in sample:
        cost, sale = out["cost_amount"], out["sale_amount"]
        out["margin"] = (sale - cost) / cost * 100 if cost else None
        out["gross"] = sale - cost
    return out


@login_required
def search(request):
    user, role = viewer(request)
    everything = dia_rows.line_rows(user)
    f = dia_search.Filters.from_query(request.GET)
    shown = dia_search.select(everything, f)
    table = sorted(shown, key=lambda r: -(r["ct"] or 0))[:TABLE_CAP]
    can = {"cost": user.has_perm(VIEW_COST), "sale": user.has_perm(VIEW_SALE), "margin": user.has_perm(VIEW_MARGIN),
           "job": user.has_perm("accounts.inv_job"), "assort": user.has_perm("accounts.inv_assort"),
           "purchase": user.has_perm("accounts.inv_purchase")}
    shapes_here = {r["shape"] for r in dia_search.select(everything, f, skip="shape") if r["category"] == f.cat}
    return dia_page(
        request, "inventory/diamonds/search.html", dtab="search", f=f, role=role,
        role_label=ROLE_GROUPS[role]["name"], roles=[(code, spec["name"]) for code, spec in ROLE_GROUPS.items()],
        can_preview=request.user.is_admin(), can=can, rows=table, shown=len(shown), total=len(everything),
        all_ct=sum((r["ct"] or 0) for r in everything), totals=_totals(shown, everything),
        cats=dia_search.category_bubbles(everything, f), cat_shapes=len(shapes_here),
        shape_bubbles=dia_search.bubbles(everything, f, "shape"),
        col_bubbles=dia_search.bubbles(everything, f, "col", order=[v for v in dia_seed.COLOUR_LADDER]),
        clar_bubbles=dia_search.bubbles(everything, f, "clar", order=[v for v in dia_seed.CLARITY_LADDER]),
        band_bubbles=dia_search.bubbles(everything, f, "band", order=_order(DiamondTerm.BAND)),
        all_href=f.with_cat("").href(), clear_href=f.cleared().href(), money=bool(table) and "cost_rate" in table[0],
        sale_money=bool(table) and "sale_rate" in table[0], margin_money=bool(table) and "margin" in table[0],
    )
