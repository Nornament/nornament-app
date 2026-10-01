"""A small shelf every inventory test can stand on.

Numbers are chosen to be findable in a response body and nowhere else: a
SALES login must never be shown 7,919 or 98,988, and a client must never be
shown SL01G, C-117 or the remark.
"""
from decimal import Decimal

import pytest

from inventory import seed, services
from inventory.models import Batch, BoxColour, CodePart

RATE = Decimal("7919")
VALUE = "98,988"          # 12.5 ct × ₹7,919, rounded
SUPPLIER = "Bhansali Gems"


@pytest.fixture
def shelf(admin_user_):
    from stock.models import Vendor

    seed.load(BoxColour, CodePart)
    supplier = Vendor.objects.create(code="BHG", name=SUPPLIER)
    batch = Batch.objects.create(code="SL01G", box_colour_id="G", family="S", cls="L", seq="01")
    onyx = services.open_pouch(
        admin_user_, batch,
        {"pouch_no": "1", "carton": "C-117", "category": "Man Made", "stone_name": "Green Onyx",
         "colour": "Green", "shape": "Oval", "cut": "Cabachon", "quality": "B", "size_text": "14*10",
         "remarks": "keep away from light", "src": "SL!2"},
        pcs=20, ct=Decimal("12.5"), rate=RATE,
    )
    onyx.supplier = supplier
    onyx.save(update_fields=["supplier"])
    ruby = services.open_pouch(
        admin_user_, batch,
        {"pouch_no": "2", "carton": "C-117", "category": "Man Made", "stone_name": "Ruby Glass",
         "colour": "Red", "shape": "Beads Round", "cut": "Regular", "quality": "A", "size_text": "Free Far",
         "src": "SL!3"},
        pcs=None, ct=Decimal("40"), rate=Decimal("50"),
    )
    return {"batch": batch, "onyx": onyx, "ruby": ruby, "supplier": supplier}


#: the round line: 3.40 ct × ₹16,517 cost = ₹56,157.80, × ₹21,013 sale = ₹71,444.20
DIA_COST, DIA_COST_VALUE = "16,517", "56,158"
DIA_SALE, DIA_SALE_VALUE = "21,013", "71,444"
DIA_SUPPLIER = "Kothari Exports"


@pytest.fixture
def diamonds(admin_user_):
    from datetime import date

    from inventory import dia_seed, dia_services
    from inventory.models import DiamondCode, DiamondTerm
    from stock.models import Vendor

    dia_seed.load(DiamondTerm)
    t = dia_services.term
    round_code = DiamondCode.objects.create(
        item_code="DRFGH VS-SI", shape=t("shape", "Round"), colour=t("colour", "F-G-H"),
        clarity=t("clarity", "VS-SI"), confirmed=True)
    princess = DiamondCode.objects.create(
        item_code="DPCEF VVS-VS", shape=t("shape", "Princess"), colour=t("colour", "E-F"),
        clarity=t("clarity", "VVS-VS"), confirmed=True)
    polki = DiamondCode.objects.create(item_code="FPL", shape=t("shape", "Polki"), note="FPL — is the L part of the product name?")
    natural, foil = t("category", "Natural Diamond"), t("category", "Foil Polki")
    lines = dia_services.open_lines(admin_user_, [
        {"category": natural, "code": round_code, "batch_no": "B-771", "size_text": "+6-12",
         "band": t("band", "+6-11"), "src": "Sheet!3", "ct": Decimal("3.40")},
        {"category": natural, "code": princess, "batch_no": "B-771", "size_text": "+2",
         "band": t("band", "+2-6"), "src": "Sheet!5", "ct": Decimal("0.85")},
        {"category": foil, "code": polki, "batch_no": "BW-1", "size_text": "20+",
         "band": t("band", "20+"), "src": "Sheet!7", "ct": Decimal("43.21")},
    ])
    dia_services.set_rate(admin_user_, round_code, "+6-12", Decimal("16517"), Decimal("21013"), date(2026, 9, 1))
    supplier = Vendor.objects.create(code="KOT", name=DIA_SUPPLIER, city="Mumbai", terms="Advance")
    return {"round": lines[0], "princess": lines[1], "polki": lines[2], "supplier": supplier}
