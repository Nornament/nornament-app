from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import services
from inventory.models import Movement, Pouch, PriceEntry
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def test_opening_writes_a_balance_a_rate_and_a_reference(shelf):
    onyx = _held(shelf["onyx"])
    assert onyx.ref == "NRN-000001" and shelf["ruby"].ref == "NRN-000002"
    assert (onyx.on_pcs, onyx.on_ct, onyx.rate) == (20, Decimal("12.5"), Decimal("7919"))
    assert services.value_of(onyx) == Decimal("98987.5")
    assert onyx.movements.get().reason == Movement.Reason.OPENING_BALANCE


def test_an_uncountable_pouch_moves_by_weight_only(shelf):
    ruby = _held(shelf["ruby"])
    assert ruby.countable is False and ruby.on_pcs is None and ruby.on_ct == Decimal("40")


def test_quantity_is_the_sum_of_movements(shelf, admin_user_):
    onyx = shelf["onyx"]
    Movement.objects.create(pouch=onyx, reason=Movement.Reason.SALE, direction=Movement.OUT, pcs=5, ct=Decimal("2.5"))
    held = _held(onyx)
    assert (held.on_pcs, held.on_ct) == (15, Decimal("10"))


def test_no_weight_means_no_value(admin_user_, shelf):
    pouch = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "3"}, pcs=1, ct=None, rate=Decimal("10"))
    assert services.value_of(_held(pouch)) is None


def test_the_latest_valuation_is_the_rate(shelf, admin_user_):
    services.add_price(admin_user_, shelf["onyx"], PriceEntry.VALUATION, Decimal("8000"), date.today())
    assert _held(shelf["onyx"]).rate == Decimal("8000")
    assert shelf["onyx"].prices.count() == 2            # the old rate is kept


def test_a_future_dated_price_is_refused(shelf, admin_user_):
    with pytest.raises(ServiceError, match="cannot take effect in the future"):
        services.add_price(admin_user_, shelf["onyx"], PriceEntry.VALUATION, Decimal("8000"),
                           date.today() + timedelta(days=1))


def test_sales_may_neither_save_nor_price(shelf, sales_user):
    with pytest.raises(PermissionDenied):
        services.save_details(sales_user, shelf["onyx"], treatment="Heated")
    with pytest.raises(PermissionDenied):
        services.add_price(sales_user, shelf["onyx"], PriceEntry.LIST, Decimal("1"), date.today())


def test_a_negative_rate_is_refused_and_zero_is_not(shelf, admin_user_):
    with pytest.raises(ServiceError):
        services.add_price(admin_user_, shelf["onyx"], PriceEntry.VALUATION, Decimal("-1"), date.today())
    services.add_price(admin_user_, shelf["onyx"], PriceEntry.LIST, Decimal("0"), date.today())


def test_save_details_writes_only_the_four_fields(shelf, accounts_user):
    services.save_details(accounts_user, shelf["onyx"], treatment="Heated", origin="Zambia")
    shelf["onyx"].refresh_from_db()
    assert (shelf["onyx"].treatment, shelf["onyx"].origin) == ("Heated", "Zambia")
    with pytest.raises(ServiceError):
        services.save_details(accounts_user, shelf["onyx"], stone_name="Emerald")
    with pytest.raises(ServiceError):
        services.save_details(accounts_user, shelf["onyx"], treatment="Painted gold")


def test_recount_posts_the_difference(shelf, admin_user_):
    moves = services.recount(admin_user_, shelf["onyx"], pcs=18, ct=Decimal("13"))
    assert len(moves) == 2
    held = _held(shelf["onyx"])
    assert (held.on_pcs, held.on_ct) == (18, Decimal("13"))
    assert services.recount(admin_user_, shelf["onyx"], pcs=18, ct=Decimal("13")) == []
