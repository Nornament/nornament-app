"""Login, the imported bcrypt hashes, and the forced password change."""
import bcrypt
import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from accounts.models import User, sync_role_groups

pytestmark = pytest.mark.django_db

#: Fixture credentials. Deliberately not a real name and not a plausible
#: password: a test that reads like a leaked login trips secret scanners, and
#: reusing a real person's username from the seed data invites the question of
#: whether it ever was one.
FIXTURE_LOGIN = "imported-user"
FIXTURE_PASSWORD = "fixture-value-not-a-credential"
FIXTURE_EMAIL = "imported-user@example.invalid"


def gotrue_hash(password):
    """What Supabase stores: bcrypt 2a, cost 10."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10, prefix=b"2a")).decode()


def test_an_imported_gotrue_hash_authenticates_unchanged(client):
    User.objects.create(
        username=FIXTURE_LOGIN,
        email=FIXTURE_EMAIL,
        password=f"bcrypt${gotrue_hash(FIXTURE_PASSWORD)}",
        must_change_password=False,
    )
    assert client.login(username=FIXTURE_LOGIN, password=FIXTURE_PASSWORD)


def test_django_rehashes_the_imported_password_on_first_login(client):
    user = User.objects.create(
        username=FIXTURE_LOGIN, password=f"bcrypt${gotrue_hash(FIXTURE_PASSWORD)}", must_change_password=False
    )
    assert user.password.startswith("bcrypt$")
    client.login(username=FIXTURE_LOGIN, password=FIXTURE_PASSWORD)
    user.refresh_from_db()
    # the modern default takes over silently — nobody had to change anything
    assert user.password.startswith("pbkdf2_")


def test_email_works_as_a_username(client):
    User.objects.create(
        username=FIXTURE_LOGIN,
        email=FIXTURE_EMAIL.upper(),
        password=f"bcrypt${gotrue_hash(FIXTURE_PASSWORD)}",
        must_change_password=False,
    )
    assert client.login(username=FIXTURE_EMAIL, password=FIXTURE_PASSWORD)


def test_a_wrong_password_is_refused(client):
    User.objects.create(username=FIXTURE_LOGIN, password=f"bcrypt${gotrue_hash(FIXTURE_PASSWORD)}")
    assert not client.login(username=FIXTURE_LOGIN, password=FIXTURE_PASSWORD + "-wrong")


def test_a_password_over_72_bytes_is_refused_rather_than_truncated():
    """bcrypt truncates silently; the form does not."""
    from django.core.exceptions import ValidationError

    from accounts.validators import BcryptLengthValidator

    with pytest.raises(ValidationError):
        BcryptLengthValidator().validate("x" * 73)
    BcryptLengthValidator().validate("x" * 72)


def test_must_change_password_blocks_every_other_screen(client, sales_user):
    sales_user.must_change_password = True
    sales_user.save(update_fields=["must_change_password"])
    client.force_login(sales_user)
    response = client.get(reverse("stock:piece_list"))
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:password_change")


def test_changing_the_password_clears_the_flag(client, sales_user):
    sales_user.must_change_password = True
    sales_user.save(update_fields=["must_change_password"])
    client.force_login(sales_user)
    replacement = FIXTURE_PASSWORD + "-replaced"
    response = client.post(
        reverse("accounts:password_change"),
        {"new_password1": replacement, "new_password2": replacement},
    )
    sales_user.refresh_from_db()
    assert response.status_code == 302
    assert not sales_user.must_change_password
    assert sales_user.check_password(replacement)


def test_role_groups_carry_the_capabilities_of_app_role():
    sync_role_groups()
    sales = User.objects.create_user(username="s", password=FIXTURE_PASSWORD)
    sales.groups.add(Group.objects.get(name="SALES"))
    sales = User.objects.get(pk=sales.pk)
    assert sales.has_perm("accounts.view_sale")
    assert not sales.has_perm("accounts.view_cost")
    assert not sales.has_perm("accounts.view_margin")
    assert not sales.has_perm("accounts.melt")
    assert not sales.is_privileged()

    admin = User.objects.create_user(username="a", password=FIXTURE_PASSWORD)
    admin.groups.add(Group.objects.get(name="ADMIN"))
    admin = User.objects.get(pk=admin.pk)
    assert all(admin.has_perm(perm) for perm in ["accounts.view_cost", "accounts.melt", "accounts.edit_bom"])
    assert admin.is_admin() and admin.is_privileged()


def test_no_home_location_means_every_location_is_visible(accounts_user, locations):
    from stock.models import Location

    assert accounts_user.home_location_id is None
    assert set(accounts_user.visible_location_ids()) == set(Location.objects.values_list("pk", flat=True))

    accounts_user.home_location = locations["MUM"]
    accounts_user.save(update_fields=["home_location"])
    assert accounts_user.visible_location_ids() == [locations["MUM"].pk]

    accounts_user.locations.add(locations["HO"])
    assert set(accounts_user.visible_location_ids()) == {locations["MUM"].pk, locations["HO"].pk}
