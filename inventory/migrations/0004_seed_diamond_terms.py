from django.db import migrations


def load(apps, schema_editor):
    from inventory import dia_seed

    dia_seed.load(apps.get_model("inventory", "DiamondTerm"))


class Migration(migrations.Migration):
    dependencies = [("inventory", "0003_diamonds")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
