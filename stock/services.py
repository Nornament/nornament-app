"""The business logic that used to live in 35 ``api.*`` functions.

Rules kept verbatim from the SQL, with the migration each came from named:

* a piece in a terminal state never moves again (``trg_apply_movement``)
* the ledger is the truth; the piece row is derived from its last movement
* metal is priced from its metal's live rate and is never marked up (0032b/0036)
* line and total rounding come from ``system_setting``, not from taste (0001b)
* melting needs the capability *and* a reason of at least ten characters (0001c)

Every write goes through here. Views call services; services never decide what
a user is allowed to *see* — masking is a view/template concern, stated once in
``stock/masking.py``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from accounts.capabilities import ADJUST_STOCK, EDIT_BOM, MELT
from .enums import (
    BomChangeReason,
    COUNTABLE_STATES,
    ChargeBasis,
    GRAMS_PER_UNIT,
    MaterialClass,
    MovementType,
    StockState,
    TERMINAL_STATES,
)
from .models import (
    ActivityLog,
    BomLine,
    BomVersion,
    Location,
    MeltRecord,
    Metal,
    MetalPurity,
    Piece,
    RateChart,
    RateChartLine,
    RepairJob,
    Sale,
    StockCount,
    StockCountScan,
    StockMovement,
    SystemSetting,
)

ZERO = Decimal("0")


class ServiceError(ValidationError):
    """A rule said no. These were ``RAISE EXCEPTION`` in the SQL."""


# ── settings and rounding ────────────────────────────────────────────────
def setting(key, default=None):
    row = SystemSetting.objects.filter(pk=key).first()
    return row.value if row else default


def setting_int(key, default):
    try:
        return int(setting(key, default))
    except (TypeError, ValueError):
        return int(default)


def setting_num(key, default):
    try:
        return Decimal(str(setting(key, default)))
    except (TypeError, ValueError):
        return Decimal(str(default))


def line_dp():
    return setting_int("line_rounding_dp", 0)


def total_dp():
    return setting_int("total_rounding_dp", 0)


def round_to(value, dp):
    """Postgres ``ROUND(numeric, int)`` — half away from zero, not banker's."""
    if value is None:
        return None
    quant = Decimal(1).scaleb(-dp)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def line_weight_gm(qty, uom):
    """``app.line_weight_gm`` — PCS converts to zero grams, deliberately."""
    if qty is None:
        return ZERO
    return Decimal(qty) * Decimal(GRAMS_PER_UNIT.get(uom, "0"))


# ── metal rates ──────────────────────────────────────────────────────────
def metal_rate(karat, side="SALE"):
    """``app.metal_rate`` — SALE uses the sale factor, COST the true fineness."""
    if not karat:
        return ZERO
    purity = MetalPurity.objects.select_related("metal").filter(pk=karat).first()
    if purity is None:
        return ZERO
    factor = purity.true_fineness if side.upper() == "COST" else purity.sale_factor
    return round_to(purity.metal.pure_rate * factor, 0)


def alloy_sale_rate(karat):
    return metal_rate(karat, "SALE")


def alloy_cost_rate(karat):
    return metal_rate(karat, "COST")


def set_metal_rate(user, code, pure_rate):
    """A fat finger here reprices the whole catalogue, so a 3× move is refused."""
    if not user.is_admin():
        raise ServiceError("Only an admin can change a metal rate.")
    metal = Metal.objects.filter(pk=(code or "").strip().upper()).first()
    if metal is None:
        raise ServiceError(f'No metal called "{code}".')
    rate = Decimal(str(pure_rate))
    if rate <= 0:
        raise ServiceError("A rate must be a number greater than zero.")
    old = metal.pure_rate
    if rate > old * 3 or rate < old / 3:
        raise ServiceError(
            f"{metal.code} would move from {old} to {rate} — more than three times. "
            "If that is right, set it in two steps."
        )
    metal.pure_rate = rate
    metal.rate_as_on = timezone.now()
    metal.save(update_fields=["pure_rate", "rate_as_on"])
    log(user, "UPDATE", "metal", metal.code, f"{old} -> {rate} per gram")
    return metal


def chart_rate(material_code, size_band="", side="COST", chart=None):
    """``app.chart_rate`` — the suggestion shown beside a rate box."""
    chart_id = chart.pk if isinstance(chart, RateChart) else chart
    if chart_id is None:
        default = RateChart.objects.filter(is_default=True).first()
        if default is None:
            return None
        chart_id = default.pk
    line = (
        RateChartLine.objects.filter(
            chart_id=chart_id,
            material__item_code=(material_code or "").strip().upper(),
            size_band=(size_band or "").strip(),
        )
        .only("cost_rate", "sale_rate")
        .first()
    )
    if line is None:
        return None
    return line.cost_rate if side.upper() == "COST" else line.sale_rate


# ── audit ────────────────────────────────────────────────────────────────
def log(user, action, table, pk, detail=None, **extra):
    return ActivityLog.objects.create(
        table_name=table,
        record_pk=str(pk),
        action=action,
        user=user if getattr(user, "is_authenticated", False) else None,
        detail=detail,
        **extra,
    )


def require(user, permission, message):
    if not (user and user.is_authenticated and user.has_perm(permission)):
        raise PermissionDenied(message)


# ── costing ──────────────────────────────────────────────────────────────
def _lines_for(piece_id, version_no):
    return list(
        BomLine.objects.filter(piece_id=piece_id, version_no=version_no)
        .select_related("material")
        .order_by("line_no")
    )


