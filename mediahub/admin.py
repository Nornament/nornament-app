from django.contrib import admin

from .models import MediaAsset


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ("media_ref", "kind", "piece", "style", "scope", "scope_id", "file_name", "uploaded_at", "confirmed_at")
    list_filter = ("kind", "storage_provider", "is_archived", "scope")
    search_fields = ("media_ref", "storage_key", "file_name", "sha256")
    readonly_fields = ("sha256", "bytes", "uploaded_at", "confirmed_at")
