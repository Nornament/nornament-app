from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import dia_rows, dia_seed, dia_services
from inventory.models import DiamondTerm

from inventory.tests.conftest import DIA_COST, DIA_SALE_VALUE

pytestmark = pytest.mark.django_db


def test_search_shows_the_stock_and_the_filters(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "Natural Diamond" in body and "Foil Polki" in body and "start here" in body
    assert "3 of 3 lines" in body and DIA_COST in body and DIA_SALE_VALUE in body
    assert "Diamonds are internal only — no client view" in body
    assert "Client preview" not in body                  # no client view on the diamond side


def test_a_filter_narrows_the_table(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds"), {"cat": "Foil Polki"}).content.decode()
    assert "1 of 3 lines" in body and "Showing only what" in body and "FPL" in body
    assert "Grades and sizes absent from this category are not offered." in body
    assert "per-stone, carat-banded goods only" in body
    assert "DRFGH VS-SI</td>" not in body


def test_sales_sees_no_cost_column(client, sales_user, diamonds):
    client.force_login(sales_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "Cost / ct" not in body and DIA_COST not in body and "Hidden for Sales / Showroom" in body


def test_an_admin_can_preview_a_role(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:diamonds"), {"as": "SALES"}).content.decode()
    assert DIA_COST not in body and "✕ cost" in body


def test_a_non_admin_cannot_preview(client, sales_user, diamonds):
    client.force_login(sales_user)
    body = client.get(reverse("inventory:diamonds"), {"as": "ADMIN"}).content.decode()
    assert DIA_COST not in body


def test_a_line_at_zero_leaves_search(client, accounts_user, admin_user_, diamonds):
    dia_services.recount_line(admin_user_, diamonds["polki"], Decimal("0"))
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "2 of 2 lines" in body and "FPL" not in body and "Foil Polki" not in body
    assert dia_rows.rail_counts()["lines"] == 2


def test_margin_counts_only_lines_priced_both_ways(client, accounts_user, admin_user_, diamonds):
    dia_services.set_rate(admin_user_, diamonds["princess"].code, "", Decimal("21000"), None, date(2026, 9, 1))
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "27.2%" in body                                   # the round line's margin; the cost-only line stays out


def test_money_columns_follow_the_role_not_the_rows(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:diamonds"), {"batch": "no-such-batch"}).content.decode()
    assert "0 of 3 lines" in body and "Cost / ct" in body and "Hidden" not in body


def test_an_empty_register_hides_nothing_from_an_admin(client, admin_user_):
    dia_seed.load(DiamondTerm)
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "Cost / ct" in body and "Hidden" not in body