def net_metal_weight(piece_id, version_no):
    total = ZERO
    for line in _lines_for(piece_id, version_no):
        if line.material.mat_class == MaterialClass.METAL:
            total += line_weight_gm(line.qty_value, line.qty_uom)
    return total


@transaction.atomic
def recost_piece(piece, version_no=None, user=None):
    """``app.recost_jewel`` — re-derive every amount on one BOM version.

    Metal lines charged ``BY_NET_METAL_WT`` are first snapped to the piece's
    total metal weight; then each line's amount is its rate times its basis,
    rounded at ``line_rounding_dp``; then the version's totals are the sums,
    rounded at ``total_rounding_dp``. Same order as the SQL, because the order
    is what makes the paisa land in the same place.
    """
    piece = _as_piece(piece)
    version_no = version_no or piece.current_bom_version
    ldp, tdp = line_dp(), total_dp()
    metal_gm = net_metal_weight(piece.pk, version_no)

    lines = _lines_for(piece.pk, version_no)
    for line in lines:
        if line.basis == ChargeBasis.BY_NET_METAL_WT:
            line.qty_value = metal_gm
            line.qty_uom = "GM"
            base = metal_gm
        elif line.basis == ChargeBasis.BY_PIECE:
            base = Decimal(line.pcs or 0)
        elif line.basis == ChargeBasis.FLAT:
            base = Decimal(1)
        else:
            base = Decimal(line.qty_value or 0)
        line.cost_amount = round_to((line.cost_rate or ZERO) * base, ldp)
        line.sale_amount = round_to((line.sale_rate or ZERO) * base, ldp)
        line.save(update_fields=["qty_value", "qty_uom", "cost_amount", "sale_amount"])

    bom_weight = sum(
        (line_weight_gm(l.qty_value, l.qty_uom) for l in lines if l.material.mat_class != MaterialClass.LABOUR),
        ZERO,
    )
    version = BomVersion.objects.get(piece=piece, version_no=version_no)
    version.net_metal_wt_gm = metal_gm
    version.bom_weight_gm = bom_weight
    version.total_cost_price = round_to(sum((l.cost_amount or ZERO for l in lines), ZERO), tdp)
    version.total_sale_price = round_to(sum((l.sale_amount or ZERO for l in lines), ZERO), tdp)
    version.making_value = round_to(
        sum((l.sale_amount or ZERO for l in lines if l.material.mat_class == MaterialClass.LABOUR), ZERO), tdp
    )
    version.goods_value = round_to(
        sum((l.sale_amount or ZERO for l in lines if l.material.mat_class != MaterialClass.LABOUR), ZERO), tdp
    )
    version.save(
        update_fields=[
            "net_metal_wt_gm",
            "bom_weight_gm",
            "total_cost_price",
            "total_sale_price",
            "making_value",
            "goods_value",
        ]
    )
    return version


def _scenario_stone_rates(piece, scenario, lines):
    """The sale rate a scenario puts on each stone line.

    A chart scenario reads that chart line by line, so its total is exact. A
    value-added one only has a target for the stones as a whole, so it is
    spread across them in proportion to what they cost — the lines that carry
    the most cost carry the most of the markup.
    """
    stones = [
        line for line in lines if line.material.mat_class not in (MaterialClass.METAL, MaterialClass.LABOUR)
    ]
    if scenario.method == scenario.CHART:
        return {
            line.line_no: chart_rate(line.material.item_code, line.size_band, "SALE", scenario.chart_id)
            or line.sale_rate
            for line in stones
        }
    cost_total = sum(((l.cost_rate or ZERO) * Decimal(l.qty_value or 0) for l in stones), ZERO)
    if not cost_total:
        return {}
    stone_sale = scenario_price(piece, scenario).stone_sale
    rates = {}
    for line in stones:
        qty = Decimal(line.qty_value or 0)
        if not qty:
            continue
        share = ((line.cost_rate or ZERO) * qty) / cost_total
        rates[line.line_no] = stone_sale * share / qty
    return rates


def sale_lines(piece, version_no=None, scenario=None):
    """``app.live_sale_price``, itemised — every line's sale rate and amount.

    Metal always passes at the live alloy rate and making keeps the rate on its
    own line, so a scenario is the one argument that changes anything here: it
    moves the stone lines and nothing else.
    """
    piece = _as_piece(piece)
    version_no = version_no or piece.current_bom_version
    ldp = line_dp()
    metal_gm = net_metal_weight(piece.pk, version_no)
    metal_rate = alloy_sale_rate(piece.metal_purity)
    lines = _lines_for(piece.pk, version_no)
    stone_rates = _scenario_stone_rates(piece, scenario, lines) if scenario else {}
    priced = []
    for line in lines:
        rate = line.sale_rate
        if line.material.mat_class == MaterialClass.METAL:
            rate = metal_rate
            amount = rate * Decimal(line.qty_value or 0)
        elif line.basis == ChargeBasis.BY_NET_METAL_WT:
            amount = (rate or ZERO) * metal_gm
        elif line.basis == ChargeBasis.BY_PIECE:
            amount = (rate or ZERO) * Decimal(line.pcs or 0)
        elif line.basis == ChargeBasis.FLAT:
            amount = rate or ZERO
        else:
            rate = stone_rates.get(line.line_no, rate)
            amount = (rate or ZERO) * Decimal(line.qty_value or 0)
        priced.append({"line": line, "sale_rate": rate, "sale_amount": round_to(amount, ldp)})
    return priced


