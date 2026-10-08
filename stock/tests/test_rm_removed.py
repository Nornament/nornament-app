"""Stones & Diamonds moved to its own app (nornament-rm); nothing of it stays here."""
import pytest
from django.apps import apps
from django.urls import NoReverseMatch, reverse

from accounts import capabilities

pytestmark = pytest.mark.django_db


def test_the_inventory_app_and_its_urls_are_gone():
    assert not apps.is_installed("inventory")
    with pytest.raises(NoReverseMatch):
        reverse("inventory:shelf")
    with pytest.raises(NoReverseMatch):
        reverse("lookbook_public", args=["x"])


def test_no_inventory_rights_and_no_karigar_role():
    assert not any(cap.split(".")[1].startswith("inv_") for cap in capabilities.ALL)
    assert "KARIGAR" not in capabilities.ROLE_GROUPS and "KARIGAR" not in capabilities.ROLE_TABS


def test_no_stones_link_in_either_shell(client, admin_user_):
    client.force_login(admin_user_)
    assert b"Stones" not in client.get(reverse("stock:dashboard")).content
    assert b"Stones" not in client.get(reverse("crm:dashboard")).content
