"""Part 5e: lookbooks — curated stones shared by a private link."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import lookbooks, services
from inventory.models import Lookbook, LookbookStone
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


def _refs(book):
    return [s.pouch.ref for s in book.stones.select_related("pouch")]


def test_create_gives_a_long_random_token_and_shares_by_default(sales_user):
    book = lookbooks.create(sales_user, "Wedding greens")
    other = lookbooks.create(sales_user, "Reds")
    assert book.shared and len(book.token) >= 20 and book.token != other.token


def test_a_title_is_required(sales_user):
    with pytest.raises(ServiceError):
        lookbooks.create(sales_user, "  ")


def test_adding_by_ref_or_batch_and_pouch_no(sales_user, shelf):
    book = lookbooks.create(sales_user, "Greens")
    added, unknown, skipped = lookbooks.add_stones(
        sales_user, book, f"{shelf['onyx'].ref.lower()}, SL01G · 2\nNRN-999999\nSL01G · 77")
    assert [p.pk for p in added] == [shelf["onyx"].pk, shelf["ruby"].pk]
    assert unknown == ["NRN-999999", "SL01G · 77"] and skipped == []
    added, unknown, skipped = lookbooks.add_stones(sales_user, book, shelf["onyx"].ref)
    assert added == [] and [p.pk for p in skipped] == [shelf["onyx"].pk]
    assert _refs(book) == [shelf["onyx"].ref, shelf["ruby"].ref]


def test_moving_and_removing_keep_the_order_tidy(sales_user, shelf, admin_user_):
    jade = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", "stone_name": "Jade"}, pcs=1,
                               ct=Decimal("1"), rate=None)
    book = lookbooks.create(sales_user, "Greens")
    lookbooks.add_stones(sales_user, book, f"{shelf['onyx'].ref} {shelf['ruby'].ref} {jade.ref}")
    lookbooks.move(sales_user, book, jade.pk, -1)
    assert _refs(book) == [shelf["onyx"].ref, jade.ref, shelf["ruby"].ref]
    lookbooks.move(sales_user, book, shelf["onyx"].pk, -1)                   # already first: no-op
    lookbooks.remove(sales_user, book, jade.pk)
    assert _refs(book) == [shelf["onyx"].ref, shelf["ruby"].ref]
    assert [p.pk for p in lookbooks.pouches(book)] == [shelf["onyx"].pk, shelf["ruby"].pk]


def test_update_resolve_and_delete(sales_user, shelf):
    book = lookbooks.create(sales_user, "Greens")
    assert lookbooks.resolve(book.token) == book and lookbooks.resolve("nope") is None
    lookbooks.update(sales_user, book, "Greens for Mrs Rao", "Hand-picked", shared=False)
    book.refresh_from_db()
    assert (book.title, book.note, book.shared) == ("Greens for Mrs Rao", "Hand-picked", False)
    assert lookbooks.resolve(book.token) is None                             # off
    lookbooks.add_stones(sales_user, book, shelf["onyx"].ref)
    lookbooks.delete(sales_user, book)
    assert not Lookbook.objects.exists() and not LookbookStone.objects.exists()


def test_every_write_needs_the_sale_right(karigar_user, sales_user, shelf):
    book = lookbooks.create(sales_user, "Greens")
    for call in (lambda: lookbooks.create(karigar_user, "x"),
                 lambda: lookbooks.update(karigar_user, book, "x", "", True),
                 lambda: lookbooks.add_stones(karigar_user, book, shelf["onyx"].ref),
                 lambda: lookbooks.move(karigar_user, book, shelf["onyx"].pk, 1),
                 lambda: lookbooks.remove(karigar_user, book, shelf["onyx"].pk),
                 lambda: lookbooks.delete(karigar_user, book)):
        with pytest.raises(PermissionDenied):
            call()