def live_sale_price(piece, version_no=None, scenario=None):
    """``app.live_sale_price`` — the frozen BOM, with metal at today's rate."""
    return sum((row["sale_amount"] for row in sale_lines(piece, version_no, scenario)), ZERO)


def current_cost(piece, version_no=None):
    """``app.current_cost`` — what an identical piece would cost to make today.

    Nothing about it is stored: it moves when the metal rate moves, which is
    the entire point. Quote off the frozen cost and the margin is a story about
    a metal price that no longer exists.
    """
    piece = _as_piece(piece)
    version_no = version_no or piece.current_bom_version
    ldp = line_dp()
    metal_gm = net_metal_weight(piece.pk, version_no)
    rate = alloy_cost_rate(piece.metal_purity)
    total = ZERO
    for line in _lines_for(piece.pk, version_no):
        if line.material.mat_class == MaterialClass.METAL:
            amount = rate * Decimal(line.qty_value or 0)
        elif line.basis == ChargeBasis.BY_NET_METAL_WT:
            amount = (line.cost_rate or ZERO) * metal_gm
        elif line.basis == ChargeBasis.BY_PIECE:
            amount = (line.cost_rate or ZERO) * Decimal(line.pcs or 0)
        elif line.basis == ChargeBasis.FLAT:
            amount = line.cost_rate or ZERO
        else:
            amount = (line.cost_rate or ZERO) * Decimal(line.qty_value or 0)
        total += round_to(amount, ldp)
    return total


@dataclass
class ScenarioPrice:
    scenario: str
    scenario_name: str
    method: str
    metal_gm: Decimal
    metal_cost: Decimal
    metal_sale: Decimal
    making_cost: Decimal
    making_sale: Decimal
    stone_cost: Decimal
    stone_sale: Decimal
    stone_multiple: Decimal | None
    cost_today: Decimal
    price: Decimal
    capped: str | None = None


def may_switch_to(user, scenario):
    """``app.set_piece_scenario``’s guard: ``may_switch``, not ``may_see``.

    The legacy let a role compare against a scenario it could not commit a
    piece to, so the two flags are separate and this reads the second.
    """
    if not (user and user.is_authenticated):
        return False
    return user.is_admin() or scenario.roles.filter(group__in=user.groups.all(), may_switch=True).exists()


def set_piece_scenario(user, piece, scenario=None):
    """``app.set_piece_scenario`` — put a piece on a scenario, or clear it.

    Clearing sends the piece back to the rates on its own lines, which is what
    it was quoted at before anyone opted in; only an admin may do that.
    """
    from .models import Scenario

    piece = _as_piece(piece)
    if scenario is None:
        if not (user and user.is_authenticated and user.is_admin()):
            raise PermissionDenied("Only an admin can clear a piece's scenario.")
        piece.scenario = None
        piece.save(update_fields=["scenario"])
        log(user, "UPDATE", "jewel_code", piece.pk, "scenario cleared — back to the piece's own lines")
        return None
    if not isinstance(scenario, Scenario):
        scenario = Scenario.objects.filter(pk=scenario, is_active=True).first()
    if scenario is None:
        raise ServiceError("No such scenario.")
    if not may_switch_to(user, scenario):
        raise PermissionDenied("You may see that scenario but not put a piece on it. Ask an admin.")
    piece.scenario = scenario
    piece.save(update_fields=["scenario"])
    log(user, "UPDATE", "jewel_code", piece.pk, f"priced on scenario {scenario.name}")
    return scenario


def scenario_price(piece, scenario=None):
    """``app.scenario_price`` — one scenario's asking price for one piece.

    Metal always passes through at its live rate; making is whatever the line
    says; only stones move. That rule is the model.
    """
    from .models import Scenario

    piece = _as_piece(piece)
    if scenario is None:
        scenario = piece.scenario or Scenario.objects.filter(is_default=True).first()
    elif not isinstance(scenario, Scenario):
        scenario = Scenario.objects.get(pk=scenario)
    if scenario is None:
        raise ServiceError("No pricing scenario is set up.")

    version_no = piece.current_bom_version
    lines = _lines_for(piece.pk, version_no)
    metal_gm = sum(
        (line_weight_gm(l.qty_value, l.qty_uom) for l in lines if l.material.mat_class == MaterialClass.METAL), ZERO
    )
    metal_sale = round_to(alloy_sale_rate(piece.metal_purity) * metal_gm, 0)
    metal_cost = round_to(alloy_cost_rate(piece.metal_purity) * metal_gm, 0)

    making_sale = making_cost = ZERO
    for line in (l for l in lines if l.material.mat_class == MaterialClass.LABOUR):
        if line.basis == ChargeBasis.FLAT:
            making_sale += line.sale_rate or ZERO
            making_cost += line.cost_rate or ZERO
        elif line.basis == ChargeBasis.BY_PIECE:
            making_sale += (line.sale_rate or ZERO) * Decimal(line.pcs or 1)
            making_cost += (line.cost_rate or ZERO) * Decimal(line.pcs or 1)
        else:
            making_sale += (line.sale_rate or ZERO) * metal_gm
            making_cost += (line.cost_rate or ZERO) * metal_gm

    stone_cost = stone_chart = ZERO
    for line in lines:
        if line.material.mat_class in (MaterialClass.METAL, MaterialClass.LABOUR):
            continue
        qty = Decimal(line.qty_value or 0)
        stone_cost += (line.cost_rate or ZERO) * qty
        rate = chart_rate(line.material.item_code, line.size_band, "SALE", scenario.chart_id)
        stone_chart += (rate if rate is not None else (line.sale_rate or ZERO)) * qty

    capped = None
    if scenario.method == scenario.CHART:
        stone_sale = stone_chart
    else:
        # value added = everything except metal. Target a markup on that, and
        # let the stones carry whatever is left after making.
        va_cost = stone_cost + making_cost
        stone_sale = va_cost * (1 + (scenario.target_pct or ZERO) / Decimal(100)) - making_sale
        if stone_cost > 0:
            multiple = stone_sale / stone_cost
            if multiple < scenario.min_multiple:
                stone_sale = stone_cost * scenario.min_multiple
                capped = "floor"
            elif multiple > scenario.max_multiple:
                stone_sale = stone_cost * scenario.max_multiple
                capped = "ceiling"
        elif stone_sale > 0:
            stone_sale = ZERO
            capped = "no stones"

    return ScenarioPrice(
        scenario=scenario.code,
        scenario_name=scenario.name,
        method=scenario.method,
        metal_gm=round_to(metal_gm, 3),
        metal_cost=metal_cost,
        metal_sale=metal_sale,
        making_cost=round_to(making_cost, 0),
        making_sale=round_to(making_sale, 0),
        stone_cost=round_to(stone_cost, 0),
        stone_sale=round_to(stone_sale, 0),
        stone_multiple=round_to(stone_sale / stone_cost, 2) if stone_cost > 0 else None,
        cost_today=metal_cost + round_to(making_cost, 0) + round_to(stone_cost, 0),
        price=metal_sale + round_to(making_sale, 0) + round_to(stone_sale, 0),
        capped=capped,
    )


