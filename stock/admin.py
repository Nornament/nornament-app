"""Reference data and back-office CRUD.

Ledger-touching models are registered read-only on purpose: a movement, a sale,
a melt and a scan may only be created by a service, where the rules live. This
is what replaces the v1 plan's whole ``/admin/*`` sidecar surface.
"""
from django.contrib import admin

from . import models


class ReadOnlyAdmin(admin.ModelAdmin):
    """Visible, searchable, and impossible to write. Services own these tables."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "city", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("code", "name", "city")


@admin.register(models.Metal)
class MetalAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "pure_rate", "rate_as_on", "is_active")
    readonly_fields = ("rate_as_on",)


@admin.register(models.MetalPurity)
class MetalPurityAdmin(admin.ModelAdmin):
    list_display = ("karat", "metal", "sale_factor", "true_fineness", "sort_order")
    list_filter = ("metal",)


@admin.register(models.MaterialCategory)
class MaterialCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "sort_order", "is_priceable")


@admin.register(models.Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("item_code", "item_name", "category", "mat_class", "default_uom", "metal", "needs_review")
    list_filter = ("category", "mat_class", "needs_review", "is_active")
    search_fields = ("item_code", "item_name", "description")


@admin.register(models.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "code_prefix", "sort_order")


@admin.register(models.Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_bestseller", "launched_on")


@admin.register(models.Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "city", "avg_tat_days", "is_active")
    search_fields = ("code", "name")


@admin.register(models.Style)
class StyleAdmin(admin.ModelAdmin):
    list_display = ("style_code", "name", "category", "collection", "state", "nos_min_qty", "is_active")
    list_filter = ("state", "category", "is_active")
    search_fields = ("style_code", "name")


class RateChartLineInline(admin.TabularInline):
    model = models.RateChartLine
    extra = 0
    autocomplete_fields = ("material",)


@admin.register(models.RateChart)
class RateChartAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "version_no", "is_default", "is_locked", "created_at")
    inlines = [RateChartLineInline]


@admin.register(models.Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "method", "target_pct", "is_default", "is_active")


@admin.register(models.SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "description")
    search_fields = ("key",)


@admin.register(models.Piece)
class PieceAdmin(admin.ModelAdmin):
    list_display = ("jewel_code", "style", "metal_purity", "stock_state", "location", "received_on")
    list_filter = ("stock_state", "location", "metal_purity")
    search_fields = ("jewel_code", "huid", "src_ref")
    autocomplete_fields = ("style", "vendor")
    readonly_fields = ("stock_state", "location", "current_bom_version", "received_on", "disposed_on")


@admin.register(models.StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ("movement_id", "piece", "move_type", "from_location", "to_location", "resulting_state", "moved_at")
    list_filter = ("move_type", "resulting_state")
    search_fields = ("piece__jewel_code", "reference_no")


@admin.register(models.Sale)
class SaleAdmin(ReadOnlyAdmin):
    list_display = ("sale_id", "sold_on", "piece", "customer_name", "sold_price", "source")
    list_filter = ("source", "sold_on", "location")
    search_fields = ("piece__jewel_code", "customer_name", "invoice_no")


@admin.register(models.MeltRecord)
class MeltRecordAdmin(ReadOnlyAdmin):
    list_display = ("melt_id", "piece", "melted_on", "cost_written_off", "authorised_by")


@admin.register(models.StockCount)
class StockCountAdmin(ReadOnlyAdmin):
    list_display = ("count_ref", "location", "status", "started_at", "closed_at", "counted_by")
    list_filter = ("status", "location")


@admin.register(models.RepairJob)
class RepairJobAdmin(admin.ModelAdmin):
    list_display = ("job_no", "piece", "status", "opened_on", "closed_on", "vendor")
    list_filter = ("status",)
    search_fields = ("job_no", "piece__jewel_code")


@admin.register(models.ActivityLog)
class ActivityLogAdmin(ReadOnlyAdmin):
    list_display = ("changed_at", "action", "table_name", "record_pk", "user", "detail")
    list_filter = ("action", "table_name")
    search_fields = ("record_pk", "detail")


admin.site.register(models.BomVersion, ReadOnlyAdmin)
admin.site.register(models.BomLine, ReadOnlyAdmin)
admin.site.register(models.CatalogueTemplate)
admin.site.register(models.JobCard)
