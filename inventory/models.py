"""Box colour → batch → pouch, and the two ledgers that hang off a pouch.

A pouch's quantity is never stored. It is the sum of its movements, so the only
way stock changes is by posting one, and a wrong entry is corrected by another
entry rather than by editing a number. Its value is carats on hand × the latest
valuation rate; a revaluation adds a row and overwrites nothing.

The batch code (``SR01Y``) says where a pouch is filed, which is exactly why it
is not the pouch's identity: re-filing would change it. The identity is the
``NRN-`` reference, assigned once.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .seed import HATCH

UNRESOLVED_SWATCH = HATCH

#: vocab.py's TREATMENT list; the blank choice is "Not recorded"
TREATMENTS = [(t, t) for t in [
    "Unknown", "None (verified)", "Heated", "Oiled / Resin", "Dyed", "Bleached",
    "Stabilised / Impregnated", "Coated (incl. AB / iridescent)", "Irradiated",
    "Diffused", "Glass-filled", "Reconstituted / Composite", "Laser Drilled",
]]

#: the prototype's origin list
ORIGINS = [(o, o) for o in [
    "Iran (feroza)", "China", "Burma / Myanmar", "Sri Lanka (Ceylon)", "Zambia", "Brazil",
    "Tanzania (Merelani)", "Africa — other", "India",
]]


class BoxColour(models.Model):
    code = models.CharField(max_length=4, primary_key=True)
    label = models.CharField(max_length=80)
    swatch = models.CharField(max_length=200, help_text="A CSS background: a colour, a gradient or a hatch.")
    confirmed = models.BooleanField(default=False)

    class Meta:
        db_table = "inv_box_colour"
        ordering = ["code"]

    def __str__(self):
        return f"{self.label} · {self.code}"


class CodePart(models.Model):
    """The first two letters of a batch code: material family, then class."""

    FAMILY, CLASS = "family", "class"

    kind = models.CharField(max_length=8, choices=[(FAMILY, "Material family"), (CLASS, "Class")])
    code = models.CharField(max_length=2)
    label = models.CharField(max_length=80)
    confirmed = models.BooleanField(default=False)

    class Meta:
        db_table = "inv_code_part"
        ordering = ["kind", "code"]
        constraints = [models.UniqueConstraint(fields=["kind", "code"], name="inv_code_part_key")]

    def __str__(self):
        return f"{self.kind} {self.code} = {self.label}"


class Batch(models.Model):
    code = models.CharField(max_length=16, unique=True)
    box_colour = models.ForeignKey(BoxColour, on_delete=models.PROTECT, related_name="batches")
    family = models.CharField(max_length=2)
    cls = models.CharField(max_length=2)
    seq = models.CharField(max_length=8)

    class Meta:
        db_table = "inv_batch"
        ordering = ["code"]
        verbose_name_plural = "batches"

    def __str__(self):
        return self.code


class Pouch(models.Model):
    ref = models.CharField(max_length=12, unique=True, editable=False)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="pouches")
    pouch_no = models.CharField(max_length=16, null=True, blank=True)
    carton = models.CharField("box no.", max_length=32, blank=True)

    # as typed in the register; normalising them is a data-quality job, not this one
    category = models.CharField(max_length=80, blank=True)
    stone_name = models.CharField(max_length=120, blank=True)
    colour = models.CharField(max_length=80, blank=True)
    shape = models.CharField(max_length=80, blank=True)
    cut = models.CharField(max_length=80, blank=True)
    quality = models.CharField(max_length=20, blank=True)
    size_text = models.CharField(max_length=80, blank=True)
    countable = models.BooleanField(default=True, help_text="A blank Pcs in the register: too small or too many to count.")
    remarks = models.TextField(blank=True)
    src = models.CharField(max_length=24, blank=True, help_text="Sheet and row it came from, e.g. SP!104.")
    import_batch = models.ForeignKey(
        "stock.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    treatment = models.CharField(max_length=40, blank=True, choices=TREATMENTS)
    origin = models.CharField(max_length=40, blank=True, choices=ORIGINS)
    purchase_date = models.DateField(null=True, blank=True)
    supplier = models.ForeignKey("stock.Vendor", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_pouch"
        ordering = ["batch__code", "pk"]
        verbose_name_plural = "pouches"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "pouch_no"], condition=Q(pouch_no__isnull=False), name="inv_pouch_key"
            )
        ]

    def __str__(self):
        return f"{self.batch.code} · {self.pouch_no or '?'}"


class Movement(models.Model):
    """Append-only. Pieces and carats are separate because a pouch can move by either."""

    IN, OUT = "in", "out"

    class Reason(models.TextChoices):
        OPENING_BALANCE = "Opening Balance"
        PURCHASE = "Purchase"
        PURCHASE_RETURN = "Purchase Return"
        SALE = "Sale"
        SALES_RETURN = "Sales Return"
        MEMO_OUT = "Memo Out"
        MEMO_IN = "Memo In"
        JOB_WORK_OUT = "Job Work Out"
        JOB_WORK_IN = "Job Work In"
        CONSUMED = "Consumed in Production"
        WASTAGE = "Wastage / Loss in Process"
        BREAKAGE = "Breakage"
        SPLIT = "Split"
        MERGE = "Merge"
        TRANSFER = "Transfer"
        SAMPLE = "Sample"
        RECOUNT_ADJUSTMENT = "Recount Adjustment"

    pouch = models.ForeignKey(Pouch, on_delete=models.PROTECT, related_name="movements")
    occurred_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=32, choices=Reason.choices)
    direction = models.CharField(max_length=3, choices=[(IN, "In"), (OUT, "Out")])
    pcs = models.PositiveIntegerField(null=True, blank=True)
    ct = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    counterparty = models.ForeignKey("stock.Vendor", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    challan_no = models.CharField(max_length=40, blank=True)
    ref = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_movement"
        ordering = ["-occurred_at", "-pk"]

    def __str__(self):
        return f"{self.reason} {self.direction} {self.pouch_id}"


class PriceEntry(models.Model):
    """A dated rate per carat. Nothing is overwritten: the latest of a kind is current."""

    VALUATION, PURCHASE, LIST = "valuation", "purchase", "list"
    KINDS = [(VALUATION, "Valuation"), (PURCHASE, "Purchase"), (LIST, "List")]

    pouch = models.ForeignKey(Pouch, on_delete=models.PROTECT, related_name="prices")
    kind = models.CharField(max_length=10, choices=KINDS)
    rate = models.DecimalField(max_digits=14, decimal_places=4)
    effective_from = models.DateField(default=timezone.localdate)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_price"
        ordering = ["-effective_from", "-pk"]

    def __str__(self):
        return f"{self.kind} {self.rate}/ct on {self.pouch_id}"
