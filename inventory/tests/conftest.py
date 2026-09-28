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
