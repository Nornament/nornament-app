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
