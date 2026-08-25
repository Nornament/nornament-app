"""The golden harness itself, proved against a file we write here.

Without this, the parity suite would be untested code that silently skips —
and a gate that cannot fail is not a gate. This builds a golden CSV from a
piece whose figures we know, then checks the comparison catches a planted
one-rupee drift.
"""
import csv
from decimal import Decimal

import pytest

from etl import golden
from stock import services

pytestmark = pytest.mark.django_db


@pytest.fixture
def golden_file(tmp_path, monkeypatch):
    monkeypatch.setattr(golden, "GOLDEN_DIR", tmp_path)
    return tmp_path


def write(path, rows, fields):
    with (path / "api_jewel.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_the_harness_passes_when_the_figures_agree(piece, golden_file):
    version = piece.current_bom()
    write(
        golden_file,
        [
            {
                "jewel_code": piece.jewel_code,
                "cost_price": str(version.total_cost_price),
                "sale_price": str(services.live_sale_price(piece)),
                "current_cost": str(services.current_cost(piece)),
            }
        ],
        ["jewel_code", "cost_price", "sale_price", "current_cost"],
    )
    assert golden.available()
    row = golden.read("api_jewel")[0]
    assert golden.compare("cost", golden.money(row["cost_price"]), version.total_cost_price) is None


def test_the_harness_catches_a_one_rupee_drift(piece, golden_file):
    version = piece.current_bom()
    planted = version.total_cost_price + Decimal("1")
    difference = golden.compare("cost", planted, version.total_cost_price)
    assert difference is not None
    assert "off by -1" in difference


def test_a_missing_figure_on_either_side_is_a_difference():
    assert golden.compare("cost", Decimal("10"), None) is not None
    assert golden.compare("cost", None, Decimal("10")) is not None
    assert golden.compare("cost", None, None) is None


def test_money_reads_the_empty_view_cell_as_absent_not_zero():
    assert golden.money("") is None
    assert golden.money("NULL") is None
    assert golden.money("1234.56") == Decimal("1234.56")


def test_available_is_false_without_files(tmp_path, monkeypatch):
    monkeypatch.setattr(golden, "GOLDEN_DIR", tmp_path)
    assert not golden.available()
