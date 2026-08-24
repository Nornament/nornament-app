"""Comparing this app's figures against the legacy SQL views, to the paisa.

``golden_export`` writes one CSV per ``api`` view out of the legacy database
with ``app.has_cap()`` shimmed to true, so the files carry real costs and
margins rather than the nulls a masked view would emit. This module reads those
files and recomputes the same figures through ``stock.services``.

The suite is skipped when no golden files are present — a laptop with no dump
restored should not fail the build — and it is the gate that must be green
before cutover, where the files do exist.
"""
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings

GOLDEN_DIR = Path(settings.BASE_DIR) / "golden"


def available(view="api_jewel"):
    return (GOLDEN_DIR / f"{view}.csv").exists()


def read(view):
    path = GOLDEN_DIR / f"{view}.csv"
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def money(value):
    """CSV text to Decimal. Empty means the view had nothing, not zero."""
    if value in (None, "", "NULL"):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def compare(label, expected, actual, tolerance=Decimal("0")):
    """One figure. Returns a difference description, or None when they agree."""
    if expected is None and actual is None:
        return None
    if expected is None or actual is None:
        return f"{label}: legacy={expected!r} new={actual!r}"
    if abs(Decimal(expected) - Decimal(actual)) > tolerance:
        return f"{label}: legacy={expected} new={actual} (off by {Decimal(actual) - Decimal(expected)})"
    return None