def piece_gaps(piece):
    """``app.piece_gaps`` — what is still missing before this piece is complete."""
    piece = _as_piece(piece)
    gaps = []
    if not piece.metal_purity:
        gaps.append("karat")
    if piece.measured_gross_wt_gm is None:
        gaps.append("gross_weight")
    if piece.location_id is None and piece.stock_state == StockState.NOT_RECEIVED:
        gaps.append("location")
    version = piece.current_bom()
    if version is None or not BomLine.objects.filter(piece=piece, version_no=piece.current_bom_version).exists():
        gaps.append("bom")
    else:
        if BomLine.objects.filter(
            piece=piece, version_no=piece.current_bom_version
        ).filter(Q(cost_rate__isnull=True) | Q(cost_rate=0)).exists():
            gaps.append("cost_rates")
        if BomLine.objects.filter(
            piece=piece, version_no=piece.current_bom_version
        ).filter(Q(sale_rate__isnull=True) | Q(sale_rate=0)).exists():
            gaps.append("sale_rates")
    if piece.huid is None and piece.stock_state in COUNTABLE_STATES:
        gaps.append("huid")
    return gaps


def weight_reconciliation(piece):
    """``vw_weight_reconciliation`` for one piece."""
    piece = _as_piece(piece)
    version = piece.current_bom()
    if version is None or piece.measured_gross_wt_gm is None or version.bom_weight_gm is None:
        return None
    diff = round_to(piece.measured_gross_wt_gm - version.bom_weight_gm, 3)
    tolerance = setting_num("gross_wt_tolerance_gm", "0.05")
    return {"diff_gm": diff, "out_of_tolerance": abs(diff) > tolerance}


# ── the ledger ───────────────────────────────────────────────────────────
def _as_piece(piece):
    if isinstance(piece, Piece):
        return piece
    if isinstance(piece, int):
        return Piece.objects.get(pk=piece)
    return Piece.objects.get(jewel_code=str(piece).strip().upper())


@transaction.atomic
def record_movement(
    user,
    piece,
    move_type,
    resulting_state,
    from_location=None,
    to_location=None,
    reason=None,
    reference_no=None,
    party_name=None,
    moved_at=None,
):
    """``trg_apply_movement``, as an explicit service.

    The ledger row is written and the piece row follows from it, under
    ``select_for_update`` — two counters scanning the same piece cannot both
    win. A terminal piece is refused: its record is history now.
    """
    piece = Piece.objects.select_for_update().get(pk=_as_piece(piece).pk)
    if piece.stock_state in TERMINAL_STATES:
        raise ServiceError(
            f"Jewel code {piece.jewel_code} is {piece.stock_state} — terminal, cannot move it. "
            "Create a new jewel code."
        )
    if to_location is not None and not user.can_see_location(_location_id(to_location)):
        raise PermissionDenied("You cannot move a piece into a location you cannot see.")

    moved_at = moved_at or timezone.now()
    movement = StockMovement.objects.create(
        piece=piece,
        move_type=move_type,
        from_location_id=_location_id(from_location) if from_location else piece.location_id,
        to_location_id=_location_id(to_location) if to_location else None,
        resulting_state=resulting_state,
        moved_at=moved_at,
        reason=reason,
        reference_no=reference_no,
        party_name=party_name,
        user=user if getattr(user, "is_authenticated", False) else None,
    )

    terminal = resulting_state in TERMINAL_STATES
    piece.stock_state = resulting_state
    piece.location_id = None if terminal else (movement.to_location_id or piece.location_id)
    if move_type == MovementType.RECEIPT and piece.received_on is None:
        piece.received_on = moved_at.date()
    if terminal:
        piece.disposed_on = moved_at.date()
    piece.updated_at = timezone.now()
    piece.save(update_fields=["stock_state", "location_id", "received_on", "disposed_on", "updated_at"])
    return movement


