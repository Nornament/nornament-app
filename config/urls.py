from django.contrib import admin
from django.urls import include, path

from .views import healthz

urlpatterns = [
    path("", include("stock.urls")),
    path("crm/", include("crm.urls")),
    path("media/", include("mediahub.urls")),
    path("accounts/", include("accounts.urls")),
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
]

admin.site.site_header = "Nornament administration"
admin.site.site_title = "Nornament"
admin.site.index_title = "Reference data and users"
