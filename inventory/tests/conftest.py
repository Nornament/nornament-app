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


KARIGAR = "Mahesh Karigar"
CUSTOMER = "Kalyan Retail"


@pytest.fixture
def parties(db):
    """A karigar (a supplier-list entry, as part 1 keeps them) and a CRM customer."""
    from crm.models import Customer
    from stock.models import Vendor

    return {
        "karigar": Vendor.objects.create(code="MAH", name=KARIGAR, city="Johari Bazar"),
        "customer": Customer.objects.create(customer_code="C-881", name=CUSTOMER),
    }


#: the purchase's cost per carat, findable in a body and nowhere else
PURCHASE_COST = "4,321"


@pytest.fixture
def ledger_docs(admin_user_, shelf, parties):
    """A job work (karigar), a memo (customer) and a purchase (supplier, cost) on the shelf."""
    from datetime import date

    from inventory import ledger_jobs
    from inventory.ledger_purchase import PurchaseHeader, PurchaseLine, post_purchase

    job = ledger_jobs.job_work_out(admin_user_, shelf["onyx"], parties["karigar"], "2026/0431", 2, Decimal("1"))
    memo = ledger_jobs.memo_out(admin_user_, shelf["ruby"], parties["customer"], "MEMO-0088", None, Decimal("5"))
    purchase = post_purchase(
        admin_user_, PurchaseHeader(supplier=shelf["supplier"], occurred_on=date(2026, 8, 7), invoice_no="2026/0442"),
        [PurchaseLine(batch=shelf["batch"], pouch_no="3", stone_name="Tanzanite", shape="Oval", colour="Blue",
                      pcs=6, ct=Decimal("3"), cost_per_ct=Decimal("4321"))],
    )
    return {**shelf, **parties, "job": job, "memo": memo, "purchase": purchase,
            "bought": purchase.movements.get().pouch}


#: a diamond purchase's cost per carat and an assortment's override, findable in a body and nowhere else
DIA_LINE_COST = "23,456"
DIA_OVERRIDE = "18,888"


@pytest.fixture
def dia_docs(admin_user_, diamonds, parties):
    """A job card (karigar), an assortment with a cost override, and a purchase (supplier, cost)."""
    from datetime import date

    from inventory import ledger_dia_assort, ledger_dia_jobs, ledger_dia_purchase
    from inventory.ledger_purchase import PurchaseHeader

    card = ledger_dia_jobs.open_card(admin_user_, parties["karigar"])
    ledger_dia_jobs.post_entry(admin_user_, card, "issue", diamonds["round"], Decimal("1"), ref="CH 2026/0417")
    assort = ledger_dia_assort.post_assortment(
        admin_user_, diamonds["polki"], Decimal("3"),
        [ledger_dia_assort.Destination("Round", "G", "VS1", "+2", Decimal("3"), Decimal("18888"))],
    )
    purchase = ledger_dia_purchase.post_dia_purchase(
        admin_user_, PurchaseHeader(supplier=diamonds["supplier"], occurred_on=date(2026, 8, 7), invoice_no="DIA-7731"),
        [ledger_dia_purchase.DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "+6-12", None,
                                             Decimal("2"), Decimal("23456"))],
    )
    return {**diamonds, **parties, "card": card, "assort": assort, "purchase": purchase}


@pytest.fixture
def finder_docs(admin_user_, ledger_docs, dia_docs):
    """Every stones and diamond document the ledger fixtures make, plus a split of the onyx and a
    transfer of the ruby. The two fixtures share keys (``purchase``, ``supplier``), so each keeps
    its own dict."""
    from inventory.ledger_assort import SplitPart, split_pouch, transfer_pouch
    from inventory.models import Batch

    split = split_pouch(admin_user_, ledger_docs["onyx"], 2, Decimal("1"), [SplitPart("7", 2, Decimal("1"))])
    to = Batch.objects.create(code="SL02G", box_colour_id="G", family="S", cls="L", seq="02")
    transfer = transfer_pouch(admin_user_, ledger_docs["ruby"], to, "5")
    return {"stones": ledger_docs, "dia": dia_docs, "split": split, "transfer": transfer}
