"""Part 5e: the staff lookbook screens."""
import pytest
from django.urls import reverse

from inventory import lookbooks
from inventory.models import Lookbook

pytestmark = pytest.mark.django_db
LIST = reverse("inventory:lookbooks")


def _page(book):
    return reverse("inventory:lookbook", args=[book.pk])


def test_the_rail_opens_the_lookbooks(client, karigar_user, shelf):
    client.force_login(karigar_user)
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert f'href="{LIST}"' in body and 'Client lookbook<span class="ct">🔒' not in body
    assert client.get(LIST).status_code == 200 and "New lookbook" not in client.get(LIST).content.decode()


def test_create_add_reorder_remove_switch_and_delete(client, sales_user, shelf):
    client.force_login(sales_user)
    response = client.post(LIST, {"title": "Greens"})
    book = Lookbook.objects.get()
    assert response["Location"] == _page(book)
    client.post(_page(book), {"action": "add", "refs": f"{shelf['onyx'].ref}, {shelf['ruby'].ref}, NRN-999999"})
    body = client.get(_page(book)).content.decode()
    assert shelf["onyx"].ref in body and shelf["ruby"].ref in body and "NRN-999999" in body     # reported unknown
    assert book.token in body                                                                    # the link
    client.post(_page(book), {"action": "up", "pouch": shelf["ruby"].pk})
    assert [s.pouch_id for s in book.stones.all()] == [shelf["ruby"].pk, shelf["onyx"].pk]
    client.post(_page(book), {"action": "remove", "pouch": shelf["ruby"].pk})
    client.post(_page(book), {"action": "save", "title": "Greens", "note": "For you", "shared": ""})
    book.refresh_from_db()
    assert not book.shared and book.note == "For you" and book.stones.count() == 1
    first = client.post(_page(book), {"action": "delete"})
    assert first.status_code == 200 and Lookbook.objects.exists()                                # asks first
    client.post(_page(book), {"action": "delete", "confirm": "delete"})
    assert not Lookbook.objects.exists()


def test_adding_from_the_pouch_page(client, sales_user, shelf):
    book = lookbooks.create(sales_user, "Greens")
    client.force_login(sales_user)
    pouch_page = client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    url = reverse("inventory:lookbook_add", args=[shelf["onyx"].ref])
    assert f'href="{url}"' in pouch_page
    response = client.post(url, {"lookbook": book.pk})
    assert response["Location"] == _page(book) and book.stones.get().pouch_id == shelf["onyx"].pk


def test_the_list_renders_the_annotated_stone_count(client, sales_user, shelf):
    client.force_login(sales_user)
    book = lookbooks.create(sales_user, "Greens")
    lookbooks.add_stones(sales_user, book, f"{shelf['onyx'].ref}, {shelf['ruby'].ref}")
    body = client.get(LIST).content.decode()
    row = body[body.index(book.title):].split("</tr>")[0]
    assert ">2<" in row


def test_a_non_digit_lookbook_on_add_returns_404(client, sales_user, shelf):
    client.force_login(sales_user)
    url = reverse("inventory:lookbook_add", args=[shelf["onyx"].ref])
    assert client.post(url, {"lookbook": "abc"}).status_code == 404


def test_the_stones_table_shows_a_photo_thumbnail_or_no_photo(client, sales_user, shelf):
    from mediahub.models import MediaAsset
    from stock.enums import MediaKind

    book = lookbooks.create(sales_user, "Greens")
    lookbooks.add_stones(sales_user, book, f"{shelf['onyx'].ref}, {shelf['ruby'].ref}")
    asset = MediaAsset.objects.create(media_ref="M-a", kind=MediaKind.PHOTO, storage_key="x/a.jpg",
                                      file_name="a.jpg", mime_type="image/jpeg", scope="pouch",
                                      scope_id=str(shelf["onyx"].pk))
    client.force_login(sales_user)
    body = client.get(_page(book)).content.decode()
    assert reverse("inventory:photo", args=[asset.pk]) in body and "no photo" in body


def test_rights_and_client_view(client, karigar_user, sales_user, admin_user_, shelf):
    book = lookbooks.create(sales_user, "Greens")
    client.force_login(karigar_user)
    assert client.post(LIST, {"title": "x"}).status_code == 403
    assert client.post(_page(book), {"action": "add", "refs": shelf["onyx"].ref}).status_code == 403
    assert f'href="{reverse("inventory:lookbook_add", args=[shelf["onyx"].ref])}"' not in \
        client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert 'Client lookbook<span class="ct">🔒' in body and LIST not in body
    for url in (LIST, _page(book), reverse("inventory:lookbook_add", args=[shelf["onyx"].ref])):
        response = client.get(url)
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf"), url
