"""The rail's four data-quality filters: each lists exactly the pouches the rail counts."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import rows, services
from inventory.views_quality import TITLES

pytestmark = pytest.mark.django_db
CHECKS = ("misfiled", "no_pouch_no", "no_photo", "no_size")
ROW = '<a class="rowlink" href="'


@pytest.fixture
def flawed(admin_user_, shelf):
    """The shelf (the ruby is misfiled with no size in mm; neither pouch has a photo), plus a jade
    with no pouch no. and no size, and a photo on the onyx."""
    from mediahub.models import MediaAsset
    from stock.enums import MediaKind

    jade = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": None, "stone_name": "Jade", "colour": "Green"},
                               pcs=3, ct=Decimal("6"), rate=None)
    MediaAsset.objects.create(media_ref="M-ONYX-1", kind=MediaKind.PHOTO, storage_key="crm/pouch/1/a.jpg",
                              file_name="SL01G-1-01.jpg", mime_type="image/jpeg", scope="pouch",
                              scope_id=str(shelf["onyx"].pk))
    return {**shelf, "jade": jade}


def _page(client, user, check):
    client.force_login(user)
    return client.get(reverse("inventory:quality", args=[check]))


def test_each_filter_lists_exactly_the_rails_live_count(client, accounts_user, flawed):
    counts = rows.summarise(rows.pouch_rows(accounts_user, services.stocked()))
    assert [counts[check] for check in CHECKS] == [1, 1, 2, 2]
    for check in CHECKS:
        body = _page(client, accounts_user, check).content.decode()
        assert body.count(ROW) == counts[check], check
        assert f'{TITLES[check]}<span class="ct">{counts[check]}</span>' in body, check
        assert f'class="on" href="{reverse("inventory:quality", args=[check])}"' in body, check


def test_each_row_opens_its_pouch(client, accounts_user, flawed):
    body = _page(client, accounts_user, "no_pouch_no").content.decode()
    assert f'{ROW}{reverse("inventory:pouch", args=[flawed["jade"].ref])}"' in body
    assert reverse("inventory:pouch", args=[flawed["onyx"].ref]) not in body
    assert "<th>Batch</th>" in body and "SL01G" in body
    body = _page(client, accounts_user, "no_size").content.decode()
    assert f'{ROW}{reverse("inventory:pouch", args=[flawed["ruby"].ref])}"' in body
    assert f'{ROW}{reverse("inventory:pouch", args=[flawed["jade"].ref])}"' in body


def test_money_shows_only_with_the_cost_right(client, accounts_user, sales_user, flawed):
    assert "Value</th>" in _page(client, accounts_user, "misfiled").content.decode()
    body = _page(client, sales_user, "misfiled").content.decode()
    assert "Value</th>" not in body and "₹50" not in body
    assert f'{ROW}{reverse("inventory:pouch", args=[flawed["ruby"].ref])}"' in body


def test_client_view_redirects_and_an_unknown_check_is_404(client, admin_user_, karigar_user, shelf):
    assert _page(client, karigar_user, "no_photo").status_code == 200
    assert _page(client, admin_user_, "bogus").status_code == 404
    client.post(reverse("inventory:set_view"), {"view": "client"})
    response = client.get(reverse("inventory:quality", args=["misfiled"]))
    assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf")


def test_the_batch_table_is_unchanged(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:batch", args=[shelf["batch"].pk]), {"view": "table"}).content.decode()
    assert "<th>Check</th>" in body and "<th>Batch</th>" not in body and body.count(ROW) == 2
