import pytest
from django.urls import reverse

from inventory.tests.conftest import VALUE

pytestmark = pytest.mark.django_db


def test_the_shelf_groups_by_box_colour(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert "Shelf — by box colour" in body
    assert "Green" in body and "1,00,988" in body       # 98,987.50 + 2,000 across the box colour
    assert "1 misfiled" in body                     # Ruby Glass, red, in a green box


def test_every_role_may_open_the_shelf(client, shelf, sales_user, karigar_user, graphic_user, production_user):
    for user in (sales_user, karigar_user, graphic_user, production_user):
        client.force_login(user)
        assert client.get(reverse("inventory:shelf")).status_code == 200, user


def test_the_view_switch_is_remembered(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client", "next": reverse("inventory:shelf")})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert 'data-view="client"' in body and "Stock value" not in body


def test_a_box_colour_lists_its_batches(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:colour", args=["G"])).content.decode()
    assert "Green — 1 batches" in body and "SL01G" in body and "2 pouches" in body
    assert "Stone · Lab / Man-made" in body and "1 colour mismatch" in body


def test_a_batch_shows_its_pouches_and_decodes_its_code(client, admin_user_, shelf):
    client.force_login(admin_user_)
    url = reverse("inventory:batch", args=[shelf["batch"].pk])
    grid = client.get(url).content.decode()
    assert "material family" in grid and "SL01G · 1" in grid and "uncountable" in grid
    table = client.get(url, {"view": "table"}).content.decode()
    assert "<th>Check</th>" in table and "chip good" in table          # Green Onyx: no flag, so ok


def test_show_all_lifts_the_forty_batch_cap(client, admin_user_, shelf):
    from inventory import services
    from inventory.models import Batch

    for n in range(2, 43):
        batch = Batch.objects.create(code=f"SL{n:02d}G", box_colour_id="G", family="S", cls="L", seq=f"{n:02d}")
        services.open_pouch(admin_user_, batch, {"pouch_no": "1", "colour": "Green"}, pcs=1, ct=1, rate=1)
    client.force_login(admin_user_)
    capped = client.get(reverse("inventory:colour", args=["G"])).content.decode()
    assert "Show all 42 batches" in capped
    assert "Show all" not in client.get(reverse("inventory:colour", args=["G"]), {"all": "1"}).content.decode()
