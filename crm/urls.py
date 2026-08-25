from django.urls import path

from . import views

app_name = "crm"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/rows/", views.customer_rows, name="customer_rows"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/purchase/", views.add_purchase, name="add_purchase"),
    path("enquiries/", views.enquiry_list, name="enquiry_list"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<int:pk>/status/", views.order_status, name="order_status"),
    path("repairs/", views.repair_list, name="repair_list"),
    path("materials/", views.client_material_list, name="client_material_list"),
    path("fon/", views.fon_register_view, name="fon"),
    path("fon/<int:pk>/", views.fon_detail, name="fon_detail"),
    path("reports/", views.reports, name="reports"),
    path("calculator/", views.calculator, name="calculator"),
]
