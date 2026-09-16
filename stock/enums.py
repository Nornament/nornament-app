"""The Postgres enums of schema ``app``, as Django choices.

Values are the enum labels verbatim — the ETL copies them across untouched and
every ported message ("books say in repair") formats from them the same way.
"""
from django.db import models


class Uom(models.TextChoices):
    CT = "CT", "Carat"
    GM = "GM", "Gram"
    RATTI = "RATTI", "Ratti"
    PCS = "PCS", "Pieces"


#: app.uom_conversion, seeded in migration 0001a
GRAMS_PER_UNIT = {"GM": "1.0", "CT": "0.2", "RATTI": "0.1215", "PCS": "0.0"}


class ChargeBasis(models.TextChoices):
    BY_QTY = "BY_QTY", "By quantity"
    BY_NET_METAL_WT = "BY_NET_METAL_WT", "By net metal weight"
    BY_GROSS_WT = "BY_GROSS_WT", "By gross weight"
    BY_PIECE = "BY_PIECE", "By piece"
    FLAT = "FLAT", "Flat"


class DesignState(models.TextChoices):
    SKETCH = "SKETCH", "Sketch"
    DESIGN_INSPIRATION = "DESIGN_INSPIRATION", "Design inspiration"
    RENDERING = "RENDERING", "Rendering"
    CAD = "CAD", "CAD"
    IN_STOCK_DESIGN = "IN_STOCK_DESIGN", "In stock"
    OUT_OF_STOCK_DESIGN = "OUT_OF_STOCK_DESIGN", "Out of stock"
    DISCONTINUED = "DISCONTINUED", "Discontinued"


class MediaKind(models.TextChoices):
    PHOTO = "PHOTO", "Photo"
    VIDEO = "VIDEO", "Video"
    CAD = "CAD", "CAD"
    PENCIL_DRAWING = "PENCIL_DRAWING", "Pencil drawing"
    RENDER = "RENDER", "Render"
    CERTIFICATE_SCAN = "CERTIFICATE_SCAN", "Certificate scan"
    JOB_CARD_SCAN = "JOB_CARD_SCAN", "Job card scan"
    GRAPH = "GRAPH", "Graph"
    DOCUMENT = "DOCUMENT", "Document"
    SELL_VIDEO = "SELL_VIDEO", "Sell video"


#: The legacy app's ``MEDIA_KINDS`` (nornament.html), unchanged in order and
#: wording. A photograph and a CAD file are not the same thing and never share
#: a grid: each kind is its own section, and ``on`` says whether the file
#: belongs to the one physical piece or to the design every piece of it shares.
MEDIA_SECTIONS = [
    {
        "kind": MediaKind.PHOTO,
        "label": "Photographs",
        "on": "piece",
        "icon": "\u25a3",
        "accept": ".jpg,.jpeg,.png,.heic,.heif,.webp,.tif,.tiff",
        "note": "JPEG, PNG, HEIC or TIFF. The original is kept untouched.",
    },
    {
        "kind": MediaKind.VIDEO,
        "label": "Video",
        "on": "piece",
        "icon": "\u25b6",
        "accept": ".mp4,.mov,.m4v,.webm",
        "note": "MP4 or MOV. A slow turn on a plain background sells better than a clip.",
    },
    {
        "kind": MediaKind.RENDER,
        "label": "Renders",
        "on": "piece",
        "icon": "\u25c8",
        "accept": ".jpg,.jpeg,.png,.webp,.tif,.tiff",
        "note": "Output from CAD, before the piece exists.",
    },
    {
        "kind": MediaKind.GRAPH,
        "label": "Graph",
        "on": "design",
        "icon": "\u25a6",
        "accept": ".jpg,.jpeg,.png,.pdf,.tif,.tiff",
        "note": "The setting layout the karigar works from \u2014 stone placement on graph paper.",
    },
    {
        "kind": MediaKind.CAD,
        "label": "CAD / 3DM",
        "on": "design",
        "icon": "\u25e7",
        "accept": ".3dm,.stl,.obj,.step,.stp,.iges,.igs,.zip,.rar,.dwg,.dxf",
        "note": "Rhino, Matrix and the like. Full size \u2014 the bucket takes them whole.",
    },
    {
        "kind": MediaKind.PENCIL_DRAWING,
        "label": "Pencil drawing",
        "on": "design",
        "icon": "\u270e",
        "accept": ".jpg,.jpeg,.png,.pdf,.heic,.tif,.tiff",
        "note": "The original sketch.",
    },
    {
        "kind": MediaKind.CERTIFICATE_SCAN,
        "label": "Certificate",
        "on": "piece",
        "icon": "\u25a4",
        "accept": ".pdf,.jpg,.jpeg,.png",
        "note": "IGI, SGL, GIA. One per stone if there are several.",
    },
    {
        "kind": MediaKind.JOB_CARD_SCAN,
        "label": "Job card",
        "on": "piece",
        "icon": "\u25a5",
        "accept": ".pdf,.jpg,.jpeg,.png,.heic",
        "note": "The paper this piece was made from.",
    },
    {
        "kind": MediaKind.DOCUMENT,
        "label": "Documents",
        "on": "piece",
        "icon": "\u25a7",
        "accept": ".pdf,.jpg,.jpeg,.png",
        "note": "Anything else on paper that belongs to this piece.",
    },
]