def _location_id(location):
    if location is None:
        return None
    if isinstance(location, Location):
        return location.pk
    if isinstance(location, int):
        return location
    key = str(location).strip()
    found = Location.objects.filter(Q(code__iexact=key) | Q(name__iexact=key)).first()
    if found is None:
        raise ServiceError(f'Location "{location}" not found.')
    return found.pk


def receive_piece(user, piece, location, reference_no=None, moved_at=None):
    """``api.receive_piece`` — a piece arrives on a shelf for the first time."""
    require(user, EDIT_BOM, "You do not have permission to receive stock.")
    return record_movement(
        user,
        piece,
        MovementType.RECEIPT,
        StockState.IN_STOCK,
        to_location=location,
        reference_no=reference_no,
        moved_at=moved_at,
    )


def transfer_piece(user, piece, to_location, reference_no=None):
    require(user, ADJUST_STOCK, "You do not have permission to move stock.")
    piece = _as_piece(piece)
    return record_movement(
        user,
        piece,
        MovementType.TRANSFER_IN,
        StockState.IN_STOCK,
        from_location=piece.location_id,
        to_location=to_location,
        reference_no=reference_no,
    )


def reserve_piece(user, piece, party_name=None):
    require(user, ADJUST_STOCK, "You do not have permission to reserve stock.")
    piece = _as_piece(piece)
    return record_movement(
        user, piece, MovementType.RESERVE, StockState.RESERVED, to_location=piece.location_id, party_name=party_name
    )


def unreserve_piece(user, piece):
    require(user, ADJUST_STOCK, "You do not have permission to reserve stock.")
    piece = _as_piece(piece)
    return record_movement(user, piece, MovementType.UNRESERVE, StockState.IN_STOCK, to_location=piece.location_id)


@transaction.atomic
def sell_piece(
    user,
    piece,
    sold_price,
    sold_on=None,
    discount_amt=ZERO,
    customer_name=None,
    customer_phone=None,
    customer=None,
    location=None,
    salesperson=None,
):
    """Record a sale and close the piece in one transaction.

    ``cost_at_sale`` is the frozen BOM cost, not today's — the margin on a sale
    is what the piece actually cost, forever.
    """
    require(user, ADJUST_STOCK, "You do not have permission to record a sale.")
    piece = Piece.objects.select_for_update().get(pk=_as_piece(piece).pk)
    if piece.stock_state in TERMINAL_STATES:
        raise ServiceError(f"Jewel code {piece.jewel_code} is already {piece.stock_state}.")
    if Sale.objects.filter(piece=piece).exists():
        raise ServiceError(f"Jewel code {piece.jewel_code} has already been sold.")

    version = piece.current_bom()
    sale = Sale.objects.create(
        piece=piece,
        bom_version_at_sale=piece.current_bom_version,
        sold_on=sold_on or timezone.localdate(),
        location_id=_location_id(location) if location else piece.location_id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer=customer,
        salesperson=salesperson or (user if getattr(user, "is_authenticated", False) else None),
        sold_price=Decimal(str(sold_price)),
        discount_amt=Decimal(str(discount_amt or 0)),
        cost_at_sale=(version.total_cost_price if version else ZERO) or ZERO,
        source=Sale.STOCK,
    )
    record_movement(user, piece, MovementType.SALE, StockState.SOLD, from_location=piece.location_id, reason="Sale")
    log(user, "SALE", "sale", sale.pk, f"{piece.jewel_code} at {sale.sold_price}")
    return sale


@transaction.atomic
def melt_piece(user, piece, reason):
    """``app.melt_jewel`` — capability *and* a reason of at least ten characters."""
    if not (user and user.is_authenticated and user.has_perm(MELT)):
        raise PermissionDenied("You are not authorised to melt. Admin only.")
    if not reason or len(reason.strip()) < 10:
        raise ServiceError("A melt reason of at least 10 characters is required.")
    piece = Piece.objects.select_for_update().get(pk=_as_piece(piece).pk)
    if piece.stock_state in TERMINAL_STATES:
        raise ServiceError(f"Cannot melt: jewel code is already {piece.stock_state}.")

    version = piece.current_bom()
    record = MeltRecord.objects.create(
        piece=piece,
        bom_version_at_melt=piece.current_bom_version,
        melted_on=timezone.localdate(),
        location_id=piece.location_id,
        reason=reason.strip(),
        cost_written_off=version.total_cost_price if version else None,
        authorised_by=user,
    )
    record_movement(user, piece, MovementType.MELT, StockState.MELTED, from_location=piece.location_id, reason=reason)
    log(user, "MELT", "melt_record", record.pk, f"{piece.jewel_code}: {reason.strip()[:120]}")
    return record


