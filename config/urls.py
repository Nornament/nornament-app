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

# The Django admin is for superusers only. Django's default lets in any
# is_staff login, and load_legacy marks imported admins as staff; everyone else
# manages what their role allows from the app's own screens (users included,
# under Users & Settings).
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser

admin.site.site_header = "Nornament administration"
admin.site.site_title = "Nornament"
admin.site.index_title = "Reference data and users"
