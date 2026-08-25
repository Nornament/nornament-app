"""The masking rule, stated once.

In Supabase a SALES login received ``null`` where a cost sat, because 22 views
wrapped every sensitive column in ``CASE WHEN app.has_cap(...)``. That worked
until someone wrote a twenty-third view.

Here, services always return the real numbers and *presentation* decides what
to show: build a piece row through :func:`piece_row`, or export through
:func:`mask_rows`, and the same eight columns are gated in the same place. The
permanent regression test in ``stock/tests/test_masking.py`` is what keeps this
honest — it logs in as a SALES user, renders every screen and asserts no cost,
vendor or margin value appears anywhere in the response.
"""
from accounts.capabilities import MANAGE_MATERIALS, VIEW_COST, VIEW_MARGIN, VIEW_SALE, VIEW_VENDOR

#: field name -> the permission required to see it
GATED_FIELDS = {
    "cost_price": VIEW_COST,
    "current_cost": VIEW_COST,
    "metal_cost_rate": VIEW_COST,
    "cost_at_sale": VIEW_COST,
    "src_cost_price": VIEW_COST,
    "cost_rate": VIEW_COST,
    "cost_amount": VIEW_COST,
    "sale_price": VIEW_SALE,
    "gold_rate_used": VIEW_SALE,
    "src_sale_price": VIEW_SALE,
    "src_tag_price": VIEW_SALE,
    "sale_rate": VIEW_SALE,
    "sale_amount": VIEW_SALE,
    "sold_price": VIEW_SALE,
    "margin": VIEW_MARGIN,
    "current_margin": VIEW_MARGIN,
    "margin_amt": VIEW_MARGIN,
    "vendor_code": VIEW_VENDOR,
    "vendor_name": VIEW_VENDOR,
    "vendor_avg_tat_days": VIEW_VENDOR,
    "material_breakup": MANAGE_MATERIALS,
}


def visible_fields(user, fields):
    """Of ``fields``, the ones this user may see. Order is preserved."""
    return [name for name in fields if allowed(user, name)]


def allowed(user, field_name):
    permission = GATED_FIELDS.get(field_name)
    if permission is None:
        return True
    return bool(user and user.is_authenticated and user.has_perm(permission))


def mask(user, row):
    """Drop every key this user may not see. Not ``None`` — absent.

    A masked ``None`` reads as "there is no cost"; an absent key reads as
    "not yours to see", and a template that loops over keys cannot leak it.
    """
    return {key: value for key, value in row.items() if allowed(user, key)}


def mask_rows(user, rows):
    return [mask(user, row) for row in rows]


def piece_row(user, piece, *, with_prices=True):
    """One row of the piece list — ``api.jewel``, masked for this user.

    The prices are computed here rather than stored, exactly as the SQL view
    computed them per request: a frozen sale price is a price from a metal rate
    that no longer exists.
    """
    from . import services

    version = piece.current_bom()
    row = {
        "jewel_code_id": piece.pk,
        "jewel_code": piece.jewel_code,
        "style_code": piece.style.style_code,
        "design_name": piece.style.name,
        "category": piece.style.category.name if piece.style.category_id else None,
        "collection": piece.style.collection.name if piece.style.collection_id else None,
        "sub_category": piece.sub_category,
        "karat": piece.metal_purity,
        "metal_colour": piece.metal_colour,
        "size_label": piece.size_label,
        "diamond_quality": piece.diamond_quality,
        "measured_gross_wt_gm": piece.measured_gross_wt_gm,
        "net_metal_wt_gm": version.net_metal_wt_gm if version else None,
        "bom_weight_gm": version.bom_weight_gm if version else None,
        "stock_state": piece.stock_state,
        "stock_state_display": piece.get_stock_state_display(),
        "location_code": piece.location.code if piece.location_id else None,
        "location": piece.location.name if piece.location_id else None,
        "received_on": piece.received_on,
        "disposed_on": piece.disposed_on,
        "huid": piece.huid,
        "bom_version": version.version_no if version else None,
        "on_website": piece.on_website,
        "remarks": piece.remarks,
        "updated_at": piece.updated_at,
        "bom_is_summary": piece.bom_is_summary,
        "src_system": piece.src_system,
        "src_ref": piece.src_ref,
        "src_net_wt_gm": piece.src_net_wt_gm,
        "src_cost_price": piece.src_cost_price,
        "src_sale_price": piece.src_sale_price,
        "src_tag_price": piece.src_tag_price,
        "vendor_code": piece.vendor.code if piece.vendor_id else None,
        "vendor_name": piece.vendor.name if piece.vendor_id else None,
        "vendor_avg_tat_days": piece.vendor.avg_tat_days if piece.vendor_id else None,
    }
    if with_prices:
        sale_price = services.live_sale_price(piece) if allowed(user, "sale_price") or allowed(user, "margin") else None
        cost_price = version.total_cost_price if version else None
        row |= {
            "sale_price": sale_price,
            "gold_rate_used": services.alloy_sale_rate(piece.metal_purity),
            "cost_price": cost_price,
            "current_cost": services.current_cost(piece),
            "metal_cost_rate": services.alloy_cost_rate(piece.metal_purity),
            "margin": (sale_price - cost_price) if (sale_price is not None and cost_price is not None) else None,
            "current_margin": (sale_price - services.current_cost(piece)) if sale_price is not None else None,
        }
    return mask(user, row)
