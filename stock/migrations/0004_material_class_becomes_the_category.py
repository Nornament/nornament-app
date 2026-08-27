"""``mat_class`` was a second copy of the category and is dropped.

In the loaded data the two agreed on every row bar the naming of one
(``COLOUR_STONE``/``SETTING``), and nothing prices off that distinction — the
engine only ever asked "is this metal", "is this making" and "is this bought
by carat", which the category answers. The metal-requires-a-metal CHECK is
re-expressed against the category so the database still refuses the row.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0003_alter_activitylog_changed_at_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='material',
            name='material_metal_required',
        ),
        migrations.RemoveField(
            model_name='material',
            name='mat_class',
        ),
        migrations.AddConstraint(
            model_name='material',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('category', 'METAL'), _negated=True), ('metal__isnull', False), _connector='OR'), name='material_metal_required'),
        ),
    ]
