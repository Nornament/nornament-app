"""The top bar's search: what each kind of query finds, the cap, the minimum, and where it is
not offered."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import dia_services, services
from inventory.tests.conftest import DIA_COST, DIA_COST_VALUE, VALUE

pytestmark = pytest.mark.django_db
D = Decimal
ROW = '<a class="rowlink" href="'


def _found(client, user, q):
    client.force_login(user)
    return client.get(reverse("inventory:search"), {"q": q}).content.decode()


def _pouch(pouch):
    return f'{ROW}{reverse("inventory:pouch", args=[pouch.ref])}"'


def _line(line):
    return f'{ROW}{reverse("inventory:dia_line", args=[line.ref])}"'


def test_the_box_is_live_on_both_sides_and_padlocked_in_client_view(client, admin_user_, shelf, diamonds):
    box = f'action="{reverse("inventory:search")}"'
    client.force_login(admin_user_)
    assert box in client.get(reverse("inventory:shelf")).content.decode()
    assert box in client.get(reverse("inventory:diamonds")).content.decode()
    client.post(reverse("inventory:set_view"), {"view": "client"})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert box not in body and "Search batch, pouch, stone… 🔒" in body
    response = client.get(reverse("inventory:search"), {"q": "onyx"})
    assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf")


def test_a_pouch_is_found_by_ref_batch_batch_and_pouch_no_or_stone_name(client, accounts_user, shelf):
    onyx, ruby = shelf["onyx"], shelf["ruby"]
    for q, hits in [(onyx.ref.lower(), {onyx}), ("sl01g", {onyx, ruby}), ("SL01G · 2", {ruby}),
                    ("SL01G 1", {onyx}), ("onyx", {onyx}), ("GLASS", {ruby}), ("SL01", set())]:
        body = _found(client, accounts_user, q)
        for pouch in (onyx, ruby):
            assert (_pouch(pouch) in body) == (pouch in hits), (q, pouch.ref)


def test_a_diamond_line_is_found_by_ref_item_code_or_batch_no(client, accounts_user, diamonds):
    lines = (diamonds["round"], diamonds["princess"], diamonds["polki"])
    rnd, princess, polki = lines
    for q, hits in [(rnd.ref.lower(), {rnd}), ("drfgh vs si", {rnd}), ("VVS", {princess}),
                    ("b-771", {rnd, princess}), ("bw-1", {polki}), ("FPL", {polki})]:
        body = _found(client, accounts_user, q)
        for line in lines:
            assert (_line(line) in body) == (line in hits), (q, line.ref)


def test_each_group_shows_at_most_fifty(client, admin_user_, shelf, diamonds):
    services.open_pouches(admin_user_, [(shelf["batch"], {"pouch_no": str(n), "stone_name": "Agate"}, 1, D("1"), None)
                                        for n in range(10, 65)])
    rnd = diamonds["round"]
    dia_services.open_lines(admin_user_, [
        {"category": rnd.category, "code": rnd.code, "batch_no": "AGATE", "size_text": "+2", "band": rnd.band,
         "src": f"Sheet!{n}", "ct": D("1")} for n in range(100, 155)])
    body = _found(client, admin_user_, "agate")
    pouches = reverse("inventory:pouch", args=["x"]).removesuffix("x/")
    lines = reverse("inventory:dia_line", args=["x"]).removesuffix("x/")
    assert body.count(f"{ROW}{pouches}") == 50 and body.count(f"{ROW}{lines}") == 50
    assert body.count("first 50 of 55") == 2


def test_a_query_under_two_characters_finds_nothing(client, accounts_user, shelf):
    for q in ("", "   ", "s"):
        body = _found(client, accounts_user, q)
        assert "Nothing found" in body and _pouch(shelf["onyx"]) not in body, q


def test_results_carry_no_money_and_every_internal_role_may_search(client, accounts_user, karigar_user, shelf,
                                                                   diamonds):
    body = _found(client, accounts_user, "SL01G")
    assert _pouch(shelf["onyx"]) in body and "7,919" not in body and VALUE not in body
    body = _found(client, accounts_user, "B-771")
    assert _line(diamonds["round"]) in body and DIA_COST not in body and DIA_COST_VALUE not in body
    assert _pouch(shelf["onyx"]) in _found(client, karigar_user, "onyx")
