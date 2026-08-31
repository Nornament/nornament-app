from django.urls import path

from . import views

app_name = "crm"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("search/", views.search, name="search"),
    path("settings/", views.settings_view, name="settings"),
    # ── PWA ──────────────────────────────────────────────────────────────
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("share/", views.share_inbox, name="share"),
    path("share/customers/", views.share_customers, name="share_customers"),
    # ── bulk import ──────────────────────────────────────────────────────
    path("import/<str:kind>/", views.bulk_import, name="bulk_import"),
    path("import/<str:kind>/template/", views.import_template, name="import_template"),
    # ── customers ────────────────────────────────────────────────────────
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/rows/", views.customer_rows, name="customer_rows"),
    path("customers/new/", views.customer_form, name="customer_new"),
    path("customers/export/", views.customer_export, name="customer_export"),
    path("customers/quick/", views.quick_customer, name="quick_customer"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", views.customer_form, name="customer_edit"),
    path("customers/<int:pk>/delete/", views.customer_delete, name="customer_delete"),
    path("customers/<int:pk>/temperature/", views.customer_apply_temperature, name="customer_temperature"),
    path("customers/<int:pk>/purchase/", views.add_purchase, name="add_purchase"),
    path("customers/<int:pk>/purchase/<int:sale_pk>/edit/", views.edit_purchase, name="edit_purchase"),
    path("customers/<int:pk>/purchase/<int:sale_pk>/delete/", views.delete_purchase, name="delete_purchase"),
    path("customers/<int:pk>/gift/", views.add_gift, name="add_gift"),
    path("customers/<int:pk>/occasion/", views.add_occasion, name="add_occasion"),
    path("customers/<int:pk>/person/", views.add_person, name="add_person"),
    path("customers/<int:pk>/outreach/", views.add_outreach, name="add_outreach"),
    path("gifts/<int:pk>/delete/", views.delete_gift, name="delete_gift"),
    path("occasions/<int:pk>/delete/", views.delete_occasion, name="delete_occasion"),
    path("people/<int:pk>/delete/", views.delete_person, name="delete_person"),
    path("outreach/<int:pk>/delete/", views.delete_outreach, name="delete_outreach"),
    # ── pipeline: four modules, one set of write endpoints ───────────────
    path("enquiries/", views.enquiry_list, name="enquiry_list"),
    path("enquiries/<int:pk>/", views.enquiry_detail, name="enquiry_detail"),
    path("enquiries/<int:pk>/convert/", views.enquiry_convert, name="enquiry_convert"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("repairs/", views.repair_list, name="repair_list"),
    path("repairs/<int:pk>/", views.repair_detail, name="repair_detail"),
    path("materials/", views.client_material_list, name="client_material_list"),
    path("materials/<int:pk>/", views.client_material_detail, name="client_material_detail"),
    path("materials/<int:pk>/to/<str:target>/", views.material_convert, name="material_convert"),
    path("<str:kind>/new/", views.pipeline_form, name="pipeline_new"),
    path("<str:kind>/<int:pk>/edit/", views.pipeline_form, name="pipeline_edit"),
    path("<str:kind>/<int:pk>/status/", views.pipeline_status, name="pipeline_status"),
    path("<str:kind>/<int:pk>/delete/", views.pipeline_delete, name="pipeline_delete"),
    # ── network and tools ────────────────────────────────────────────────
    path("fon/", views.fon_register_view, name="fon"),
    path("fon/<int:pk>/", views.fon_detail, name="fon_detail"),
    path("reports/", views.reports, name="reports"),
    path("calculator/", views.calculator, name="calculator"),
    path("calculator/attach/", views.quote_attach, name="quote_attach"),
]
