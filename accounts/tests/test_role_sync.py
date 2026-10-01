import pytest
from django.contrib.auth.models import Group, Permission

from accounts.models import sync_role_groups

pytestmark = pytest.mark.django_db


def test_an_admins_untick_survives_a_resync():
    sync_role_groups()
    accounts = Group.objects.get(name="ACCOUNTS")
    accounts.permissions.remove(Permission.objects.get(codename="inv_assort"))
    sync_role_groups()
    assert not accounts.permissions.filter(codename="inv_assort").exists()


def test_a_new_right_is_granted_to_the_roles_that_list_it():
    Permission.objects.filter(codename="inv_assort").delete()     # as if the right were brand new
    sync_role_groups()
    assert Group.objects.get(name="ACCOUNTS").permissions.filter(codename="inv_assort").exists()
    assert not Group.objects.get(name="SALES").permissions.filter(codename="inv_assort").exists()


def test_a_new_role_gets_its_full_defaults():
    Group.objects.filter(name="KARIGAR").delete()
    sync_role_groups()
    assert list(Group.objects.get(name="KARIGAR").permissions.values_list("codename", flat=True)) == ["inv_job"]
