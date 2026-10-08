"""Stones & Diamonds moved to nornament-rm (2026-10-09). Remove what it left here.

In order: its 16 tables first (they reference the import batches, so those
cannot go while the tables stand); then its import batches and photo rows
(bucket files are left — harmless and recoverable); the five inv_* rights;
Karigar desk logins (deactivated — the role was only for stones) and the
group; and what Django kept about the app: its migration rows and content types.

Irreversible: the tables are dropped with CASCADE. The only way back is restoring
the database backup taken just before this deploy.
"""
from django.db import migrations

INV_TABLES = [
    "inv_lookbook_stone", "inv_lookbook", "inv_stock_take_count", "inv_stock_take",
    "inv_dia_line_cost", "inv_dia_rate", "inv_dia_line", "inv_dia_code", "inv_dia_term",
    "inv_price", "inv_movement", "inv_document", "inv_pouch", "inv_batch",
    "inv_code_part", "inv_box_colour",
]
RIGHTS = ["inv_masters", "inv_purchase", "inv_job", "inv_assort", "inv_move"]


def forwards(apps, schema_editor):
    MediaAsset = apps.get_model("mediahub", "MediaAsset")
    ImportBatch = apps.get_model("stock", "ImportBatch")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("accounts", "User")

    # inv_* rows point at these, so the tables go first
    with schema_editor.connection.cursor() as cursor:
        for table in INV_TABLES:
            cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
        cursor.execute("DELETE FROM django_migrations WHERE app = 'inventory'")
    batches = ImportBatch.objects.filter(source__in=["STONES", "DIAMONDS"])
    workbooks = list(batches.values_list("media_id", flat=True))
    batches.delete()
    MediaAsset.objects.filter(pk__in=workbooks).delete()
    MediaAsset.objects.filter(scope="pouch").delete()

    Permission.objects.filter(content_type__app_label="accounts", codename__in=RIGHTS).delete()
    karigar = Group.objects.filter(name="KARIGAR").first()
    if karigar:
        for user in User.objects.filter(groups=karigar):
            if user.groups.count() == 1:
                user.is_active = False
                user.save(update_fields=["is_active"])
        karigar.delete()

    ContentType = apps.get_model("contenttypes", "ContentType")
    stale = ContentType.objects.filter(app_label="inventory")
    Permission.objects.filter(content_type__in=stale).delete()
    stale.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_inv_move"),
        ("mediahub", "0008_piece_photos_onto_their_piece"),
        ("stock", "0011_restore_reference"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(forwards, None),
        migrations.AlterModelOptions(
            name="capability",
            options={"default_permissions": (), "managed": False, "permissions": [
                ("view_sale", "Can see sale prices"), ("view_cost", "Can see cost prices"),
                ("view_vendor", "Can see vendors"), ("manage_materials", "Can see the material breakup"),
                ("view_margin", "Can see margins"), ("adjust_stock", "Can adjust stock"),
                ("melt", "Can melt a piece"), ("edit_bom", "Can edit a bill of materials"),
            ]},
        ),
    ]
