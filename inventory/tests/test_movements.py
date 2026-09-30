from decimal import Decimal

import pytest
from django.urls import reverse

from inventory.models import Movement

pytestmark = pytest.mark.django_db


def test_the_ledger_runs_a_balance(client, admin_user_, shelf):
    onyx = shelf["onyx"]
    Movement.objects.create(pouch=onyx, reason=Movement.Reason.SALE, direction=Movement.OUT, pcs=5, ct=Decimal("2.5"))
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:movements", args=[onyx.ref])).content.decode()
    assert "Opening Balance" in body and "Sale" in body
    assert "10.00 ct" in body and "15 pcs" in body            # balance after the sale
    assert "2 movements" in body


def test_filtering_by_reason_keeps_the_running_balance(client, admin_user_, shelf):
    onyx = shelf["onyx"]
    Movement.objects.create(pouch=onyx, reason=Movement.Reason.SALE, direction=Movement.OUT, pcs=5, ct=Decimal("2.5"))
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:movements", args=[onyx.ref]), {"reason": "Sale"}).content.decode()
    assert "10.00 ct" in body and "Opening Balance</span>" not in body


def test_client_view_never_opens_the_ledger(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    response = client.get(reverse("inventory:movements", args=[shelf["onyx"].ref]))
    assert response.status_code == 302
