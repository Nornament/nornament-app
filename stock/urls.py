from django.urls import path

from . import views

app_name = "stock"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # ── stock ────────────────────────────────────────────────────────────
    path("pieces/", views.piece_list, name="piece_list"),
    path("pieces/rows/", views.piece_rows, name="piece_rows"),
    path("pieces/new/", views.piece_form, name="piece_new"),
    path("pieces/<str:jewel_code>/", views.piece_detail, name="piece_detail"),
    path("pieces/<str:jewel_code>/edit/", views.piece_form, name="piece_edit"),
    path("pieces/<str:jewel_code>/bom/", views.piece_bom, name="piece_bom"),
    path("pieces/<str:jewel_code>/bom/edit/", views.piece_bom_edit, name="piece_bom_edit"),
    path("pieces/<str:jewel_code>/scenarios/", views.piece_scenarios, name="piece_scenarios"),
    path("pieces/<str:jewel_code>/sell/", views.sell_piece_view, name="sell_piece"),
    path("pieces/<str:jewel_code>/melt/", views.melt_piece_view, name="melt_piece"),
    path("pieces/<str:jewel_code>/move/", views.move_piece_view, name="move_piece"),
    path("pieces/<str:jewel_code>/reserve/", views.reserve_piece_view, name="reserve_piece"),
    path("pieces/<str:jewel_code>/repair/", views.repair_open, name="repair_open"),
    # ── catalogue ────────────────────────────────────────────────────────
    path("styles/", views.style_list, name="style_list"),
    path("styles/new/", views.style_form, name="style_new"),
    path("styles/<str:style_code>/edit/", views.style_form, name="style_edit"),
    # ── reference ────────────────────────────────────────────────────────
    path("materials/", views.material_list, name="material_list"),
    path("rates/", views.rate_list, name="rate_list"),
    path("rates/set/", views.set_rate_view, name="set_rate"),
    # ── counts ───────────────────────────────────────────────────────────
    path("counts/", views.count_list, name="count_list"),
    path("counts/open/", views.count_open, name="count_open"),
    path("counts/<int:count_id>/", views.count_detail, name="count_detail"),
    path("counts/<int:count_id>/scan/", views.count_scan, name="count_scan"),
    path("counts/<int:count_id>/unscan/", views.count_unscan, name="count_unscan"),
    path("counts/<int:count_id>/close/", views.count_close, name="count_close"),
    # ── workshop ─────────────────────────────────────────────────────────
    path("repairs/", views.repair_list, name="repair_list"),
    path("repairs/<int:job_id>/complete/", views.repair_complete, name="repair_complete"),
    path("melt/", views.melt_list, name="melt_list"),
    # ── admin ────────────────────────────────────────────────────────────
    path("sales/", views.sale_list, name="sale_list"),
    path("reports/", views.reports, name="reports"),
    path("reports/margin/", views.margin_report, name="margin_report"),
    path("data/", views.data, name="data"),
    path("audit/", views.audit, name="audit"),
    path("settings/", views.settings_view, name="settings"),
    path("exports/pieces.csv", views.piece_export, name="piece_export"),
]
