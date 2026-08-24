"""Fixtures every test leans on: users with real roles, and a priced piece.

The users are built through ``sync_role_groups`` rather than by handing out
permissions ad hoc, so a test that passes for the SALES group is a test about
the real SALES group.
"""
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from accounts.models import User, sync_role_groups
from stock import services
from stock.enums import ChargeBasis, MaterialClass, StockState, Uom
from stock.models import (
    BomVersion,
    Category,
    Location,
    Material,
    MaterialCategory,
    Metal,
    MetalPurity,
    Piece,
    RateChart,
    RateChartLine,
    Scenario,
    Style,
    SystemSetting,
)


@pytest.fixture(autouse=True)
def _plain_static_storage(settings):
    """Tests render templates without a collectstatic run behind them."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def _reference_data(db):
    """The seed migration runs for real databases; tests get it explicitly."""
    sync_role_groups()
    return None


def _user(username, group_name, **extra):
    user = User.objects.create_user(username=username, password="correct-horse-battery", **extra)
    user.must_change_password = False
    user.save(update_fields=["must_change_password"])
    if group_name:
        user.groups.add(Group.objects.get(name=group_name))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def admin_user_(db):
    return _user("owner", "ADMIN", full_name="Owner")


@pytest.fixture
def accounts_user(db):
    return _user("accountant", "ACCOUNTS", full_name="Accounts")


@pytest.fixture
def sales_user(db):
    """A showroom login: sale price yes, cost, vendor and margin no."""
    return _user("showroom", "SALES", full_name="Showroom")


@pytest.fixture
def graphic_user(db):
    return _user("graphics", "GRAPHIC", full_name="Graphics")


@pytest.fixture
def locations(db):
    return {
        code: Location.objects.get_or_create(code=code, defaults={"name": name, "kind": kind})[0]
        for code, name, kind in [("HO", "Head Office", "GODOWN"), ("MUM", "Mumbai", "SHOWROOM")]
    }


@pytest.fixture
def rates(db):
    gold, _ = Metal.objects.get_or_create(code="GOLD", defaults={"name": "Gold", "pure_rate": Decimal("15481")})
    silver, _ = Metal.objects.get_or_create(code="SILVER", defaults={"name": "Silver", "pure_rate": Decimal("260")})
    MetalPurity.objects.get_or_create(
        karat="18K", defaults={"sale_factor": "0.7600", "true_fineness": "0.7500", "metal": gold, "sort_order": 3}
    )
    MetalPurity.objects.get_or_create(
        karat="925", defaults={"sale_factor": "1.0000", "true_fineness": "0.9250", "metal": silver, "sort_order": 2}
    )
    for key, value in [("line_rounding_dp", "0"), ("total_rounding_dp", "0"), ("gross_wt_tolerance_gm", "0.050")]:
        SystemSetting.objects.get_or_create(key=key, defaults={"value": value})
    return {"gold": gold, "silver": silver}


@pytest.fixture
def materials(db, rates):
    categories = {
        code: MaterialCategory.objects.get_or_create(
            code=code, defaults={"name": code.title(), "sort_order": order, "is_priceable": code != "LABOUR"}
        )[0]
        for order, code in enumerate(["METAL", "DIAMOND", "SETTING", "LABOUR"], start=1)
    }
    gold = Material.objects.create(
        item_code="G",
        item_name="Gold",
        mat_class=MaterialClass.METAL,
        category=categories["METAL"],
        default_uom=Uom.GM,
        metal=rates["gold"],
    )
    diamond = Material.objects.create(
        item_code="DRKL",
        item_name="Diamond RKL",
        mat_class=MaterialClass.DIAMOND,
        category=categories["DIAMOND"],
        default_uom=Uom.CT,
    )
    making = Material.objects.create(
        item_code="MAKING",
        item_name="Making Charge",
        mat_class=MaterialClass.LABOUR,
        category=categories["LABOUR"],
        default_uom=Uom.GM,
    )
    return {"gold": gold, "diamond": diamond, "making": making}


@pytest.fixture
def chart(db, materials):
    chart = RateChart.objects.create(code="DEFAULT", name="Default", is_default=True)
    RateChartLine.objects.create(
        chart=chart, material=materials["diamond"], size_band="", cost_rate=Decimal("150000"), sale_rate=Decimal("180000")
    )
    return chart


@pytest.fixture
def scenarios(db, chart):
    """The seed migration already created these; point RETAIL at the test chart."""
    retail, _ = Scenario.objects.update_or_create(
        code="RETAIL",
        defaults={"name": "Retail", "method": Scenario.CHART, "chart": chart, "is_default": True},
    )
    Scenario.objects.get_or_create(
        code="VA100",
        defaults={"name": "Value added +100%", "method": Scenario.VALUE_ADDED, "target_pct": Decimal("100")},
    )
    return retail


@pytest.fixture
def piece(db, locations, materials, admin_user_):
    """One 18K piece: 4 g of gold, 1.125 ct of diamond, making at 1500/g."""
    category = Category.objects.get_or_create(code="EARR", defaults={"name": "Earrings", "sort_order": 10})[0]
    style = Style.objects.create(style_code="ER00738", name="Petal studs", category=category)
    piece = Piece.objects.create(
        jewel_code="ER00738",
        style=style,
        metal_purity="18K",
        measured_gross_wt_gm=Decimal("4.200"),
        stock_state=StockState.NOT_RECEIVED,
        current_bom_version=1,
    )
    BomVersion.objects.create(piece=piece, version_no=1, is_current=True)
    services.set_bom(
        admin_user_,
        piece,
        [
            {
                "material": materials["gold"],
                "qty_value": Decimal("4"),
                "qty_uom": Uom.GM,
                "basis": ChargeBasis.BY_QTY,
                "cost_rate": Decimal("11611"),
                "sale_rate": Decimal("11766"),
            },
            {
                "material": materials["diamond"],
                "qty_value": Decimal("1.125"),
                "qty_uom": Uom.CT,
                "basis": ChargeBasis.BY_QTY,
                "cost_rate": Decimal("150000"),
                "sale_rate": Decimal("180000"),
            },
            {
                "material": materials["making"],
                "qty_value": None,
                "qty_uom": Uom.GM,
                "basis": ChargeBasis.BY_NET_METAL_WT,
                "cost_rate": Decimal("1200"),
                "sale_rate": Decimal("1500"),
            },
        ],
    )
    return Piece.objects.get(pk=piece.pk)


@pytest.fixture
def received_piece(db, piece, locations, admin_user_):
    services.receive_piece(admin_user_, piece, locations["MUM"])
    return Piece.objects.get(pk=piece.pk)
