"""Reading the restored Supabase dump.

The dump is restored into its own database on the same cluster and reached
through the ``legacy`` alias. Nothing here writes to it: it is a read-only
source that gets thrown away after cutover.
"""
from django.db import connections
from django.db.utils import ConnectionDoesNotExist

LEGACY = "legacy"


class LegacyUnavailable(RuntimeError):
    """Raised with an explanation rather than a psycopg traceback."""


def connection():
    try:
        return connections[LEGACY]
    except ConnectionDoesNotExist as error:
        raise LegacyUnavailable(
            "No 'legacy' database is configured. Restore the Supabase dump into its own "
            "database and set LEGACY_DB_NAME (see docs/RUNBOOK.md)."
        ) from error


def rows(sql, params=None):
    """Every row of a query as a dict, streamed through a server-side cursor."""
    with connection().cursor() as cursor:
        cursor.execute(sql, params or [])
        columns = [column[0] for column in cursor.description]
        while batch := cursor.fetchmany(2000):
            for row in batch:
                yield dict(zip(columns, row))


def scalar(sql, params=None):
    with connection().cursor() as cursor:
        cursor.execute(sql, params or [])
        result = cursor.fetchone()
        return result[0] if result else None


def scalar_row(sql, params=None):
    """One row, as a tuple — for a query that returns several aggregates."""
    with connection().cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchone() or ()


def table_exists(qualified_name):
    schema, _, table = qualified_name.partition(".")
    return bool(
        scalar(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
            [schema or "public", table],
        )
    )


def reset_sequences(app_labels=("stock", "crm", "accounts", "mediahub")):
    """After preserving primary keys, the sequences must be told where we are."""
    from django.apps import apps
    from django.db import connection as default_connection

    statements = []
    for label in app_labels:
        # unmanaged models own no table and therefore no sequence
        models = [model for model in apps.get_app_config(label).get_models() if model._meta.managed]
        statements.extend(default_connection.ops.sequence_reset_sql(no_style(), models))
    with default_connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
    return len(statements)


def no_style():
    from django.core.management.color import no_style as _no_style

    return _no_style()
