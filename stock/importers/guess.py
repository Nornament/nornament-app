"""Filling in a material the sheet mentions but the register has never seen.

127 of the 224 codes in the first real file were new. Asking a human to type
category, unit and metal for each of those is how an import stops happening,
so the band a code appeared in does the work: it already says what kind of
thing the code is. What the band cannot answer — a metal purity that does not
exist in the table — is returned as a problem rather than a guess, because a
wrong purity silently misprices every piece that uses it.
"""
import re

from stock.enums import ChargeBasis, Uom

#: band -> the material category a code in that band belongs to
BAND_CATEGORY = {
    "diamond": "DIAMOND",
    "metal": "METAL",
    "stone": "SETTING",
    "other": "OTHER",
    "charge": "LABOUR",
}

#: band -> the unit its quantities are written in
BAND_UOM = {
    "diamond": Uom.CT,
    "metal": Uom.GM,
    "stone": Uom.CT,
    "other": Uom.GM,
    "charge": Uom.PCS,
}

#: codes in the diamond band that are polki, not diamond
POLKI_PREFIXES = ("FPL", "PL")

METAL_BY_PREFIX = {"G": "GOLD", "S": "SILVER"}


def _category_for(line):
    if line.band == "diamond" and line.code.upper().startswith(POLKI_PREFIXES):
        return "POLKI"
    return BAND_CATEGORY[line.band]


def _minted_code(line):
    """The BI–BR band carries a name and no code, so we mint a stable one."""
    slug = re.sub(r"[^A-Z0-9]+", "-", line.code.upper()).strip("-")
    return f"OTH-{slug}"


def _metal_fields(line):
    """Metal, purity and the karat it was read from — or a reason we cannot."""
    from stock.models import MetalPurity

    code = line.code.upper()
    metal_id = METAL_BY_PREFIX.get(code[0]) if code else None
    if metal_id is None:
        return None, None, (
            f"{line.code!r} does not start with G or S, so its metal cannot be read. "
            "Pick the metal and purity by hand."
        )
    karat = re.search(r"(\d+K|\d{3})", line.name.upper() or code)
    if karat is None:
        return None, None, f"No karat or fineness in {line.name or line.code!r}."
    karat = karat.group(1)
    purity = MetalPurity.objects.filter(pk=karat).first()
    if purity is None:
        return None, None, (
            f"Purity {karat!r} is not in the purity table. Create it, or point "
            f"{line.code!r} at an existing purity."
        )
    return metal_id, purity, None


def material_fields(line):
    """``(kwargs for Material, problem)``. A problem blocks the import."""
    category = _category_for(line)
    fields = {
        "item_code": _minted_code(line) if line.band == "other" else line.code.upper(),
        "item_name": line.name or line.code,
        "category_id": category,
        "default_uom": BAND_UOM[line.band],
    }
    if category == "METAL":
        metal_id, purity, problem = _metal_fields(line)
        if problem:
            return fields, problem
        fields["metal_id"] = metal_id
        fields["purity_factor"] = purity.true_fineness
    return fields, None


def bom_basis_and_uom(line, material_category):
    """How a BOM line off this sheet is charged.

    Metal is BY_QTY on the sheet's own net weight, never BY_NET_METAL_WT:
    recosting snaps every BY_NET_METAL_WT line to the piece's *total* metal
    weight, which would double-count a piece carrying two metal lines.
    Charges are FLAT, where the base is 1 and the rate is the amount.
    """
    if material_category == "LABOUR":
        return ChargeBasis.FLAT, Uom.PCS
    if material_category == "METAL":
        return ChargeBasis.BY_QTY, Uom.GM
    uom = Uom.CT if material_category in ("DIAMOND", "POLKI") else BAND_UOM.get(line.band, Uom.CT)
    return _priced_basis(line), uom


def _priced_basis(line):
    """Whether this line is charged per piece or per carat, per IVY's own sum.

    The export mixes the two even inside one band: a 168-piece cubic zirconia
    line prices at 168 x 120, while a diamond line beside it prices on weight.
    Nothing in the row declares which, so the amount column arbitrates —
    whichever base reproduces the amount IVY already computed is the base IVY
    used. Ties and unusable rows stay on weight, the commoner case.
    """
    amount = line.cost_amount if line.cost_amount is not None else line.sale_amount
    rate = line.cost_rate if line.cost_amount is not None else line.sale_rate
    if not amount or not rate or not line.pcs or line.qty is None:
        return ChargeBasis.BY_QTY
    by_piece = abs(line.pcs * rate - amount)
    by_weight = abs(line.qty * rate - amount)
    return ChargeBasis.BY_PIECE if by_piece < by_weight else ChargeBasis.BY_QTY
