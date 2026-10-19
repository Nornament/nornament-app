"""The piece sheet: one piece out in the stock upload layout, and straight back in."""
import io
from decimal import Decimal

import pytest
from django.urls import reverse

from stock.importers import analyse, commit, ivy

pytestmark = pytest.mark.django_db


def _download(client, user):
    client.force_login(user)
    response = client.get(reverse("stock:piece_sheet", kwargs={"jewel_code": "ER00738"}))
    assert response.status_code == 200
    return io.BytesIO(response.content)


def test_the_sheet_reads_back_through_the_importer(client, admin_user_, received_piece):
    sheet = _download(client, admin_user_)
    assert ivy.header_problems(sheet) == []
    [parsed] = ivy.parse(sheet)
    assert (parsed.jewel_code, parsed.style_code, parsed.category, parsed.metal_purity) == (
        "ER00738", "ER00738", "Earrings", "18K"
    )
    by_band = {line.band: line for line in parsed.lines}
    assert sorted(by_band) == ["diamond", "metal"]
    assert (by_band["diamond"].code, by_band["diamond"].qty, by_band["diamond"].cost_rate) == (
        "DRKL", Decimal("1.125"), Decimal("150000")
    )
    assert (by_band["metal"].code, by_band["metal"].qty) == ("G", Decimal("4"))
    # making is charged per gram of metal here, and goes back as BG/BH amounts
    assert (parsed.making_cost, parsed.making_sale) == (Decimal("4800"), Decimal("6000"))
    version = received_piece.current_bom()
    assert parsed.src_cost_price == version.total_cost_price

    plan = analyse.analyse([parsed])
    assert plan.blockers == []
    assert all(row.action == "map" for row in plan.materials)

    # and re-imported over itself, it costs to the rupee what it did before
    decisions = analyse.default_decisions(plan)
    decisions["pieces"]["ER00738"]["action"] = "update"
    result = commit.commit([parsed], decisions, admin_user_)
    assert result["pieces_updated"] == 1 and result["variances"] == []
    received_piece.refresh_from_db()
    assert received_piece.current_bom().total_cost_price == version.total_cost_price


def test_a_sales_login_gets_the_sheet_with_no_cost_and_no_vendor(client, sales_user, received_piece):
    from stock.models import Vendor

    received_piece.vendor = Vendor.objects.create(code="VEN01", name="Sharma Karigars")
    received_piece.save(update_fields=["vendor"])
    [parsed] = ivy.parse(_download(client, sales_user))
    assert parsed.src_cost_price is None and parsed.making_cost is None and parsed.vendor == ""
    assert all(line.cost_rate is None and line.cost_amount is None for line in parsed.lines)
    # what a showroom may see is still there
    assert parsed.src_sale_price and parsed.making_sale
    assert all(line.sale_rate for line in parsed.lines)
