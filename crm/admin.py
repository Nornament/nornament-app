from django.contrib import admin

from . import models


@admin.register(models.Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("customer_code", "name", "mobile", "location", "customer_type", "is_fon", "fon_level")
    list_filter = ("is_fon", "fon_level", "customer_type", "temperature")
    search_fields = ("customer_code", "name", "mobile", "email")


@admin.register(models.Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ("enquiry_code", "customer", "enquiry_date", "status", "temperature", "follow_up_date")
    list_filter = ("status", "temperature")
    search_fields = ("enquiry_code", "item_of_interest", "customer__name")


@admin.register(models.Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_code", "customer", "order_date", "status", "total_amount", "advance_paid")
    list_filter = ("status",)
    search_fields = ("order_code", "item_description", "customer__name")


@admin.register(models.Repair)
class RepairAdmin(admin.ModelAdmin):
    list_display = ("repair_code", "customer", "received_date", "status", "estimated_cost", "final_cost")
    list_filter = ("status",)
    search_fields = ("repair_code", "customer__name")


@admin.register(models.ClientMaterial)
class ClientMaterialAdmin(admin.ModelAdmin):
    list_display = ("cm_code", "customer", "received_date", "status", "metal_type", "weight_grams")
    list_filter = ("status",)


@admin.register(models.EtlException)
class EtlExceptionAdmin(admin.ModelAdmin):
    list_display = ("run_at", "entity", "legacy_id", "problem")
    list_filter = ("entity", "problem")


admin.site.register(models.Salesperson)
admin.site.register(models.CrmSetting)