# ── BOM ──────────────────────────────────────────────────────────────────
@transaction.atomic
def set_bom(user, piece, lines, reason=BomChangeReason.CORRECTION, note=None):
    """Replace the current version's lines and recost.

    ``lines`` is a list of dicts: ``material`` (code or Material), ``qty_value``,
    ``qty_uom``, ``basis``, ``pcs``, ``cost_rate``, ``sale_rate``, ``size_band``.
    """
    require(user, EDIT_BOM, "You do not have permission to change a bill of materials.")
    from .models import Material

    piece = _as_piece(piece)
    if piece.stock_state in TERMINAL_STATES:
        raise ServiceError(f"Jewel code {piece.jewel_code} is closed. Its record is history now.")

    version = piece.current_bom()
    if version is None:
        version = BomVersion.objects.create(
            piece=piece, version_no=piece.current_bom_version, reason=reason, note=note, created_by=user
        )
    BomLine.objects.filter(piece=piece, version_no=version.version_no).delete()

    for index, raw in enumerate(lines, start=1):
        material = raw["material"]
        if not isinstance(material, Material):
            material = Material.objects.get(item_code=str(material).strip().upper())
        uom = raw.get("qty_uom") or material.default_uom
        _check_line_uom(material, uom, index)
        BomLine.objects.create(
            piece=piece,
            version_no=version.version_no,
            line_no=index,
            material=material,
            size_band=raw.get("size_band", "") or "",
            pcs=raw.get("pcs"),
            qty_value=_decimal(raw.get("qty_value")),
            qty_uom=uom,
            basis=raw.get("basis", ChargeBasis.BY_QTY),
            cost_rate=_decimal(raw.get("cost_rate")),
            sale_rate=_decimal(raw.get("sale_rate")),
            off_chart=bool(raw.get("off_chart", False)),
            remarks=raw.get("remarks"),
        )
    recost_piece(piece, version.version_no, user)
    log(user, "UPDATE", "jewel_material_line", piece.jewel_code, f"{len(lines)} lines")
    return version


def _check_line_uom(material, uom, line_no):
    """``trg_check_line_uom`` — metal is grams, diamonds are carats or pieces."""
    if material.mat_class == MaterialClass.METAL and uom != "GM":
        raise ServiceError(f"Metal line {line_no} must be GM, got {uom}")
    if material.mat_class in (MaterialClass.DIAMOND, MaterialClass.POLKI) and uom not in ("CT", "PCS"):
        raise ServiceError(f"Diamond/Polki line {line_no} must be CT or PCS, got {uom}")


def _decimal(value):
    if value is None or value == "":
        return None
    return Decimal(str(value))


@transaction.atomic
def refresh_bom_rates(user, piece, chart=None, side="BOTH"):
    """``api.refresh_bom_rates`` — repull chart rates onto a piece's lines.

    A line marked ``off_chart`` is left alone: it carries a deliberate rate.
    """
    require(user, EDIT_BOM, "You do not have permission to change a bill of materials.")
    piece = _as_piece(piece)
    touched = 0
    for line in _lines_for(piece.pk, piece.current_bom_version):
        if line.off_chart or line.material.mat_class == MaterialClass.METAL:
            continue
        fields = []
        if side in ("BOTH", "COST"):
            rate = chart_rate(line.material.item_code, line.size_band, "COST", chart)
            if rate is not None and rate != line.cost_rate:
                line.cost_rate = rate
                fields.append("cost_rate")
        if side in ("BOTH", "SALE"):
            rate = chart_rate(line.material.item_code, line.size_band, "SALE", chart)
            if rate is not None and rate != line.sale_rate:
                line.sale_rate = rate
                fields.append("sale_rate")
        if fields:
            line.save(update_fields=fields)
            touched += 1
    recost_piece(piece, piece.current_bom_version, user)
    return touched


