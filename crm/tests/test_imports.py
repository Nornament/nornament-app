"""The bulk importers, and the screens built on them.

The thing worth testing here is not that a CSV parses — it is that a row the
preview objects to is never written, because the whole point of the two-step is
that a silent import of the wrong column is worse than no import.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from crm import imports
from crm.models import Customer
from stock.models import Sale


@pytest.fixture
def customer(db):
    return Customer.objects.create(customer_code="NOR-001", name="Meera Raghavan", mobile="9820011223")


def _rows(text):
    return imports.read_csv(text)[1]


# ── header matching ──────────────────────────────────────────────────────
def test_headers_match_loosely_because_shop_floor_sheets_never_match_exactly():
    rows = _rows("Full Name , Phone Number ,DOB\nMeera Raghavan,9820011223,14/08/1990\n")
    assert imports._pick(rows[0], imports.CUSTOMER_FIELDS["name"]) == "Meera Raghavan"
    assert imports._pick(rows[0], imports.CUSTOMER_FIELDS["mobile"]) == "9820011223"
    assert imports.parse_date(imports._pick(rows[0], imports.CUSTOMER_FIELDS["birth_date"])) == date(1990, 8, 14)


def test_a_semicolon_sheet_and_a_bom_still_read():
    headers, rows = imports.read_csv("﻿Name;Mobile\nMeera;98200\n")
    assert headers == ["Name", "Mobile"]
    assert rows[0]["name"] == "Meera"


# ── customers ────────────────────────────────────────────────────────────
def test_a_duplicate_code_or_mobile_is_flagged_and_not_written(customer):
    preview = imports.preview_customers(
        _rows("Name,Mobile,Customer Code\nSomeone Else,,NOR-001\nMeera Again,9820011223,\nNew Person,9820099887,\n")
    )
    assert [bool(row["problem"]) for row in preview] == [True, True, False]

    created, skipped = imports.import_customers(preview)
    assert (created, skipped) == (1, 2)
    assert Customer.objects.count() == 2
    assert Customer.objects.get(mobile="9820099887").customer_code.startswith("NOR-")


def test_a_row_with_no_name_is_skipped_rather_than_creating_a_blank_customer(db):
    preview = imports.preview_customers(_rows("Name,Mobile\n,9820000000\n"))
    assert preview[0]["problem"]
    assert imports.import_customers(preview) == (0, 1)
    assert not Customer.objects.exists()


def test_two_new_rows_sharing_a_mobile_do_not_both_get_written(db):
    """The duplicate check has to see the rows above it, not just the database."""
    preview = imports.preview_customers(_rows("Name,Mobile\nOne,9820000000\nTwo,9820000000\n"))
    assert not preview[0]["problem"] and preview[1]["problem"]


# ── purchases ────────────────────────────────────────────────────────────
def test_purchases_match_a_customer_by_code_or_by_mobile(customer):
    preview = imports.preview_purchases(
        _rows(
            "Customer Code,Bill Date,Net Amount,Item Description\n"
            "NOR-001,14/08/2026,\"₹1,20,500\",Polki necklace\n"
        )
    )
    assert preview[0]["problem"] == ""
    assert preview[0]["customer"] == customer
    assert preview[0]["sold_price"] == Decimal("120500")
    assert preview[0]["sold_on"] == date(2026, 8, 14)
    assert preview[0]["category"] == "cat1"  # polki


def test_an_unmatched_customer_or_unreadable_amount_is_skipped(customer):
    preview = imports.preview_purchases(
        _rows("Customer Code,Date,Amount\nNOR-999,14/08/2026,1000\nNOR-001,14/08/2026,not a number\n")
    )
    assert all(row["problem"] for row in preview)
    assert imports.import_purchases(preview) == (0, 2)
    assert not Sale.objects.exists()


def test_an_imported_purchase_lands_in_the_one_ledger_tagged_crm(customer):
    preview = imports.preview_purchases(
        _rows("Customer Code,Date,Amount,Description,Remarks\nNOR-001,2026-08-14,50000,Gold bangle,Diwali\n")
    )
    assert imports.import_purchases(preview) == (1, 0)
    sale = Sale.objects.get()
    assert sale.source == Sale.CRM
    assert sale.customer == customer
    assert sale.cost_at_sale is None, "a CRM purchase carries no cost, so it carries no margin"
    assert sale.product_category == "cat2"  # gold
    assert sale.remarks == "Diwali"


# ── the screens ──────────────────────────────────────────────────────────
def _login(client, user):
    client.force_login(user)


def test_the_preview_writes_nothing_until_it_is_confirmed(client, admin_user_, customer):
    _login(client, admin_user_)
    csv_text = "Name,Mobile\nAsha Nair,9820044556\n"
    response = client.post(
        reverse("crm:bulk_import", kwargs={"kind": "customers"}),
        {"csv_file": _as_file(csv_text)},
    )
    assert response.status_code == 200
    assert b"Asha Nair" in response.content
    assert Customer.objects.count() == 1, "the preview wrote a row"

    response = client.post(
        reverse("crm:bulk_import", kwargs={"kind": "customers"}), {"csv_text": csv_text, "commit": "1"}
    )
    assert response.status_code == 302
    assert Customer.objects.filter(name="Asha Nair").exists()


def test_the_template_download_has_the_columns_the_page_promises(client, admin_user_):
    _login(client, admin_user_)
    body = client.get(reverse("crm:import_template", kwargs={"kind": "customers"})).content.decode()
    assert body.splitlines()[0].split(",")[:2] == ["Name", "Mobile"]


def test_an_unknown_importer_is_a_404_not_a_crash(client, admin_user_):
    _login(client, admin_user_)
    assert client.get(reverse("crm:bulk_import", kwargs={"kind": "nonsense"})).status_code == 404


def _as_file(text):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("rows.csv", text.encode(), content_type="text/csv")
