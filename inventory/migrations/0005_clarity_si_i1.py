from django.db import migrations


def add_si_i1(apps, schema_editor):
    """The owner's ruling (2026-09-30): "SI I1" covers SI1, SI2 and I1."""
    DiamondTerm = apps.get_model("inventory", "DiamondTerm")
    term, _ = DiamondTerm.objects.get_or_create(kind="clarity", value="SI-I1",
                                                defaults={"sort": 104, "expands_to": "SI1 SI2 I1"})
    if not term.expands_to:
        term.expands_to = "SI1 SI2 I1"
        term.save(update_fields=["expands_to"])


class Migration(migrations.Migration):
    dependencies = [("inventory", "0004_seed_diamond_terms")]

    operations = [migrations.RunPython(add_si_i1, migrations.RunPython.noop)]
