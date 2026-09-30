"""Who holds which inventory right — the prototype's matrix, mapped onto our groups."""
import pytest

from accounts.capabilities import (
    INV_ASSORT, INV_JOB, INV_MASTERS, INV_PURCHASE, VIEW_COST, VIEW_MARGIN, VIEW_SALE,
)

pytestmark = pytest.mark.django_db

INVENTORY = (INV_MASTERS, INV_PURCHASE, INV_JOB, INV_ASSORT)


def test_owner_and_accounts_hold_every_inventory_right(admin_user_, accounts_user):
    for user in (admin_user_, accounts_user):
        for perm in INVENTORY:
            assert user.has_perm(perm), f"{user} lacks {perm}"


def test_the_karigar_desk_posts_job_cards_and_sees_no_money(karigar_user):
    assert karigar_user.has_perm(INV_JOB)
    for perm in (INV_MASTERS, INV_PURCHASE, INV_ASSORT, VIEW_COST, VIEW_SALE, VIEW_MARGIN):
        assert not karigar_user.has_perm(perm), f"karigar holds {perm}"


def test_production_is_stock_staff(production_user):
    assert production_user.has_perm(INV_JOB)
    assert not production_user.has_perm(INV_MASTERS)
    assert not production_user.has_perm(INV_ASSORT)


def test_sales_holds_no_inventory_right(sales_user):
    for perm in INVENTORY:
        assert not sales_user.has_perm(perm)


def test_the_karigar_desk_opens_no_stock_tab():
    from accounts.capabilities import ROLE_TABS

    assert ROLE_TABS["KARIGAR"] == ()


def test_the_karigar_desk_lands_on_the_shelf_and_is_kept_out_of_the_crm(client, karigar_user):
    from django.urls import reverse

    client.force_login(karigar_user)
    assert client.get(reverse("stock:dashboard"))["Location"] == reverse("inventory:shelf")
    assert client.get(reverse("crm:dashboard")).status_code == 403
    assert client.get(reverse("crm:customer_list")).status_code == 403


def test_graphic_still_opens_the_crm(client, graphic_user):
    from django.urls import reverse

    client.force_login(graphic_user)
    assert client.get(reverse("crm:dashboard")).status_code == 200
