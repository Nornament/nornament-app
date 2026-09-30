from django.urls import path

from . import views, views_diamonds

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
    path("diamonds/settings/", views_diamonds.search, name="dia_settings"),            # replaced in Task 9
    path("diamonds/import/", views_diamonds.search, name="dia_import_home"),           # replaced in Task 10
]
