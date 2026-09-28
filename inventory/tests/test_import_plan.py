from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import seed, services
from inventory.importers import plan, stones
from inventory.models import BoxColour, CodePart, Movement, Pouch
from inventory.tests.fixtures_stones import build_workbook
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _codes():
    seed.load(BoxColour, CodePart)


def _items(decisions=None):
    return plan.analyse(stones.parse(build_workbook()), decisions)


def _by_src(items):
    return {item.row.src: item for item in items}


def test_the_review_finds_every_case():
    items = _by_src(_items())
    assert items["SL!4"].problem and "SL!2" in items["SL!4"].problem      # duplicate key
    assert items["SL!6"].problem                                          # batch code does not read
    assert items["SL!5"].problem is None and items["SL!5"].suggestion == "1"
    assert items["SL!2"].problem is None and items["SL!7"].problem is None
    assert plan.counts(list(items.values()))["blocked"] == 2


def test_a_blocked_import_cannot_commit(admin_user_):
    with pytest.raises(ServiceError):
        plan.commit(_items(), admin_user_)
    assert not Pouch.objects.exists()


def _decided():
    return {"SL!4": {"batch": "", "pouch_no": "9", "skip": False}, "SL!6": {"batch": "", "pouch_no": "", "skip": True}}


def test_commit_opens_every_decided_row(admin_user_):
    result = plan.commit(_items(_decided()), admin_user_)
    assert result == {"created": 5, "updated": 0, "recounted": 0, "skipped": 1}
    assert Pouch.objects.get(batch__code="SL01G", pouch_no="9").stone_name == "Green Onyx"
    assert Pouch.objects.get(src="SL!5").pouch_no is None                # left blank, as decided
    assert BoxColour.objects.get(code="F").confirmed is False            # seeded, unconfirmed
    pearl = services.stocked(Pouch.objects.filter(src="SL!7")).get()
    assert pearl.rate is None                                            # no rate: cannot be valued


def test_reimport_updates_and_recounts(admin_user_):
    plan.commit(_items(_decided()), admin_user_)
    from inventory.tests.fixtures_stones import SHEETS_DEFAULT, _row

    changed = {"SL": [_row("SL01G", 1, "Green Onyx", "Green", 18, 13, 100)]}
    items = plan.analyse(stones.parse(build_workbook(changed)))
    assert items[0].existing is not None and items[0].recount
    result = plan.commit(items, admin_user_)
    assert result["updated"] == 1 and result["recounted"] == 1
    onyx = services.stocked(Pouch.objects.filter(batch__code="SL01G", pouch_no="1")).get()
    assert (onyx.on_pcs, onyx.on_ct) == (18, Decimal("13"))
    assert onyx.movements.filter(reason=Movement.Reason.RECOUNT_ADJUSTMENT).count() == 2


def test_fill_suggested_numbers_only_blank_ones():
    items = _items()
    post = {f"pouch_no:{i.row.src}": "" for i in plan.attention(items)}
    post |= {f"batch:{i.row.src}": "" for i in plan.attention(items)}
    post["fill_suggested"] = "1"
    decisions = plan.read_decisions(post, items, {})
    assert decisions["SL!5"]["pouch_no"] == "1"


def test_sales_cannot_import(sales_user):
    with pytest.raises(PermissionDenied):
        plan.commit(_items(_decided()), sales_user)
