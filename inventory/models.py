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
from django.db.models import Case, F, Q, Sum, Value, When
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
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children",
        help_text="The pouch a split took this one from.",
    )
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


class StockDocument(models.Model):
    """The header every stock-moving action posts its movements under.

    One shape for every kind, so a challan, a memo, a purchase bill, a split, a
    transfer and a one-off sale are listed, read and reversed the same way. Job
    work and memos stay open while goods are out; every other kind closes when
    it is posted. Nothing on it is edited afterwards: a reversal is a new
    document that points back at this one.
    """

    class Kind(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        JOB_WORK = "job_work", "Job work"
        MEMO = "memo", "Memo"
        SPLIT = "split", "Split"
        TRANSFER = "transfer", "Transfer"
        SINGLE = "single", "Single"
        # diamonds (part 4): listed only on the diamond screens, never on a stones one
        DIA_JOB = "dia_job", "Job card"
        DIA_ASSORT = "dia_assort", "Assortment"
        DIA_PURCHASE = "dia_purchase", "Diamond purchase"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        REVERSED = "reversed", "Reversed"

    CURRENCIES = [("INR", "INR"), ("USD", "USD")]

    kind = models.CharField(max_length=12, choices=Kind.choices)
    number = models.CharField(max_length=40)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    vendor = models.ForeignKey(
        "stock.Vendor", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="The supplier (purchase, purchase return) or the karigar (job work).",
    )
    # SET_NULL, as stock.Sale does: the CRM deletes customers, and a memo must not block it
    customer = models.ForeignKey("crm.Customer", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    occurred_on = models.DateField(default=timezone.localdate)
    expected_back = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCIES, blank=True)
    fx_rate = models.DecimalField("rate to INR", max_digits=12, decimal_places=4, null=True, blank=True)
    landed_extras = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    # a transfer's from and to, so reversing it can file the pouch back
    from_batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    from_pouch_no = models.CharField(max_length=16, blank=True)
    to_batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    to_pouch_no = models.CharField(max_length=16, blank=True)
    reverses = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversals")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_document"
        ordering = ["-created_at", "-pk"]
        constraints = [
            # a reversed document's number may be used again
            models.UniqueConstraint(
                fields=["kind", "number"], condition=~Q(status="reversed"), name="inv_document_number"
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.number}"


class Movement(models.Model):
    """Append-only. Pieces and carats are separate because a pouch can move by either.

    A ``settle`` is recorded against a document — goods already out, consumed,
    lost or sold — and never counts in a balance. A movement that ``reverses``
    another repeats its pouch, direction and quantities, and counts with the
    opposite sign.
    """

    IN, OUT, SETTLE = "in", "out", "settle"

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
        # the diamond ledgers (part 4)
        RETURNED_UNUSED = "Returned Unused"
        ASSORT_OUT = "Assort Out"
        ASSORT_IN = "Assort In"

    pouch = models.ForeignKey(Pouch, on_delete=models.PROTECT, related_name="movements", null=True, blank=True)
    diamond = models.ForeignKey(
        "DiamondLine", on_delete=models.PROTECT, related_name="movements", null=True, blank=True
    )
    occurred_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=32, choices=Reason.choices)
    direction = models.CharField(max_length=6, choices=[(IN, "In"), (OUT, "Out"), (SETTLE, "Settle")])
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
    document = models.ForeignKey(
        StockDocument, null=True, blank=True, on_delete=models.PROTECT, related_name="movements",
        help_text="Empty for opening balances and import recounts.",
    )
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal",
        help_text="The movement this one cancels.",
    )

    class Meta:
        db_table = "inv_movement"
        ordering = ["-occurred_at", "-pk"]
        constraints = [
            # one ledger for both kinds of stock: a movement moves exactly one thing
            models.CheckConstraint(
                condition=Q(pouch__isnull=False, diamond__isnull=True) | Q(pouch__isnull=True, diamond__isnull=False),
                name="inv_movement_one_owner",
            )
        ]

    def __str__(self):
        return f"{self.reason} {self.direction} {self.pouch_id or self.diamond_id}"

    @property
    def effect(self):
        """+1, −1 or 0: what this movement does to its pouch's balance — ``balance``'s rule, row by row."""
        if self.direction == self.SETTLE:
            return 0
        sign = 1 if self.direction == self.IN else -1
        return -sign if self.reverses_id else sign


def balance(field):
    """The sum of ``pcs`` or ``ct`` over ``movements`` that is a pouch's (or a diamond line's) balance.

    In adds and out subtracts; a settle never counts, because the goods it
    settles had already left; a reversal counts with the opposite sign of the
    movement it cancels. Stones and diamonds share this table, so every
    balance reads through here.
    """
    value = F(f"movements__{field}")
    return Sum(Case(
        When(movements__direction=Movement.SETTLE, then=Value(0)),
        When(movements__direction=Movement.OUT, movements__reverses__isnull=True, then=-value),
        When(movements__direction=Movement.IN, movements__reverses__isnull=False, then=-value),
        default=value,
        output_field=Movement._meta.get_field(field),
    ))


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


