"""The removal migration, run against the state just before it."""
import pytest
from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("accounts", "0005_inv_move")]
AFTER = [("accounts", "0006_remove_rm")]


def test_karigar_only_logins_are_deactivated_and_the_rights_are_gone():
    executor = MigrationExecutor(connection)
    # the test DB is built with 0006 applied and it cannot be reversed, so
    # forget it was applied; its forward step is idempotent on a clean schema
    executor.recorder.record_unapplied("accounts", "0006_remove_rm")
    executor.loader.build_graph()
    old = executor.loader.project_state(BEFORE).apps
    Group, User = old.get_model("auth", "Group"), old.get_model("accounts", "User")
    karigar, _ = Group.objects.get_or_create(name="KARIGAR")
    sales, _ = Group.objects.get_or_create(name="SALES")
    desk = User.objects.create(username="desk", is_active=True)
    desk.groups.add(karigar)
    both = User.objects.create(username="both", is_active=True)
    both.groups.add(karigar, sales)

    executor = MigrationExecutor(connection)
    executor.migrate(AFTER)
    new = executor.loader.project_state(AFTER).apps
    User, Group, Permission = new.get_model("accounts", "User"), new.get_model("auth", "Group"), new.get_model("auth", "Permission")
    assert User.objects.get(username="desk").is_active is False
    assert User.objects.get(username="both").is_active is True
    assert not Group.objects.filter(name="KARIGAR").exists()
    assert not Permission.objects.filter(codename__startswith="inv_").exists()
    with connection.cursor() as cursor:
        cursor.execute("select count(*) from information_schema.tables where table_name like 'inv\\_%'")
        assert cursor.fetchone()[0] == 0


def test_the_removal_cannot_be_reversed():
    executor = MigrationExecutor(connection)
    with pytest.raises(IrreversibleError):
        executor.migrate(BEFORE)
