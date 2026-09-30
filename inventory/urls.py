from django.urls import path

from . import views, views_dia_settings, views_diamonds

app_name = "inventory"

urlpatterns = [
    path("", views.shelf, name="shelf"),
    path("view/", views.set_view, name="set_view"),
    path("colours/<str:code>/", views.colour, name="colour"),
    path("batches/<int:pk>/", views.batch, name="batch"),
    path("import/", views.import_home, name="import_home"),
    path("import/<int:batch_id>/", views.import_review, name="import_review"),
    path("import/<int:batch_id>/commit/", views.import_commit, name="import_commit"),
    path("pouches/<str:ref>/", views.pouch, name="pouch"),
    path("pouches/<str:ref>/save/", views.pouch_save, name="pouch_save"),
    path("pouches/<str:ref>/price/", views.pouch_price, name="pouch_price"),
    path("pouches/<str:ref>/photos/", views.pouch_photos, name="pouch_photos"),
    path("pouches/<str:ref>/movements/", views.movements, name="movements"),
    path("photos/<int:media_id>/", views.photo, name="photo"),
    path("diamonds/", views_diamonds.search, name="diamonds"),
    path("diamonds/settings/", views_dia_settings.settings_page, name="dia_settings"),
    path("diamonds/settings/terms/", views_dia_settings.term_add, name="dia_term_add"),
    path("diamonds/settings/terms/<int:pk>/rename/", views_dia_settings.term_rename, name="dia_term_rename"),
    path("diamonds/settings/terms/<int:pk>/delete/", views_dia_settings.term_delete, name="dia_term_delete"),
    path("diamonds/settings/terms/<int:pk>/expansion/", views_dia_settings.expansion, name="dia_expansion"),
    path("diamonds/settings/codes/<str:code>/", views_dia_settings.code_save, name="dia_code_save"),
    path("diamonds/settings/rates/", views_dia_settings.rate_save, name="dia_rate_save"),
    path("diamonds/settings/rates/ivy/", views_dia_settings.rates_ivy, name="dia_rates_ivy"),
    path("diamonds/settings/suppliers/", views_dia_settings.supplier_save, name="dia_supplier_save"),
    path("diamonds/settings/rights/", views_dia_settings.right_toggle, name="dia_right_toggle"),
    path("diamonds/import/", views_diamonds.search, name="dia_import_home"),           # replaced in Task 10
]
