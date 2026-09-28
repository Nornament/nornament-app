from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.shelf, name="shelf"),
    path("view/", views.set_view, name="set_view"),
    path("colours/<str:code>/", views.shelf, name="colour"),          # replaced in Task 7
    path("import/", views.shelf, name="import_home"),                  # replaced in Task 9
]
