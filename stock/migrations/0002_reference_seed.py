"""Reference rows the application cannot run without.

These are the seeds of migrations 0001a, 0004, 0032b, 0034 and 0036. The ETL
overwrites them with whatever the legacy database holds; this is what a fresh
database starts from so that a first run is not an empty screen.
"""
from decimal import Decimal

from django.db import migrations

UOM_CONVERSIONS = [("GM", "1.0"), ("CT", "0.2"), ("RATTI", "0.1215"), ("PCS", "0.0")]

METALS = [
    ("GOLD", "Gold", "15481", "Pure 24K per gram, incl. GST"),
    ("SILVER", "Silver", "260", "Pure 999 per gram, incl. GST"),
]

# 925 sells at the 999 rate (factor 1.0) and costs at its true 0.925 — a 7.5
# point spread, deliberate, and the correction migration 0032b exists to make.
PURITIES = [
    ("24K", "1.0000", "1.0000", "GOLD", 1),
    ("22K", "0.9250", "0.9167", "GOLD", 2),
    ("18K", "0.7600", "0.7500", "GOLD", 3),
    ("14K", "0.5900", "0.5833", "GOLD", 4),
    ("999", "1.0000", "1.0000", "SILVER", 1),
    ("925", "1.0000", "0.9250", "SILVER", 2),
]

MATERIAL_CATEGORIES = [
    ("METAL", "Metal", 1, True, "Priced from its metal's live rate, never marked up"),
    ("DIAMOND", "Diamond", 2, True, "Cut and polished"),
    ("POLKI", "Diamond Polki", 3, True, "Uncut, foil-backed"),
    ("SETTING", "Setting Stones", 4, True, "Coloured stones and pearls that are set"),
    ("PURAI", "Purai Stones", 5, True, "Kept separate from setting stones on purpose"),
    ("OTHER", "Other Materials", 6, True, "Findings, and anything not yet classified"),
    ("LABOUR", "Making", 7, False, "Not a material — the charge for making the piece"),
]

SETTINGS = [
    ("line_rounding_dp", "0", "Decimals each material line rounds to before summing. 0 = whole rupees, matches the legacy Excel job card."),
    ("total_rounding_dp", "0", "Decimals the jewel code total rounds to."),
    ("gross_wt_tolerance_gm", "0.050", "Allowed gap between the BOM-derived weight and the measured gross weight before the reconciliation report flags it."),
    ("making_rate_default", "1500", "Making charge per gram of metal, unless a line says otherwise."),
    ("making_basis_default", "BY_NET_METAL_WT", "How a making line is charged by default."),
]

LOCATIONS = [
    ("HO", "Head Office", "GODOWN", "Jaipur"),
    ("MUM", "Mumbai", "SHOWROOM", "Mumbai"),
    ("KOL", "Kolkata", "SHOWROOM", "Kolkata"),
    ("WS1", "Workshop", "WORKSHOP", "Jaipur"),
]

CATEGORIES = [
    ("EARR", "Earrings", "ER", 10),
    ("NECK", "Necklaces", "NK", 20),
    ("RING", "Rings", "RG", 30),
    ("BANG", "Bangles / Bracelets", "BG", 40),
    ("BROO", "Brooch", "BC", 50),
    ("MANG", "Mangalsutras / Chains", "MG", 60),
    ("PEND", "Pendant Sets", "PS", 70),
]


def seed(apps, schema_editor):
    UomConversion = apps.get_model("stock", "UomConversion")
    Metal = apps.get_model("stock", "Metal")
    MetalPurity = apps.get_model("stock", "MetalPurity")
    MaterialCategory = apps.get_model("stock", "MaterialCategory")
    SystemSetting = apps.get_model("stock", "SystemSetting")
    Location = apps.get_model("stock", "Location")
    Category = apps.get_model("stock", "Category")
    Scenario = apps.get_model("stock", "Scenario")

    for unit, grams in UOM_CONVERSIONS:
        UomConversion.objects.update_or_create(unit=unit, defaults={"grams_per_unit": Decimal(grams)})
    for code, name, rate, note in METALS:
        Metal.objects.get_or_create(code=code, defaults={"name": name, "pure_rate": Decimal(rate), "note": note})
    for karat, sale, fineness, metal, order in PURITIES:
        MetalPurity.objects.update_or_create(
            karat=karat,
            defaults={
                "sale_factor": Decimal(sale),
                "true_fineness": Decimal(fineness),
                "metal_id": metal,
                "sort_order": order,
            },
        )
    for code, name, order, priceable, note in MATERIAL_CATEGORIES:
        MaterialCategory.objects.update_or_create(
            code=code, defaults={"name": name, "sort_order": order, "is_priceable": priceable, "note": note}
        )
    for key, value, description in SETTINGS:
        SystemSetting.objects.get_or_create(key=key, defaults={"value": value, "description": description})
    for code, name, kind, city in LOCATIONS:
        Location.objects.get_or_create(code=code, defaults={"name": name, "kind": kind, "city": city})
    for code, name, prefix, order in CATEGORIES:
        Category.objects.get_or_create(code=code, defaults={"name": name, "code_prefix": prefix, "sort_order": order})

    if not Scenario.objects.exists():
        Scenario.objects.create(
            code="RETAIL",
            name="Retail",
            method="CHART",
            is_default=True,
            spread_over=["DIAMOND", "POLKI", "SETTING", "PURAI"],
            note="Sale rates exactly as the chart holds them",
        )
        Scenario.objects.create(
            code="VA100",
            name="Value added +100%",
            method="VALUE_ADDED",
            target_pct=Decimal("100"),
            spread_over=["DIAMOND", "POLKI", "SETTING", "PURAI"],
            note="Stones and making together must double their cost. Metal passes through.",
        )


def unseed(apps, schema_editor):
    """Deliberately a no-op: reference data is not something a rollback deletes."""


class Migration(migrations.Migration):
    dependencies = [("stock", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
