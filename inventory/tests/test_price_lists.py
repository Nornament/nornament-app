"""Part 5b: the two price lists and setting one price for a whole group."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from inventory import services, views_prices
from inventory.models import Pouch, PriceEntry
from inventory.tests.conftest import VALUE
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


@pytest.mark.parametrize("rate", [None, Decimal("0"), Decimal("-5"), Decimal("1e10"), Decimal("NaN"), Decimal("Infinity"),
                                   Decimal("0.00001"), Decimal("9999999999.99999")])
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


COST, SELLING = reverse("inventory:prices_cost"), reverse("inventory:prices_selling")


@pytest.fixture
def priced(admin_user_, shelf):
    """The shelf with a purchase price and a list price on the onyx, and an empty jade pouch."""
    services.add_price(admin_user_, shelf["onyx"], PriceEntry.PURCHASE, Decimal("6000"), date(2026, 8, 7))
    services.add_price(admin_user_, shelf["onyx"], PriceEntry.LIST, Decimal("9500"), date(2026, 9, 1))
    jade = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "9", "stone_name": "Jade", "colour": "Green"},
                               pcs=0, ct=Decimal("0"), rate=None)
    return {**shelf, "jade": jade}


def _get(client, user, url, **params):
    client.force_login(user)
    return client.get(url, params)


def test_the_cost_list_shows_purchase_valuation_and_value_with_a_total(client, accounts_user, priced):
    body = _get(client, accounts_user, COST).content.decode()
    assert priced["onyx"].ref in body and priced["ruby"].ref in body
    assert "₹6,000" in body and "₹7,919" in body and VALUE in body
    assert "1,00,988" in body                                          # 98,987.5 + 2,000
    assert f'href="{reverse("inventory:dia_settings")}#rates"' in body and "Diamonds price by the rate card →" in body
    assert 'class="on" href="' + COST + '"' in body


def test_the_selling_list_shows_list_price_value_and_margin(client, accounts_user, priced):
    body = _get(client, accounts_user, SELLING).content.decode()
    assert "₹9,500" in body and "₹1,18,750" in body                   # 12.5 ct × ₹9,500
    assert "20.0%" in body                                             # (9,500 − 7,919) / 7,919
    assert "<th class=\"r\">Margin</th>" in body


def test_the_selling_foot_total_sits_under_list_value_not_list_ct(client, accounts_user, shelf):
    body = _get(client, accounts_user, SELLING).content.decode()
    foot = body[body.index("<tfoot>"):]
    assert '<td></td><td class="r"><b>—</b></td>' in foot                # blank List /ct, then the total — never ₹0


def test_the_selling_foot_shows_the_total_in_the_list_value_cell(client, accounts_user, priced):
    body = _get(client, accounts_user, SELLING).content.decode()
    foot = body[body.index("<tfoot>"):]
    assert '<td></td><td class="r"><b>₹1,18,750</b></td>' in foot


def test_sales_sees_list_prices_but_no_cost_or_margin_and_no_cost_list(client, sales_user, priced):
    body = _get(client, sales_user, SELLING).content.decode()
    assert "₹9,500" in body and "₹1,18,750" in body
    for secret in ("7,919", VALUE, "6,000", "20.0%", "Margin</th>"):
        assert secret not in body, secret
    assert _get(client, sales_user, COST).status_code == 403


@pytest.mark.parametrize("fixture", ["karigar_user", "graphic_user", "production_user"])
def test_a_login_without_the_right_is_refused_both(client, request, priced, fixture):
    user = request.getfixturevalue(fixture)
    assert _get(client, user, COST).status_code == 403
    assert _get(client, user, SELLING).status_code == 403


def test_the_filters_narrow_the_list(client, accounts_user, priced):
    def refs(**params):
        body = _get(client, accounts_user, COST, **params).content.decode()
        return {name for name in ("onyx", "ruby", "jade") if priced[name].ref in body}

    assert refs() == {"onyx", "ruby"}                                  # in stock only, by default
    assert refs(f="1") == {"onyx", "ruby", "jade"}                     # the box unticked: every pouch
    assert refs(stone="ONYX") == {"onyx"}
    assert refs(colour="Red") == {"ruby"}
    assert refs(shape="Oval") == {"onyx"} and refs(quality="A") == {"ruby"} and refs(size_text="14*10") == {"onyx"}
    assert refs(batch="sl0") == {"onyx", "ruby"} and refs(batch="XX") == set()
    assert refs(box="G") == {"onyx", "ruby"}


def test_paging_keeps_the_filters(client, accounts_user, priced, monkeypatch):
    monkeypatch.setattr(views_prices, "PAGE", 1)
    first = _get(client, accounts_user, COST, f="1", batch="SL").content.decode()
    assert "Page 1 of 3" in first and "?f=1&amp;batch=SL&amp;stock=1&page=2" not in first
    assert "?f=1&amp;batch=SL&page=2" in first                        # the box unticked stays unticked
    second = _get(client, accounts_user, COST, f="1", batch="SL", page="2").content.decode()
    assert "Page 2 of 3" in second


def test_the_rail_opens_each_list_by_right(client, accounts_user, sales_user, karigar_user, priced):
    body = _get(client, accounts_user, reverse("inventory:shelf")).content.decode()
    assert f'href="{COST}"' in body and f'href="{SELLING}"' in body
    body = _get(client, sales_user, reverse("inventory:shelf")).content.decode()
    assert f'href="{COST}"' not in body and "Price list — cost<span class=\"ct\">🔒" in body
    assert f'href="{SELLING}"' in body
    body = _get(client, karigar_user, reverse("inventory:shelf")).content.decode()
    assert "Price list — selling<span class=\"ct\">🔒" in body and f'href="{SELLING}"' not in body


def test_client_view_padlocks_both_and_redirects_both(client, admin_user_, priced):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert COST not in body and SELLING not in body and "Price list — cost" not in body
    assert "Price list — selling<span class=\"ct\">🔒" in body
    for url in (COST, SELLING):
        response = client.get(url)
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf"), url


def _set(client, user, url, count, rate="1250", **filters):
    client.force_login(user)
    return client.post(url, {"f": "1", "stock": "1", **filters, "count": str(count), "rate": rate,
                             "effective_from": timezone.localdate().isoformat()})


def _said(response):
    """Follows the redirect, the way a browser does — the flash is read off the page it lands on
    (consuming it there), not off the request that queued it, so a later post never inherits it."""
    followed = response.client.get(response["Location"])
    return [str(m) for m in followed.context["messages"]]


def test_setting_a_list_price_prices_every_filtered_pouch_on_every_page(client, accounts_user, priced, monkeypatch):
    monkeypatch.setattr(views_prices, "PAGE", 1)
    response = _set(client, accounts_user, SELLING, 2, batch="SL")
    assert response.status_code == 302
    assert response["Location"] == f"{SELLING}?f=1&batch=SL&stock=1"
    assert _said(response) == ["List price set on 2 pouches."]
    assert services.latest_price(priced["ruby"], PriceEntry.LIST).rate == Decimal("1250")
    assert services.latest_price(priced["onyx"], PriceEntry.LIST).rate == Decimal("1250")
    assert not priced["jade"].prices.exists()                         # empty, so not in the in-stock group


def test_setting_a_valuation_from_the_cost_list_shows_on_the_pouch(client, accounts_user, priced):
    response = _set(client, accounts_user, COST, 1, rate="8000", stone="onyx")
    assert _said(response) == ["Valuation set on 1 pouch."]
    body = client.get(reverse("inventory:pouch", args=[priced["onyx"].ref])).content.decode()
    assert "₹8,000" in body


def test_a_changed_group_or_a_bad_rate_writes_nothing_and_says_why(client, accounts_user, priced):
    before = PriceEntry.objects.count()
    response = _set(client, accounts_user, SELLING, 5)
    assert _said(response) == ["The group changed since the page loaded — check the count and set again."]
    response = _set(client, accounts_user, SELLING, 2, rate="0")
    assert _said(response) == ["The rate has to be a number above zero, at most ten digits before the point."]
    response = _set(client, accounts_user, SELLING, 2, rate="abc")
    assert "The rate has to be a number" in _said(response)[0]
    response = _set(client, accounts_user, SELLING, 0, stone="nothing-like-this")
    assert _said(response) == ["No pouch matches these filters."]
    assert PriceEntry.objects.count() == before


def test_a_date_that_does_not_exist_is_refused_and_writes_nothing(client, accounts_user, priced):
    before = PriceEntry.objects.count()
    client.force_login(accounts_user)
    response = client.post(SELLING, {"f": "1", "stock": "1", "count": "2", "rate": "1250",
                                     "effective_from": "2026-02-30"})
    assert _said(response) == ["That date does not exist."]
    assert PriceEntry.objects.count() == before


def test_the_form_shows_only_to_who_may_set_and_states_the_count(client, accounts_user, sales_user, priced):
    body = _get(client, accounts_user, SELLING).content.decode()
    assert "Set for 2 pouches" in body and 'name="count" value="2"' in body and "Set list price" in body
    assert "Set valuation" in _get(client, accounts_user, COST).content.decode()
    assert "Set for" not in _get(client, sales_user, SELLING).content.decode()


def test_sales_cannot_set_a_list_price_even_by_posting(client, sales_user, priced):
    before = PriceEntry.objects.count()
    assert _set(client, sales_user, SELLING, 2).status_code == 403
    assert PriceEntry.objects.count() == before


def test_client_view_refuses_a_post(client, admin_user_, priced):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    before = PriceEntry.objects.count()
    response = _set(client, admin_user_, SELLING, 2)
    assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf")
    assert PriceEntry.objects.count() == before
