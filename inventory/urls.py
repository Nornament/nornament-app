from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.shelf, name="shelf"),
    path("view/", views.set_view, name="set_view"),
    path("colours/<str:code>/", views.colour, name="colour"),
    path("batches/<int:pk>/", views.batch, name="batch"),
    path("pouches/<str:ref>/", views.shelf, name="pouch"),             # replaced in Task 8
    path("import/", views.shelf, name="import_home"),                  # replaced in Task 9
]
