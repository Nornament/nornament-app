"""Part 5c: the merge screen."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import services
from inventory.models import Pouch, StockDocument

pytestmark = pytest.mark.django_db
D = Decimal
ONYX = {"stone_name": "Green Onyx", "colour": "Green", "shape": "Oval", "quality": "B"}


@pytest.fixture
def twin(admin_user_, shelf):
    return services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", "size_text": "12*10", **ONYX},
                               pcs=10, ct=D("7.5"), rate=D("9000"))


def _url(pouch):
    return reverse("inventory:merge", args=[pouch.ref])


def test_the_form_lists_the_same_stone_and_ticks_the_opening_pouch(client, accounts_user, shelf, twin):
    client.force_login(accounts_user)
    body = client.get(_url(shelf["onyx"])).content.decode()
    assert "Merge pouches" in body and "Post merge" in body
    assert f'name="pouch" value="{shelf["onyx"].pk}" checked' in body
    assert f'name="pouch" value="{twin.pk}"' in body and f'name="pouch" value="{twin.pk}" checked' not in body
    assert shelf["ruby"].ref not in body
    assert f'name="into" value="{shelf["onyx"].pk}" checked' in body and 'name="into" value="new"' in body
    assert 'name="new_pouch_no" maxlength="16" value="6"' in body    # the batch's next free number
    assert "₹7,919" in body and "₹9,000" in body                       # valuation, to the cost right
    assert f'class="on" href="{reverse("inventory:movements", args=[shelf["onyx"].ref])}"' in body


def test_a_pouch_with_no_like_pouch_says_so(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(_url(shelf["ruby"])).content.decode()
    assert "No other pouch in this batch holds the same stone." in body and "Post merge" not in body


def test_posting_a_merge_into_a_new_pouch_opens_its_document(client, accounts_user, shelf, twin):
    client.force_login(accounts_user)
    response = client.post(_url(shelf["onyx"]), {"pouch": [shelf["onyx"].pk, twin.pk], "into": "new",
                                                "new_pouch_no": "7", "size_text": "mixed", "loss_ct": "0.5", "note": "re-sieved"})
    doc = StockDocument.objects.get(kind=StockDocument.Kind.MERGE)
    assert response.status_code == 302 and response["Location"] == reverse("inventory:document", args=[doc.pk])
    page = client.get(response["Location"]).content.decode()
    assert "Merge posted as MRG-000001." in page
    assert Pouch.objects.filter(batch=shelf["batch"], pouch_no="7", size_text="mixed").exists()


def test_a_merge_without_a_valuation_says_so(client, accounts_user, admin_user_, shelf):
    bare = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", **ONYX}, pcs=2, ct=D("1"), rate=None)
    client.force_login(accounts_user)
    response = client.post(_url(shelf["onyx"]), {"pouch": [shelf["onyx"].pk, bare.pk], "into": str(shelf["onyx"].pk)})
    page = client.get(response["Location"]).content.decode()
    assert "Merge posted as MRG-000001. — no valuation set: one of the pouches had none." in page


def test_a_refusal_comes_back_on_the_form_with_the_ticks_kept(client, accounts_user, shelf, twin):
    client.force_login(accounts_user)
    response = client.post(_url(shelf["onyx"]), {"pouch": [twin.pk], "into": str(twin.pk)})
    body = response.content.decode()
    assert response.status_code == 200 and "Tick at least two pouches to merge." in body
    assert f'name="pouch" value="{twin.pk}" checked' in body
    assert f'name="pouch" value="{shelf["onyx"].pk}" checked' not in body
    assert not StockDocument.objects.exists()


def test_a_pouch_outside_the_candidates_is_ignored(client, accounts_user, shelf, twin):
    client.force_login(accounts_user)
    response = client.post(_url(shelf["onyx"]), {"pouch": [shelf["onyx"].pk, shelf["ruby"].pk],
                                                "into": str(shelf["onyx"].pk)})
    assert "Tick at least two pouches to merge." in response.content.decode()


def test_the_buttons_show_to_the_assort_right_only_and_never_in_client_view(client, accounts_user, sales_user,
                                                                            admin_user_, shelf):
    merge = f'href="{_url(shelf["onyx"])}"'
    for name in ("inventory:pouch", "inventory:movements"):
        client.force_login(accounts_user)
        assert merge in client.get(reverse(name, args=[shelf["onyx"].ref])).content.decode(), name
    client.force_login(sales_user)
    assert merge not in client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    assert merge not in client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()


def test_rights_and_client_view(client, sales_user, admin_user_, shelf, twin):
    client.force_login(sales_user)
    assert client.get(_url(shelf["onyx"])).status_code == 403
    assert client.post(_url(shelf["onyx"]), {"pouch": [shelf["onyx"].pk, twin.pk], "into": "new",
                                             "new_pouch_no": "7"}).status_code == 403
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for response in (client.get(_url(shelf["onyx"])),
                     client.post(_url(shelf["onyx"]), {"pouch": [shelf["onyx"].pk, twin.pk], "into": "new",
                                                       "new_pouch_no": "7"})):
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf")
    assert not StockDocument.objects.exists()
