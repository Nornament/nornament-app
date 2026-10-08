"""Put back the reference rows a stock wipe used to take with it.

Until the wipe stopped touching them, choosing "Reference data" deleted every
metal, purity and material category — rows no screen can recreate — and left
every IVY import blocked on "Purity '18K' is not in the purity table". This
restores 0002's seed wherever it is missing.

Create-only: a row that exists keeps the values it has, because the ETL loads
the legacy purity factors over the seed and those must not be reset. Locations
and categories have screens of their own, so they are only seeded
into an empty table, as a fresh database would be.
"""
from importlib import import_module

from django.db import migrations

seed = import_module("stock.migrations.0002_reference_seed")


def restore(apps, schema_editor):
    Metal = apps.get_model("stock", "Metal")
    MetalPurity = apps.get_model("stock", "MetalPurity")
    MaterialCategory = apps.get_model("stock", "MaterialCategory")
    Location = apps.get_model("stock", "Location")
    Category = apps.get_model("stock", "Category")

    for code, name, rate, note in seed.METALS:
        Metal.objects.get_or_create(code=code, defaults={"name": name, "pure_rate": rate, "note": note})
    for karat, sale, fineness, metal, order in seed.PURITIES:
        MetalPurity.objects.get_or_create(
            karat=karat,
            defaults={"sale_factor": sale, "true_fineness": fineness, "metal_id": metal, "sort_order": order},
        )
    for code, name, order, priceable, note in seed.MATERIAL_CATEGORIES:
        MaterialCategory.objects.get_or_create(
            code=code, defaults={"name": name, "sort_order": order, "is_priceable": priceable, "note": note}
        )
    if not Location.objects.exists():
        for code, name, kind, city in seed.LOCATIONS:
            Location.objects.create(code=code, name=name, kind=kind, city=city)
    if not Category.objects.exists():
        for code, name, prefix, order in seed.CATEGORIES:
            Category.objects.create(code=code, name=name, code_prefix=prefix, sort_order=order)


class Migration(migrations.Migration):
    dependencies = [("stock", "0010_vendor_terms")]

    operations = [migrations.RunPython(restore, migrations.RunPython.noop)]