#: Which kinds may be made the picture every list and the catalogue pulls.
#: Piece-scoped only — a graph or a CAD file belongs to the design, and there
#: is no such thing as "the display picture of a design, for this one piece".
HERO_KINDS = frozenset({MediaKind.PHOTO, MediaKind.RENDER})


class StockState(models.TextChoices):
    NOT_RECEIVED = "NOT_RECEIVED", "Not received"
    IN_STOCK = "IN_STOCK", "In stock"
    RESERVED = "RESERVED", "Reserved"
    ON_APPROVAL = "ON_APPROVAL", "On approval"
    IN_TRANSIT = "IN_TRANSIT", "In transit"
    IN_REPAIR = "IN_REPAIR", "In repair"
    SOLD = "SOLD", "Sold"
    MELTED = "MELTED", "Melted"
    LOST = "LOST", "Lost"


#: ``stock_state IN ('SOLD','MELTED','LOST')`` — a piece here never moves again
TERMINAL_STATES = frozenset({StockState.SOLD, StockState.MELTED, StockState.LOST})
#: ``app.countable_state()`` — what should be on the shelf during a count
COUNTABLE_STATES = frozenset({StockState.IN_STOCK, StockState.RESERVED})


class MovementType(models.TextChoices):
    RECEIPT = "RECEIPT", "Receipt"
    TRANSFER_OUT = "TRANSFER_OUT", "Transfer out"
    TRANSFER_IN = "TRANSFER_IN", "Transfer in"
    RESERVE = "RESERVE", "Reserve"
    UNRESERVE = "UNRESERVE", "Unreserve"
    APPROVAL_OUT = "APPROVAL_OUT", "Approval out"
    APPROVAL_RETURN = "APPROVAL_RETURN", "Approval return"
    REPAIR_OUT = "REPAIR_OUT", "Repair out"
    REPAIR_IN = "REPAIR_IN", "Repair in"
    SALE = "SALE", "Sale"
    SALE_RETURN = "SALE_RETURN", "Sale return"
    MELT = "MELT", "Melt"
    LOST = "LOST", "Lost"
    COUNT_ADJUSTMENT = "COUNT_ADJUSTMENT", "Count adjustment"


class BomChangeReason(models.TextChoices):
    INITIAL = "INITIAL", "Initial"
    REPAIR = "REPAIR", "Repair"
    CORRECTION = "CORRECTION", "Correction"
    RECOST = "RECOST", "Recost"


class LocationKind(models.TextChoices):
    SHOWROOM = "SHOWROOM", "Showroom"
    GODOWN = "GODOWN", "Godown"
    WORKSHOP = "WORKSHOP", "Workshop"
    VENDOR = "VENDOR", "Vendor"
    TRANSIT = "TRANSIT", "Transit"
