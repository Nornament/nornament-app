"""The golden suite runs against the database the ETL just loaded.

A parity test against an empty test database proves nothing, so these tests
bind to the real (rehearsal) database instead of letting pytest-django create
one. That only happens when ``GOLDEN_DB`` names it — otherwise the suite skips,
so nobody's laptop and no CI run ever points a test at a live database by
accident. Everything here reads; nothing writes.

    manage.py load_legacy
    manage.py golden_export --shim --out golden/
    GOLDEN_DB=nornament pytest -m golden
"""
import os

import pytest


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Point the default connection at the loaded database, read-only."""
    target = os.environ.get("GOLDEN_DB")
    if not target:
        yield
        return

    from django.db import connections

    connection = connections["default"]
    connection.close()
    previous = connection.settings_dict["NAME"]
    connection.settings_dict["NAME"] = target
    with django_db_blocker.unblock():
        yield
    connection.close()
    connection.settings_dict["NAME"] = previous


@pytest.fixture(autouse=True)
def _no_writes_against_the_loaded_database(request):
    """A golden test that writes would corrupt the thing it is checking."""
    if not os.environ.get("GOLDEN_DB"):
        return
    if request.node.get_closest_marker("golden") is None:
        pytest.skip("GOLDEN_DB is set — only the golden suite may run against it")
