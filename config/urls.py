from django.contrib import admin
from django.urls import include, path

from inventory import views_lookbooks
from .views import healthz

urlpatterns = [
    path("lookbook/<str:token>/", views_lookbooks.lookbook_public, name="lookbook_public"),
    path("lookbook/<str:token>/photo/<int:media_id>/", views_lookbooks.lookbook_photo, name="lookbook_photo"),
    path("", include("stock.urls")),
    path("crm/", include("crm.urls")),
    path("inventory/", include("inventory.urls")),
    path("media/", include("mediahub.urls")),
    path("accounts/", include("accounts.urls")),
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
]

admin.site.site_header = "Nornament administration"
admin.site.site_title = "Nornament"
admin.site.index_title = "Reference data and users"
