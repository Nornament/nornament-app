from django.urls import path

from . import views

app_name = "stock"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("pieces/", views.piece_list, name="piece_list"),
    path("pieces/rows/", views.piece_rows, name="piece_rows"),
    path("pieces/<str:jewel_code>/", views.piece_detail, name="piece_detail"),
    path("pieces/<str:jewel_code>/bom/", views.piece_bom, name="piece_bom"),
    path("pieces/<str:jewel_code>/scenarios/", views.piece_scenarios, name="piece_scenarios"),
    path("pieces/<str:jewel_code>/sell/", views.sell_piece_view, name="sell_piece"),
    path("pieces/<str:jewel_code>/melt/", views.melt_piece_view, name="melt_piece"),
    path("pieces/<str:jewel_code>/move/", views.move_piece_view, name="move_piece"),
    path("materials/", views.material_list, name="material_list"),
    path("rates/", views.rate_list, name="rate_list"),
    path("rates/set/", views.set_rate_view, name="set_rate"),
    path("counts/", views.count_list, name="count_list"),
    path("counts/open/", views.count_open, name="count_open"),
    path("counts/<int:count_id>/", views.count_detail, name="count_detail"),
    path("counts/<int:count_id>/scan/", views.count_scan, name="count_scan"),
    path("counts/<int:count_id>/unscan/", views.count_unscan, name="count_unscan"),
    path("counts/<int:count_id>/close/", views.count_close, name="count_close"),
    path("repairs/", views.repair_list, name="repair_list"),
    path("repairs/<int:job_id>/complete/", views.repair_complete, name="repair_complete"),
    path("sales/", views.sale_list, name="sale_list"),
    path("reports/margin/", views.margin_report, name="margin_report"),
    path("exports/pieces.csv", views.piece_export, name="piece_export"),
]