class DiamondTerm(models.Model):
    """One value in one of the diamond master lists.

    Every list the Settings page edits is rows here, so renaming a value renames
    it on every code and line that uses it.
    """

    CATEGORY, SHAPE, COLOUR, CLARITY, BAND = "category", "shape", "colour", "clarity", "band"
    KINDS = [(CATEGORY, "Category"), (SHAPE, "Shape"), (COLOUR, "Colour grade"),
             (CLARITY, "Clarity grade"), (BAND, "Size band")]

    kind = models.CharField(max_length=10, choices=KINDS)
    value = models.CharField(max_length=60)
    sort = models.IntegerField(default=1000)
    expands_to = models.CharField(
        max_length=120, blank=True, help_text="Space-separated single grades this range stands for."
    )

    class Meta:
        db_table = "inv_dia_term"
        ordering = ["kind", "sort", "value"]
        constraints = [models.UniqueConstraint(fields=["kind", "value"], name="inv_dia_term_key")]

    def __str__(self):
        return self.value

    def grades(self):
        """The single grades a filter chip matches this value by.

        A range answers for each grade it spans; a plain grade for itself; a
        fancy colour or an unresolved token for none, so it never poses as a grade.
        """
        if self.expands_to:
            return self.expands_to.split()
        if self.value.startswith(("?", "(", "Fancy")):
            return []
        return [self.value]


class DiamondCode(models.Model):
    """One item code (``DRFGH VS-SI``) and what it means. Fixed once, every line follows."""

    item_code = models.CharField(max_length=40, primary_key=True)
    shape = models.ForeignKey(DiamondTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    colour = models.ForeignKey(DiamondTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    clarity = models.ForeignKey(DiamondTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    confirmed = models.BooleanField(default=False)
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "inv_dia_code"
        ordering = ["item_code"]

    def __str__(self):
        return self.item_code


class DiamondLine(models.Model):
    """One diamond stock line. Carats on hand are the sum of its movements."""

    ref = models.CharField(max_length=12, unique=True, editable=False)
    category = models.ForeignKey(DiamondTerm, on_delete=models.PROTECT, related_name="+")
    code = models.ForeignKey(DiamondCode, on_delete=models.PROTECT, related_name="lines")
    shape_override = models.ForeignKey(
        DiamondTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="From a carat-band size prefix, when the code names no shape.",
    )
    colour_override = models.ForeignKey(
        DiamondTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="The file's colour for this line, when it differs from its code's (fancy lots under one code).",
    )
    batch_no = models.CharField(max_length=40, blank=True)
    size_text = models.CharField(max_length=40, blank=True)
    band = models.ForeignKey(DiamondTerm, on_delete=models.PROTECT, related_name="+")
    ct_lo = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    ct_hi = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    src = models.CharField(max_length=24, blank=True, help_text="Sheet and row it came from.")
    import_batch = models.ForeignKey(
        "stock.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_dia_line"
        ordering = ["pk"]

    def __str__(self):
        return f"{self.ref} {self.code_id}"

    @property
    def shape(self):
        return self.shape_override or self.code.shape

    @property
    def colour(self):
        return self.colour_override or self.code.colour


class DiamondRate(models.Model):
    """The inventory's own rate card: per item code, per size ("" = any size). Latest wins."""

    code = models.ForeignKey(DiamondCode, on_delete=models.PROTECT, related_name="rates")
    size_text = models.CharField(max_length=40, blank=True)
    cost_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    sale_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    effective_from = models.DateField(default=timezone.localdate)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_dia_rate"
        ordering = ["code", "size_text", "-effective_from", "-pk"]

    def __str__(self):
        return f"{self.code_id} {self.size_text or 'any size'}"


class DiamondLineCost(models.Model):
    """A diamond line's own cost per carat, in INR: written by the purchase that brought it in, or
    carried by weight through an assortment. Latest wins, and it wins over the rate card (owner,
    2026-10-01). Imported lines have none and keep the rate card. Nothing is overwritten."""

    line = models.ForeignKey(DiamondLine, on_delete=models.PROTECT, related_name="costs")
    cost_rate = models.DecimalField(max_digits=14, decimal_places=4)
    effective_from = models.DateField(default=timezone.localdate)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    document = models.ForeignKey(
        StockDocument, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="The purchase or assortment that set it; empty for a manual change.",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_dia_line_cost"
        ordering = ["-effective_from", "-pk"]

    def __str__(self):
        return f"{self.cost_rate}/ct on {self.line_id}"
