from django.db import migrations


def load(apps, schema_editor):
    from inventory import seed

    seed.load(apps.get_model("inventory", "BoxColour"), apps.get_model("inventory", "CodePart"))


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
