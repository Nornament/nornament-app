"""Part 5b: the two price lists and setting one price for a whole group."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from inventory import services
from inventory.models import Pouch, PriceEntry
from stock.models import ActivityLog
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


def _group():
    return list(Pouch.objects.order_by("pk"))


def test_a_group_set_writes_one_dated_row_per_pouch_and_one_log(accounts_user, shelf):
    before = PriceEntry.objects.count()
    logs = ActivityLog.objects.count()
    when = timezone.localdate() - timedelta(days=1)
    n = services.set_group_price(accounts_user, _group(), PriceEntry.LIST, Decimal("1250"), when, described="stone=onyx")
    assert n == 2
    made = PriceEntry.objects.filter(kind=PriceEntry.LIST)
    assert PriceEntry.objects.count() == before + 2 and made.count() == 2
    assert {e.pouch_id for e in made} == {shelf["onyx"].pk, shelf["ruby"].pk}
    assert all(e.rate == Decimal("1250") and e.effective_from == when and e.set_by == accounts_user for e in made)
    assert ActivityLog.objects.count() == logs + 1
    assert ActivityLog.objects.latest("pk").detail == "list 1250/ct on 2 pouches (stone=onyx)"
    assert services.latest_price(shelf["onyx"], PriceEntry.LIST).rate == Decimal("1250")


def test_a_valuation_set_becomes_the_rate_on_file_and_nothing_is_overwritten(accounts_user, shelf):
    services.set_group_price(accounts_user, [shelf["onyx"]], PriceEntry.VALUATION, Decimal("8000"), timezone.localdate())
    onyx = services.stocked(Pouch.objects.filter(pk=shelf["onyx"].pk)).get()
    assert onyx.rate == Decimal("8000")
    assert shelf["onyx"].prices.filter(kind=PriceEntry.VALUATION).count() == 2      # the opening 7,919 is kept


@pytest.mark.parametrize("rate", [None, Decimal("0"), Decimal("-5"), Decimal("1e10"), Decimal("NaN"), Decimal("Infinity")])
def test_a_bad_rate_writes_nothing(accounts_user, shelf, rate):
    before = PriceEntry.objects.count()
    with pytest.raises(ServiceError):
        services.set_group_price(accounts_user, _group(), PriceEntry.LIST, rate, timezone.localdate())
    assert PriceEntry.objects.count() == before


def test_a_future_date_an_empty_group_and_a_purchase_kind_are_refused(accounts_user, shelf):
    before = PriceEntry.objects.count()
    tomorrow = timezone.localdate() + timedelta(days=1)
    with pytest.raises(ServiceError, match="future"):
        services.set_group_price(accounts_user, _group(), PriceEntry.LIST, Decimal("10"), tomorrow)
    with pytest.raises(ServiceError, match="No pouch matches these filters."):
        services.set_group_price(accounts_user, [], PriceEntry.LIST, Decimal("10"), timezone.localdate())
    with pytest.raises(ServiceError, match="purchase"):
        services.set_group_price(accounts_user, _group(), PriceEntry.PURCHASE, Decimal("10"), timezone.localdate())
    assert PriceEntry.objects.count() == before


def test_each_kind_needs_inv_masters_and_its_own_right(sales_user, production_user, shelf):
    before = PriceEntry.objects.count()
    today = timezone.localdate()
    with pytest.raises(PermissionDenied):          # Sales sees list prices but does not edit records
        services.set_group_price(sales_user, _group(), PriceEntry.LIST, Decimal("10"), today)
    with pytest.raises(PermissionDenied):
        services.set_group_price(production_user, _group(), PriceEntry.VALUATION, Decimal("10"), today)
    assert PriceEntry.objects.count() == before
