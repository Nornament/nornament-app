from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "full_name", "email", "home_location", "is_active", "must_change_password")
    list_filter = ("is_active", "must_change_password", "groups", "home_location")
    filter_horizontal = ("groups", "user_permissions", "locations")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Nornament",
            {
                "fields": (
                    "full_name",
                    "phone",
                    "must_change_password",
                    "home_location",
                    "locations",
                    "legacy_auth_uid",
                    "legacy_user_id",
                ),
                "description": "An empty home location means every location is visible.",
            },
        ),
    )
    readonly_fields = ("legacy_auth_uid", "legacy_user_id")
