"""The five roles of ``app.role``, as groups carrying the capabilities."""
from django.db import migrations


def create_groups(apps, schema_editor):
    from accounts.models import sync_role_groups

    sync_role_groups()


def drop_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=["ADMIN", "ACCOUNTS", "SALES", "GRAPHIC", "PRODUCTION"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(create_groups, drop_groups)]
