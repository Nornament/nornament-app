"""Part 5a's rail and tabs: what was padlocked now links, and what stays padlocked still is."""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db
CHECKS = ("misfiled", "no_pouch_no", "no_photo", "no_size")


def _shelf(client, user):
    client.force_login(user)
    return client.get(reverse("inventory:shelf")).content.decode()


def test_the_stones_rail_links_the_lists_and_the_data_quality_filters(client, accounts_user, shelf):
    body = _shelf(client, accounts_user)
    urls = [reverse("inventory:splits"), reverse("inventory:transfers"),
            *(reverse("inventory:quality", args=[check]) for check in CHECKS)]
    for url in urls:
        assert f'href="{url}"' in body, url
    assert 'Misfiled colour<span class="ct">1</span>' in body and 'No pouch no.<span class="ct">0</span>' in body
    assert 'Missing photos<span class="ct">2</span>' in body and 'No size in mm<span class="ct">1</span>' in body
    assert "🔒" not in body.split('<div class="nav-h">Data quality</div>')[1].split("</nav>")[0]
    assert f'href="{reverse("inventory:stock_takes")}"' in body and f'href="{reverse("inventory:lookbooks")}"' in body


def test_client_view_shows_neither_the_lists_nor_the_filters(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert reverse("inventory:splits") not in body and reverse("inventory:quality", args=["misfiled"]) not in body


def test_the_diamond_movements_tab_is_live_and_so_is_stock_take(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert f'href="{reverse("inventory:dia_movements")}">Movements</a>' in body
    assert f'href="{reverse("inventory:dia_stock_takes")}">Stock take</a>' in body
    previewed = client.get(reverse("inventory:diamonds"), {"as": "SALES"}).content.decode()       # only an admin previews
    assert f'href="{reverse("inventory:dia_movements")}?as=SALES">Movements</a>' in previewed


def test_suppliers_opens_the_supplier_card_for_whoever_keeps_suppliers(client, accounts_user, production_user,
                                                                       sales_user, shelf):
    target = f'href="{reverse("inventory:dia_settings")}#suppliers"'
    body = _shelf(client, accounts_user)
    assert target in body and 'Suppliers<span class="ct">🔒' not in body
    assert 'id="suppliers"' in client.get(reverse("inventory:dia_settings")).content.decode()
    client.post(reverse("inventory:set_view"), {"view": "client"})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert target not in body and 'Suppliers<span class="ct">🔒' in body
    for user in (production_user, sales_user):          # Production sees suppliers but does not edit settings
        body = _shelf(client, user)
        assert target not in body and 'Suppliers<span class="ct">🔒' in body, user
