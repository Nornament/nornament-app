from django.urls import path

from . import views

app_name = "mediahub"

urlpatterns = [
    path("presign/", views.presign, name="presign"),
    path("confirm/", views.confirm, name="confirm"),
    path("upload/", views.proxy_upload, name="proxy_upload"),
    path("<int:media_id>/", views.media_redirect, name="media"),
    path("<int:media_id>/delete/", views.detach, name="detach"),
]