@transaction.atomic
def new_bom_version(user, piece, reason, note=None, repair_job=None):
    """Copy the current version into a new one and make that current."""
    piece = _as_piece(piece)
    previous = piece.current_bom()
    next_no = (BomVersion.objects.filter(piece=piece).aggregate(top=Max("version_no"))["top"] or 0) + 1
    BomVersion.objects.filter(piece=piece, is_current=True).update(is_current=False)
    version = BomVersion.objects.create(
        piece=piece,
        version_no=next_no,
        reason=reason,
        note=note,
        repair_job=repair_job,
        cost_rate_card=previous.cost_rate_card if previous else None,
        sale_rate_card=previous.sale_rate_card if previous else None,
        is_current=True,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    if previous:
        for line in _lines_for(piece.pk, previous.version_no):
            BomLine.objects.create(
                piece=piece,
                version_no=next_no,
                line_no=line.line_no,
                material=line.material,
                size_band=line.size_band,
                pcs=line.pcs,
                qty_value=line.qty_value,
                qty_uom=line.qty_uom,
                basis=line.basis,
                cost_rate=line.cost_rate,
                sale_rate=line.sale_rate,
                off_chart=line.off_chart,
                remarks=line.remarks,
            )
    piece.current_bom_version = next_no
    piece.updated_at = timezone.now()
    piece.save(update_fields=["current_bom_version", "updated_at"])
    return version


# ── repairs ──────────────────────────────────────────────────────────────
@transaction.atomic
def open_repair(user, piece, fault_description, job_no=None, vendor=None, return_location=None):
    require(user, EDIT_BOM, "You do not have permission to open a repair.")
    piece = _as_piece(piece)
    if piece.stock_state in TERMINAL_STATES:
        raise ServiceError(f"Jewel code {piece.jewel_code} is {piece.stock_state}.")
    job_no = job_no or _next_job_no()
    job = RepairJob.objects.create(
        job_no=job_no,
        piece=piece,
        from_bom_version=piece.current_bom_version,
        opened_on=timezone.localdate(),
        vendor=vendor,
        return_location=return_location or piece.location,
        fault_description=fault_description,
        opened_by=user,
    )
    record_movement(
        user,
        piece,
        MovementType.REPAIR_OUT,
        StockState.IN_REPAIR,
        from_location=piece.location_id,
        to_location=piece.location_id,
        reason="Repair opened",
        reference_no=job_no,
    )
    log(user, "REPAIR", "repair_job", job.pk, f"{piece.jewel_code} opened")
    return job


def _next_job_no():
    last = RepairJob.objects.order_by("-repair_job_id").first()
    return f"RJ{(last.repair_job_id + 1) if last else 1:06d}"


@transaction.atomic
def complete_repair(user, job):
    """``app.complete_repair`` — apply the material changes onto a new version.

    Removals subtract and delete an emptied line; additions add to a matching
    line or open a new one. The piece then comes home to wherever it left from.
    """
    require(user, EDIT_BOM, "You do not have permission to close a repair.")
    if not isinstance(job, RepairJob):
        job = RepairJob.objects.get(pk=job)
    if job.status == RepairJob.DONE:
        raise ServiceError(f"Repair job {job.job_no} is already closed.")

    piece = job.piece
    version = new_bom_version(
        user, piece, BomChangeReason.REPAIR, note=f"Auto-created by repair job {job.job_no}", repair_job=job
    )

    for change in job.changes.filter(action="REMOVE").select_related("material"):
        line = BomLine.objects.filter(
            piece=piece, version_no=version.version_no, material=change.material, size_band=change.size_band
        ).first()
        if line is None:
            continue
        line.qty_value = (line.qty_value or ZERO) - (change.qty_value or ZERO)
        line.pcs = (line.pcs or 0) - (change.pcs or 0)
        if (line.qty_value or ZERO) <= 0 and (line.pcs or 0) <= 0:
            line.delete()
        else:
            line.save(update_fields=["qty_value", "pcs"])

    for change in job.changes.filter(action="ADD").select_related("material"):
        line = BomLine.objects.filter(
            piece=piece, version_no=version.version_no, material=change.material, size_band=change.size_band
        ).first()
        if line is not None:
            line.qty_value = (line.qty_value or ZERO) + (change.qty_value or ZERO)
            line.pcs = (line.pcs or 0) + (change.pcs or 0)
            line.cost_rate = change.cost_rate if change.cost_rate is not None else line.cost_rate
            line.sale_rate = change.sale_rate if change.sale_rate is not None else line.sale_rate
            line.save(update_fields=["qty_value", "pcs", "cost_rate", "sale_rate"])
        else:
            next_line_no = (
                BomLine.objects.filter(piece=piece, version_no=version.version_no).aggregate(top=Max("line_no"))["top"]
                or 0
            ) + 1
            BomLine.objects.create(
                piece=piece,
                version_no=version.version_no,
                line_no=next_line_no,
                material=change.material,
                size_band=change.size_band,
                pcs=change.pcs,
                qty_value=change.qty_value,
                qty_uom=change.qty_uom,
                basis=ChargeBasis.BY_QTY,
                cost_rate=change.cost_rate,
                sale_rate=change.sale_rate,
                remarks="Added by repair",
            )

    recost_piece(piece, version.version_no, user)
    job.status = RepairJob.DONE
    job.to_bom_version = version.version_no
    job.closed_on = timezone.localdate()
    job.closed_by = user
    job.save(update_fields=["status", "to_bom_version", "closed_on", "closed_by"])

    home = (
        StockMovement.objects.filter(piece=piece, move_type=MovementType.REPAIR_OUT)
        .order_by("-movement_id")
        .values_list("from_location_id", flat=True)
        .first()
    )
    record_movement(
        user,
        piece,
        MovementType.REPAIR_IN,
        StockState.IN_STOCK,
        from_location=piece.location_id,
        to_location=home or job.return_location_id or piece.location_id,
        reason="Repair completed",
        reference_no=job.job_no,
    )
    log(user, "REPAIR", "repair_job", job.pk, f"{piece.jewel_code} closed at v{version.version_no}")
    return version.version_no


# ── stock count ──────────────────────────────────────────────────────────
SCAN_SUFFIX = re.compile(r"\s+")


def normalise_scan(raw):
    """Barcode scanners append suffixes; take the part before a double underscore."""
    code = (raw or "").strip().split("__", 1)[0].upper()
    return SCAN_SUFFIX.sub("", code)


@transaction.atomic
def open_count(user, location):
    """``app.open_count`` — resume the open count at this location, or start one."""
    require(user, EDIT_BOM, "You do not have permission to run a stock count.")
    location_id = _location_id(location)
    if not user.can_see_location(location_id):
        raise PermissionDenied("You cannot count that location.")
    existing = StockCount.objects.filter(location_id=location_id, status=StockCount.OPEN).first()
    if existing:
        return existing
    location_obj = Location.objects.get(pk=location_id)
    ref = f"SC-{timezone.localdate():%y%m%d}-{location_obj.code}"
    if StockCount.objects.filter(count_ref=ref).exists():
        ref = f"{ref}-{StockCount.objects.filter(count_ref__startswith=ref).count() + 1}"
    count = StockCount.objects.create(count_ref=ref, location_id=location_id, status=StockCount.OPEN, counted_by=user)
    log(user, "INSERT", "stock_count", ref, f"Count opened at {location_obj.code}")
    return count


def _verdict_for(piece, count_location_id):
    if piece.location_id == count_location_id and piece.stock_state in COUNTABLE_STATES:
        return StockCountScan.FOUND, None
    if piece.stock_state not in COUNTABLE_STATES:
        return StockCountScan.NOT_STOCK, f"books say {piece.get_stock_state_display().lower()}"
    return StockCountScan.ELSEWHERE, f"books say {piece.location.code if piece.location else 'no location'}"


@transaction.atomic
def scan_piece(user, count, code):
    """``app.scan_piece`` — one code into an open count, idempotent per piece."""
    require(user, EDIT_BOM, "You do not have permission to run a stock count.")
    count = count if isinstance(count, StockCount) else StockCount.objects.get(pk=count)
    if count.status != StockCount.OPEN:
        raise ServiceError(f"That count is already {count.status.lower()}.")
    jewel_code = normalise_scan(code)
    if not jewel_code:
        raise ServiceError("Nothing scanned.")

    piece = Piece.objects.select_related("location").filter(jewel_code__iexact=jewel_code).first()
    if piece is None:
        return {"verdict": "UNKNOWN", "code": jewel_code, "note": "no such piece in the system"}

    verdict, note = _verdict_for(piece, count.location_id)
    _, created = StockCountScan.objects.get_or_create(
        count=count, piece=piece, defaults={"scanned_by": user, "verdict": verdict}
    )
    return {
        "verdict": verdict if created else "ALREADY",
        "first_verdict": verdict,
        "code": piece.jewel_code,
        "note": note if created else "already scanned in this count",
    }


@transaction.atomic
def unscan_piece(user, count, code):
    require(user, EDIT_BOM, "You do not have permission to run a stock count.")
    count = count if isinstance(count, StockCount) else StockCount.objects.get(pk=count)
    if count.status != StockCount.OPEN:
        raise ServiceError(f"That count is already {count.status.lower()}.")
    StockCountScan.objects.filter(count=count, piece__jewel_code__iexact=normalise_scan(code)).delete()
    return count_state(user, count)


def count_state(user, count):
    """``app.count_state`` — live figures for an open count, frozen for a closed one."""
    count = count if isinstance(count, StockCount) else StockCount.objects.get(pk=count)
    if not user.can_see_location(count.location_id):
        raise PermissionDenied("You cannot see that count.")
    if count.status != StockCount.OPEN and count.result:
        return count.result

    expected = set(
        Piece.objects.filter(location_id=count.location_id, stock_state__in=list(COUNTABLE_STATES)).values_list(
            "pk", flat=True
        )
    )
    scans = list(count.scans.select_related("piece", "piece__location").order_by("-scanned_at"))
    scanned_ids = {scan.piece_id for scan in scans}

    def described(scan):
        verdict, note = _verdict_for(scan.piece, count.location_id)
        if scan.piece_id in expected:
            verdict, note = StockCountScan.FOUND, None
        return {"code": scan.piece.jewel_code, "at": scan.scanned_at.isoformat(), "verdict": verdict, "note": note}

    missing = sorted(
        Piece.objects.filter(pk__in=expected - scanned_ids).values_list("jewel_code", flat=True)
    )
    unexpected = [described(scan) for scan in scans if scan.piece_id not in expected]
    return {
        "count_id": count.pk,
        "count_ref": count.count_ref,
        "status": count.status,
        "location_id": count.location_id,
        "location": count.location.code,
        "location_name": count.location.name,
        "started_at": count.started_at.isoformat(),
        "closed_at": count.closed_at.isoformat() if count.closed_at else None,
        "counted_by": str(count.counted_by) if count.counted_by else None,
        "expected": len(expected),
        "found": len(expected & scanned_ids),
        "unexpected": len(unexpected),
        "missing": len(expected - scanned_ids),
        "scanned": len(scans),
        "recent": [described(scan) for scan in scans[:12]],
        "missing_list": missing,
        "unexpected_list": sorted(unexpected, key=lambda row: row["code"]),
    }


@transaction.atomic
def close_count(user, count, cancel=False, notes=None):
    """``app.close_count`` — freeze the result; a closed count never recomputes."""
    require(user, EDIT_BOM, "You do not have permission to run a stock count.")
    count = count if isinstance(count, StockCount) else StockCount.objects.get(pk=count)
    if count.status != StockCount.OPEN:
        raise ServiceError(f"That count is already {count.status.lower()}.")
    if cancel:
        count.status = StockCount.CANCELLED
        count.closed_at = timezone.now()
        count.save(update_fields=["status", "closed_at"])
        log(user, "UPDATE", "stock_count", count.count_ref, "Count cancelled")
        return {"cancelled": True, "count_ref": count.count_ref}

    result = count_state(user, count)
    closed_at = timezone.now()
    result |= {"status": StockCount.CLOSED, "closed_at": closed_at.isoformat()}
    count.status = StockCount.CLOSED
    count.closed_at = closed_at
    count.result = result
    if notes:
        count.notes = notes
    count.save(update_fields=["status", "closed_at", "result", "notes"])
    log(
        user,
        "UPDATE",
        "stock_count",
        count.count_ref,
        f"Count closed: {result['found']} of {result['expected']} found, "
        f"{result['missing']} missing, {result['unexpected']} unexpected",
    )
    return result


# ── reporting ────────────────────────────────────────────────────────────
def stock_summary(user):
    """Pieces and carried cost per location, scoped to what the user may see."""
    rows = (
        Piece.objects.visible_to(user)
        .filter(stock_state__in=list(COUNTABLE_STATES))
        .values("location__code", "location__name")
        .annotate(pieces=Count("pk"))
        .order_by("location__code")
    )
    return list(rows)


def should_make(user):
    """``vw_should_make`` — styles below their minimum stock level."""
    from .models import Style

    return [
        {
            "style_code": style.style_code,
            "name": style.name,
            "nos_min_qty": style.nos_min_qty,
            "live_pieces": live,
            "shortfall": style.nos_min_qty - live,
        }
        for style in Style.objects.filter(is_active=True)
        if (live := style.pieces.filter(stock_state=StockState.IN_STOCK).count()) < style.nos_min_qty
    ]
