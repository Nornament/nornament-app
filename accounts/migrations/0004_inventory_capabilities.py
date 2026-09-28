"""Four inventory capabilities, and the Karigar desk group that holds one of them."""
from django.db import migrations


def sync_groups(apps, schema_editor):
    from accounts.models import sync_role_groups

    sync_role_groups()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_role_groups'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='capability',
            options={'default_permissions': (), 'managed': False, 'permissions': [('view_sale', 'Can see sale prices'), ('view_cost', 'Can see cost prices'), ('view_vendor', 'Can see vendors'), ('manage_materials', 'Can see the material breakup'), ('view_margin', 'Can see margins'), ('adjust_stock', 'Can adjust stock'), ('melt', 'Can melt a piece'), ('edit_bom', 'Can edit a bill of materials'), ('inv_masters', 'Can edit inventory records and import stock'), ('inv_purchase', 'Can post inventory purchases'), ('inv_job', 'Can post job-card movements'), ('inv_assort', 'Can post assortments')]},
        ),
        migrations.RunPython(sync_groups, migrations.RunPython.noop),
    ]
