"""Users are managed from Users & Settings; the Django admin is superusers only."""
import pytest
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db

#: a temporary password the validators accept; not a credential anywhere
TEMP = "fixture-temp-Value-2041"


def _add(client, **extra):
    data = {"username": "showroom2", "full_name": "Showroom Two", "email": "showroom2@example.invalid",
            "role": "SALES", "password": TEMP, **extra}
    return client.post(reverse("stock:user_add"), data)


def _edit(client, account, **changes):
    data = {"username": account.username, "full_name": account.full_name, "email": account.email,
            "role": changes.pop("role", "SALES"), "is_active": "on", **changes}
    if data["is_active"] is None:
        del data["is_active"]
    return client.post(reverse("stock:user_edit", args=[account.pk]), data)


def test_the_django_admin_turns_away_everyone_but_a_superuser(client, admin_user_):
    # an Admin-role login marked staff, as load_legacy marks imported admins
    admin_user_.is_staff = True
    admin_user_.save(update_fields=["is_staff"])
    client.force_login(admin_user_)
    assert client.get("/admin/").status_code == 302  # to the admin's own login

    root = User.objects.create_superuser(username="root", password=TEMP)
    root.must_change_password = False
    root.save(update_fields=["must_change_password"])
    client.force_login(root)
    assert client.get("/admin/").status_code == 200


def test_an_admin_adds_a_user_with_one_role_and_a_forced_password_change(client, admin_user_):
    client.force_login(admin_user_)
    # a staff or superuser flag smuggled into the post is not a field, so it does nothing
    response = _add(client, is_staff="on", is_superuser="on")
    assert response.status_code == 302

    added = User.objects.get(username="showroom2")
    assert list(added.groups.values_list("name", flat=True)) == ["SALES"]
    assert added.is_active and added.must_change_password
    assert not added.is_staff and not added.is_superuser
    assert added.check_password(TEMP)
    assert not added.user_permissions.exists()


def test_an_admin_changes_a_role_and_resets_a_password(client, admin_user_, sales_user):
    client.force_login(admin_user_)
    sales_user.must_change_password = False
    sales_user.save(update_fields=["must_change_password"])

    _edit(client, sales_user, role="ACCOUNTS", password=TEMP)

    sales_user.refresh_from_db()
    assert list(sales_user.groups.values_list("name", flat=True)) == ["ACCOUNTS"]
    assert sales_user.check_password(TEMP) and sales_user.must_change_password


def test_leaving_the_password_blank_keeps_theirs(client, admin_user_, sales_user):
    client.force_login(admin_user_)
    before = sales_user.password
    _edit(client, sales_user, full_name="Renamed")
    sales_user.refresh_from_db()
    assert sales_user.full_name == "Renamed" and sales_user.password == before


def test_nobody_can_lock_themselves_out(client, admin_user_):
    client.force_login(admin_user_)
    page = _edit(client, admin_user_, role="SALES", is_active=None)
    assert page.status_code == 200
    assert b"cannot disable your own login" in page.content
    assert b"cannot change your own role" in page.content
    admin_user_.refresh_from_db()
    assert admin_user_.is_active and admin_user_.groups.filter(name="ADMIN").exists()


def test_only_a_superuser_can_change_a_superuser(client, admin_user_):
    root = User.objects.create_superuser(username="root", password=TEMP, email="root@example.invalid")
    client.force_login(admin_user_)
    page = _edit(client, root, role="SALES", password=TEMP)
    assert b"Only a superuser can change a superuser" in page.content
    root.refresh_from_db()
    assert root.check_password(TEMP) and not root.groups.exists()


def test_two_logins_cannot_share_an_email(client, admin_user_, sales_user):
    sales_user.email = "taken@example.invalid"
    sales_user.save(update_fields=["email"])
    client.force_login(admin_user_)
    page = _add(client, email="TAKEN@example.invalid")
    assert page.status_code == 200 and b"already uses this email" in page.content
    assert not User.objects.filter(username="showroom2").exists()


def test_a_role_without_the_settings_screen_cannot_manage_users(client, sales_user):
    sales_user.must_change_password = False
    sales_user.save(update_fields=["must_change_password"])
    client.force_login(sales_user)
    assert _add(client).status_code == 403
    assert client.get(reverse("stock:user_edit", args=[sales_user.pk])).status_code == 403


def test_a_new_user_has_no_role_until_one_is_chosen(client, admin_user_):
    client.force_login(admin_user_)
    page = _add(client, role="")
    assert page.status_code == 200
    assert not User.objects.filter(username="showroom2").exists()
