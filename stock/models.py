"""The ``app`` schema, mirrored near-1:1.

Table and column names are kept — ``db_table``/``db_column`` everywhere — so a
legacy dump restores beside this one and ``parity_check`` can compare like with
like. Money is ``DecimalField`` throughout; a float here is a rounding bug that
shows up as a rupee gap months later.

Guarantees the SQL had are kept at the database level rather than re-expressed
in Python: foreign keys, the CHECKs, and the partial unique indexes — the one
on ``sale.jewel_code_id`` above all, which is what stops a piece being sold
twice.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .enums import (
    BomChangeReason,
    ChargeBasis,
    COUNTABLE_STATES,
    DesignState,
    LocationKind,
    MediaKind,
    MovementType,
    StockState,
    Uom,
)


class AppModel(models.Model):
    """Everything in this app lives in one schema's worth of tables."""

    class Meta:
        abstract = True


# ── reference ────────────────────────────────────────────────────────────
class UomConversion(AppModel):
    unit = models.CharField(max_length=8, primary_key=True, choices=Uom.choices, db_column="unit")
    grams_per_unit = models.DecimalField(max_digits=12, decimal_places=6)

    class Meta:
        db_table = "uom_conversion"

    def __str__(self):
        return self.unit


class Metal(AppModel):
    """One live rate per metal, typed in by an admin (migration 0032b)."""

    code = models.CharField(max_length=32, primary_key=True)
    name = models.CharField(max_length=80)
    pure_rate = models.DecimalField(max_digits=14, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))])
    rate_as_on = models.DateTimeField(default=timezone.now)
    unit = models.CharField(max_length=8, default="GM")
    note = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "metal"
        constraints = [models.CheckConstraint(condition=Q(pure_rate__gt=0), name="metal_rate_positive")]

    def __str__(self):
        return self.name


class MetalPurity(AppModel):
    """A purity belongs to a metal. 925 silver prices off silver, not gold."""

    karat = models.CharField(max_length=16, primary_key=True)
    sale_factor = models.DecimalField(max_digits=6, decimal_places=4)
    true_fineness = models.DecimalField(max_digits=6, decimal_places=4)
    metal = models.ForeignKey(Metal, on_delete=models.PROTECT, db_column="metal", related_name="purities")
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "metal_purity"
        ordering = ["metal_id", "sort_order"]
        constraints = [
            models.CheckConstraint(
                condition=Q(sale_factor__gt=0) & Q(true_fineness__gt=0) & Q(true_fineness__lte=1),
                name="metal_purity_factors_sane",
            )
        ]

    def __str__(self):
        return self.karat


class SystemSetting(AppModel):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.TextField()
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "system_setting"

    def __str__(self):
        return self.key


class Location(AppModel):
    location_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=LocationKind.choices, default=LocationKind.SHOWROOM)
    city = models.CharField(max_length=80, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "location"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Category(AppModel):
    category_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, db_column="parent_id")
    code_prefix = models.CharField(max_length=8, blank=True, null=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "category"
        ordering = ["sort_order", "code"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Tag(AppModel):
    tag_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=80)
    tag_group = models.CharField(max_length=40)

    class Meta:
        db_table = "tag"
        unique_together = [("tag_group", "name")]

    def __str__(self):
        return f"{self.tag_group}:{self.name}"


class Collection(AppModel):
    collection_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=32, unique=True, null=True, blank=True)
    name = models.CharField(max_length=120)
    story = models.TextField(blank=True, null=True)
    is_bestseller = models.BooleanField(default=False)
    launched_on = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "collection"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Vendor(AppModel):
    vendor_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    contact = models.CharField(max_length=120, blank=True, null=True)
    city = models.CharField(max_length=80, blank=True, null=True)
    avg_tat_days = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "vendor"
        ordering = ["code"]

    def __str__(self):
        return self.name


class MaterialCategory(AppModel):
    """The six categories the business uses (migration 0034), plus Making."""

    code = models.CharField(max_length=32, primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    sort_order = models.IntegerField(default=0)
    is_priceable = models.BooleanField(default=True)
    note = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "material_category"
        ordering = ["sort_order"]
        verbose_name_plural = "material categories"

    def __str__(self):
        return self.name


class Material(AppModel):
    material_id = models.AutoField(primary_key=True)
    item_code = models.CharField(max_length=64, unique=True)
    item_name = models.CharField(max_length=160)
    description = models.TextField(blank=True, null=True)
    size = models.CharField(max_length=64, blank=True, null=True)
    category = models.ForeignKey(
        MaterialCategory, on_delete=models.PROTECT, db_column="category", related_name="materials"
    )
    default_uom = models.CharField(max_length=8, choices=Uom.choices)
    purity_factor = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    metal = models.ForeignKey(
        Metal, null=True, blank=True, on_delete=models.PROTECT, db_column="metal", related_name="materials"
    )
    needs_review = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "material"
        ordering = ["item_code"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(category="METAL") | Q(metal__isnull=False),
                name="material_metal_required",
            )
        ]

    # ``mat_class`` was a second copy of the category that could disagree with
    # it; the category is the single answer now, and these are the two
    # questions costing actually asks of it.
    @property
    def is_metal(self):
        return self.category_id == "METAL"

    @property
    def is_labour(self):
        return self.category_id == "LABOUR"

    def __str__(self):
        return f"{self.item_code} — {self.item_name}"


class Style(AppModel):
    style_id = models.AutoField(primary_key=True)
    style_code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=160, blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, db_column="category_id", related_name="styles")
    collection = models.ForeignKey(
        Collection, null=True, blank=True, on_delete=models.SET_NULL, db_column="collection_id", related_name="styles"
    )
    state = models.CharField(max_length=24, choices=DesignState.choices, default=DesignState.SKETCH)
    designer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_column="designer_user_id",
        related_name="designed_styles",
    )
    story = models.TextField(blank=True, null=True)
    website_description = models.TextField(blank=True, null=True)
    designed_on = models.DateField(null=True, blank=True)
    parent_style = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, db_column="parent_style_id", related_name="versions"
    )
    version_label = models.CharField(max_length=40, blank=True, null=True)
    nos_min_qty = models.IntegerField(default=0)
    tags = models.ManyToManyField(Tag, through="StyleTag", related_name="styles", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_column="created_by",
        related_name="+",
    )

    class Meta:
        db_table = "style"
        ordering = ["style_code"]

    def __str__(self):
        return self.style_code


class StyleTag(AppModel):
    style = models.ForeignKey(Style, on_delete=models.CASCADE, db_column="style_id")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, db_column="tag_id")

    class Meta:
        db_table = "style_tag"
        unique_together = [("style", "tag")]


class Scenario(AppModel):
    """Turns cost into an asking price. Metal is never marked up (0036)."""

    CHART = "CHART"
    VALUE_ADDED = "VALUE_ADDED"
    MULTIPLIER = "MULTIPLIER"
    METHODS = [
        (CHART, "Rate chart \u2014 take the sale rate as written"),
        (VALUE_ADDED, "Target margin \u2014 cost + %, absorbed by the chosen categories"),
        (MULTIPLIER, "Category multipliers \u2014 a factor per material category"),
    ]
    SPREAD_BY = [
        ("COST", "Their cost"),
        ("WEIGHT", "Their weight"),
        ("CHART", "Their rate-chart sale value"),
    ]

    scenario_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    method = models.CharField(max_length=16, choices=METHODS)
    chart = models.ForeignKey(
        "RateChart", null=True, blank=True, on_delete=models.SET_NULL, db_column="chart_id", related_name="scenarios"
    )
    target_pct = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    spread_over = models.JSONField(
        default=list,
        blank=True,
        help_text='Material categories the markup lands on, e.g. ["DIAMOND","POLKI"]. Empty means every priceable non-metal category.',
    )
    spread_by = models.CharField(max_length=8, choices=SPREAD_BY, default="COST")
    multipliers = models.JSONField(
        default=dict,
        blank=True,
        help_text='Category multipliers, e.g. {"DIAMOND": "2.5"}. A category left out passes at 1\u00d7.',
    )
    min_multiple = models.DecimalField(max_digits=8, decimal_places=3, default=Decimal("1.0"))
    max_multiple = models.DecimalField(max_digits=8, decimal_places=3, default=Decimal("8.0"))
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "scenario"
        constraints = [
            models.UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="scenario_one_default"),
            models.CheckConstraint(
                condition=~Q(method="VALUE_ADDED") | Q(target_pct__isnull=False),
                name="scenario_value_added_needs_target",
            ),
        ]

    def __str__(self):
        return self.name


class ScenarioRole(AppModel):
    """Who may price with a scenario, and who may switch a piece onto it."""

    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, db_column="scenario_id", related_name="roles")
    group = models.ForeignKey("auth.Group", on_delete=models.CASCADE, db_column="role_id", related_name="scenario_roles")
    may_see = models.BooleanField(default=True)
    may_switch = models.BooleanField(default=False)

    class Meta:
        db_table = "scenario_role"
        unique_together = [("scenario", "group")]


class RateChart(AppModel):
    """Cost and sale on one line. Forks rather than being edited in place."""

    chart_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=80)
    version_no = models.IntegerField(default=1)
    is_default = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False)
    forked_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, db_column="forked_from", related_name="forks"
    )
    note = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="created_by", related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "rate_chart"
        ordering = ["-is_default", "code", "-version_no"]
        constraints = [
            models.UniqueConstraint(fields=["code", "version_no"], name="rate_chart_code_version"),
            models.UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="rate_chart_one_default"),
        ]

    def __str__(self):
        return f"{self.name} v{self.version_no}"


class RateChartLine(AppModel):
    chart = models.ForeignKey(RateChart, on_delete=models.CASCADE, db_column="chart_id", related_name="lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, db_column="material_id", related_name="chart_lines")
    size_band = models.CharField(max_length=64, default="", blank=True)
    cost_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    sale_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    rate_uom = models.CharField(max_length=8, blank=True, null=True)

    class Meta:
        db_table = "rate_chart_line"
        unique_together = [("chart", "material", "size_band")]
        constraints = [
            models.CheckConstraint(condition=Q(cost_rate__isnull=True) | Q(cost_rate__gte=0), name="chart_cost_nonneg"),
            models.CheckConstraint(condition=Q(sale_rate__isnull=True) | Q(sale_rate__gte=0), name="chart_sale_nonneg"),
        ]


class RateCard(AppModel):
    """Superseded by RateChart but kept: BOM versions still point at it."""

    COST = "COST"
    SALE = "SALE"
    rate_card_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    card_type = models.CharField(max_length=8, choices=[(COST, "Cost"), (SALE, "Sale")])
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="created_by", related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "rate_card"

    def __str__(self):
        return self.code


class RateCardLine(AppModel):
    rate_card = models.ForeignKey(RateCard, on_delete=models.CASCADE, db_column="rate_card_id", related_name="lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, db_column="material_id", related_name="card_lines")
    size_band = models.CharField(max_length=64, default="", blank=True)
    rate = models.DecimalField(max_digits=14, decimal_places=4)
    rate_uom = models.CharField(max_length=8, choices=Uom.choices)

    class Meta:
        db_table = "rate_card_line"
        unique_together = [("rate_card", "material", "size_band")]


# ── pieces ───────────────────────────────────────────────────────────────
class PieceQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The RLS rule ``jewel_visible``, in one place.

        A piece with no location (never received, or terminal) is visible to
        everyone; anything on a shelf is visible only to someone who can see
        that shelf.
        """
        if user is None or not user.is_authenticated:
            return self.none()
        if user.is_superuser or user.home_location_id is None:
            return self
        return self.filter(Q(location__isnull=True) | Q(location_id__in=user.visible_location_ids()))

    def live(self):
        return self.filter(stock_state__in=list(COUNTABLE_STATES))

    def with_current_bom(self):
        return self.select_related("style", "style__category", "location", "vendor").prefetch_related("bom_versions")


class Piece(AppModel):
    """``app.jewel_code`` — one physical piece, its whole life in one row."""

    jewel_code_id = models.AutoField(primary_key=True)
    jewel_code = models.CharField(max_length=64, unique=True)
    style = models.ForeignKey(Style, on_delete=models.PROTECT, db_column="style_id", related_name="pieces")
    sub_category = models.CharField(max_length=80, blank=True, null=True)
    metal_purity = models.CharField(max_length=16, blank=True, null=True, help_text="Karat, e.g. 18K or 925.")
    metal_colour = models.CharField(max_length=32, blank=True, null=True)
    size_label = models.CharField(max_length=32, blank=True, null=True)
    diamond_quality = models.CharField(max_length=64, blank=True, null=True)
    measured_gross_wt_gm = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    length_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    breadth_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    height_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    fg_date = models.DateField(null=True, blank=True)
    stock_type = models.CharField(max_length=32, default="FINISH_GOODS", blank=True, null=True)
    huid = models.CharField(max_length=32, unique=True, null=True, blank=True)
    hallmarked_on = models.DateField(null=True, blank=True)
    hallmark_centre = models.CharField(max_length=120, blank=True, null=True)
    stock_state = models.CharField(max_length=16, choices=StockState.choices, default=StockState.NOT_RECEIVED)
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, db_column="location_id", related_name="pieces"
    )
    received_on = models.DateField(null=True, blank=True)
    disposed_on = models.DateField(null=True, blank=True)
    current_bom_version = models.IntegerField(default=1)
    vendor = models.ForeignKey(
        Vendor, null=True, blank=True, on_delete=models.PROTECT, db_column="vendor_id", related_name="pieces"
    )
    scenario = models.ForeignKey(
        Scenario, null=True, blank=True, on_delete=models.SET_NULL, db_column="scenario_id", related_name="pieces"
    )
    on_website = models.BooleanField(default=False)
    website_url = models.URLField(max_length=500, blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    # what the source system said, kept beside what we computed (0018)
    src_system = models.CharField(max_length=40, blank=True, null=True)
    src_ref = models.CharField(max_length=80, blank=True, null=True)
    src_cost_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    src_sale_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    src_tag_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    src_net_wt_gm = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    bom_is_summary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="created_by", related_name="+"
    )
    updated_at = models.DateTimeField(default=timezone.now)

    objects = PieceQuerySet.as_manager()

    class Meta:
        db_table = "jewel_code"
        ordering = ["jewel_code"]
        indexes = [
            models.Index(fields=["style"], name="idx_jewel_style"),
            models.Index(fields=["stock_state", "location"], name="idx_jewel_state"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(stock_state__in=["SOLD", "MELTED", "LOST", "NOT_RECEIVED"]) | Q(location__isnull=False),
                name="live_piece_has_location",
            ),
            models.CheckConstraint(
                condition=~Q(stock_state__in=["SOLD", "MELTED", "LOST"]) | Q(disposed_on__isnull=False),
                name="dead_piece_has_date",
            ),
        ]

    def __str__(self):
        return self.jewel_code

    @property
    def is_terminal(self):
        from .enums import TERMINAL_STATES

        return self.stock_state in TERMINAL_STATES

    def current_bom(self):
        return self.bom_versions.filter(is_current=True).first()


class PieceCertificate(AppModel):
    certificate_id = models.AutoField(primary_key=True)
    piece = models.ForeignKey(Piece, on_delete=models.CASCADE, db_column="jewel_code_id", related_name="certificates")
    company = models.CharField(max_length=80)
    cert_number = models.CharField(max_length=80)
    issued_on = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "jewel_code_certificate"
        unique_together = [("company", "cert_number")]


class BomVersion(AppModel):
    """One frozen costing of one piece. Versions are added, never edited."""

    piece = models.ForeignKey(Piece, on_delete=models.CASCADE, db_column="jewel_code_id", related_name="bom_versions")
    version_no = models.IntegerField()
    reason = models.CharField(max_length=16, choices=BomChangeReason.choices, default=BomChangeReason.INITIAL)
    note = models.TextField(blank=True, null=True)
    repair_job = models.ForeignKey(
        "RepairJob", null=True, blank=True, on_delete=models.SET_NULL, db_column="repair_job_id", related_name="bom_versions"
    )
    cost_rate_card = models.ForeignKey(
        RateCard, null=True, blank=True, on_delete=models.SET_NULL, db_column="cost_rate_card_id", related_name="+"
    )
    sale_rate_card = models.ForeignKey(
        RateCard, null=True, blank=True, on_delete=models.SET_NULL, db_column="sale_rate_card_id", related_name="+"
    )
    net_metal_wt_gm = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    bom_weight_gm = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    total_cost_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    total_sale_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    making_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    goods_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="created_by", related_name="+"
    )

    class Meta:
        db_table = "bom_version"
        ordering = ["piece_id", "version_no"]
        constraints = [
            models.UniqueConstraint(fields=["piece", "version_no"], name="bom_version_pk"),
            models.UniqueConstraint(fields=["piece"], condition=Q(is_current=True), name="uq_current_bom"),
        ]

    def __str__(self):
        return f"{self.piece_id} v{self.version_no}"


class BomLine(AppModel):
    """``app.jewel_material_line`` — one material on one version of one piece."""

    line_id = models.BigAutoField(primary_key=True)
    piece = models.ForeignKey(Piece, on_delete=models.CASCADE, db_column="jewel_code_id", related_name="bom_lines")
    version_no = models.IntegerField()
    line_no = models.IntegerField()
    material = models.ForeignKey(Material, on_delete=models.PROTECT, db_column="material_id", related_name="bom_lines")
    size_band = models.CharField(max_length=64, default="", blank=True)
    pcs = models.IntegerField(null=True, blank=True)
    qty_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    qty_uom = models.CharField(max_length=8, choices=Uom.choices)
    basis = models.CharField(max_length=20, choices=ChargeBasis.choices, default=ChargeBasis.BY_QTY)
    cost_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    cost_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    sale_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    sale_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    off_chart = models.BooleanField(
        default=False, help_text="Carries a rate that differs from the chart it was priced against — deliberate, and findable later."
    )
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "jewel_material_line"
        ordering = ["piece_id", "version_no", "line_no"]
        unique_together = [("piece", "version_no", "line_no")]
        indexes = [models.Index(fields=["piece", "version_no"], name="idx_jml")]

    def __str__(self):
        return f"{self.piece_id} v{self.version_no} #{self.line_no}"


# ── the ledger ───────────────────────────────────────────────────────────
class StockMovement(AppModel):
    """Append-only. A piece's state is whatever its last movement said."""

    movement_id = models.BigAutoField(primary_key=True)
    piece = models.ForeignKey(Piece, on_delete=models.PROTECT, db_column="jewel_code_id", related_name="movements")
    move_type = models.CharField(max_length=20, choices=MovementType.choices)
    from_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, db_column="from_location_id", related_name="movements_out"
    )
    to_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, db_column="to_location_id", related_name="movements_in"
    )
    resulting_state = models.CharField(max_length=16, choices=StockState.choices)
    moved_at = models.DateTimeField()
    reference_no = models.CharField(max_length=80, blank=True, null=True)
    party_name = models.CharField(max_length=160, blank=True, null=True)
    reason = models.TextField(blank=True, null=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="user_id", related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "stock_movement"
        ordering = ["-moved_at", "-movement_id"]
        indexes = [
            models.Index(fields=["piece", "-moved_at"], name="idx_move_jc"),
            models.Index(fields=["move_type", "-moved_at"], name="idx_move_type"),
        ]

    def __str__(self):
        return f"{self.move_type} {self.piece_id}"


class Sale(AppModel):
    """One revenue ledger. A CRM purchase lands here too, with ``source='CRM'``.

    The partial unique index on ``piece`` is what stops the same piece being
    sold twice; CRM-sourced rows carry no piece at all and are excluded from it.
    """

    STOCK = "STOCK"
    CRM = "CRM"
    SOURCES = [(STOCK, "Stock"), (CRM, "CRM")]

    sale_id = models.BigAutoField(primary_key=True)
    piece = models.ForeignKey(
        Piece, null=True, blank=True, on_delete=models.PROTECT, db_column="jewel_code_id", related_name="sales"
    )
    bom_version_at_sale = models.IntegerField(null=True, blank=True)
    sold_on = models.DateField()
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, db_column="location_id", related_name="sales"
    )
    customer_name = models.CharField(max_length=160, blank=True, null=True)
    customer_phone = models.CharField(max_length=40, blank=True, null=True)
    customer = models.ForeignKey(
        "crm.Customer", null=True, blank=True, on_delete=models.SET_NULL, related_name="sales"
    )
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="salesperson_id", related_name="+"
    )
    sold_price = models.DecimalField(max_digits=14, decimal_places=2)
    discount_amt = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    cost_at_sale = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    margin_amt = models.GeneratedField(
        expression=models.F("sold_price") - models.F("discount_amt") - models.F("cost_at_sale"),
        output_field=models.DecimalField(max_digits=14, decimal_places=2),
        db_persist=True,
    )
    source = models.CharField(max_length=8, choices=SOURCES, default=STOCK)
    # what the CRM knew about the sale and stock never did
    product_category = models.CharField(
        max_length=8, blank=True, null=True, help_text="cat1/cat2/cat3 — the FoN commission category."
    )
    invoice_no = models.CharField(max_length=80, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    remarks = models.TextField(blank=True, null=True, help_text="The legacy purchase form's free-text remarks.")
    legacy_id = models.CharField(max_length=64, blank=True, null=True, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "sale"
        ordering = ["-sold_on", "-sale_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["piece"], condition=Q(piece__isnull=False), name="uq_sale_piece_once"
            ),
        ]

    def __str__(self):
        return f"{self.piece_id or self.customer_id} {self.sold_price}"


class MeltRecord(AppModel):
    melt_id = models.BigAutoField(primary_key=True)
    piece = models.OneToOneField(Piece, on_delete=models.PROTECT, db_column="jewel_code_id", related_name="melt")
    bom_version_at_melt = models.IntegerField()
    melted_on = models.DateField()
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, db_column="location_id", related_name="melts"
    )
    reason = models.TextField()
    cost_written_off = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    authorised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, db_column="authorised_by", related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "melt_record"


class RepairJob(AppModel):
    OPEN, WITH_VENDOR, DONE, CANCELLED = "OPEN", "WITH_VENDOR", "DONE", "CANCELLED"
    STATUSES = [(OPEN, "Open"), (WITH_VENDOR, "With vendor"), (DONE, "Done"), (CANCELLED, "Cancelled")]

    repair_job_id = models.BigAutoField(primary_key=True)
    job_no = models.CharField(max_length=40, unique=True)
    piece = models.ForeignKey(Piece, on_delete=models.PROTECT, db_column="jewel_code_id", related_name="repairs")
    from_bom_version = models.IntegerField()
    to_bom_version = models.IntegerField(null=True, blank=True)
    opened_on = models.DateField()
    closed_on = models.DateField(null=True, blank=True)
    vendor = models.ForeignKey(
        Vendor, null=True, blank=True, on_delete=models.PROTECT, db_column="vendor_id", related_name="repairs"
    )
    return_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, db_column="return_location_id", related_name="+"
    )
    fault_description = models.TextField()
    work_done = models.TextField(blank=True, null=True)
    labour_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    status = models.CharField(max_length=16, choices=STATUSES, default=OPEN)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="opened_by", related_name="+"
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="closed_by", related_name="+"
    )

    class Meta:
        db_table = "repair_job"
        ordering = ["-opened_on"]

    def __str__(self):
        return self.job_no

    @property
    def tat_days(self):
        if self.closed_on and self.opened_on:
            return (self.closed_on - self.opened_on).days
        return None


class RepairMaterialChange(AppModel):
    REMOVE, ADD = "REMOVE", "ADD"
    change_id = models.BigAutoField(primary_key=True)
    repair_job = models.ForeignKey(RepairJob, on_delete=models.CASCADE, db_column="repair_job_id", related_name="changes")
    action = models.CharField(max_length=8, choices=[(REMOVE, "Remove"), (ADD, "Add")])
    material = models.ForeignKey(Material, on_delete=models.PROTECT, db_column="material_id", related_name="+")
    size_band = models.CharField(max_length=64, default="", blank=True)
    pcs = models.IntegerField(null=True, blank=True)
    qty_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    qty_uom = models.CharField(max_length=8, choices=Uom.choices)
    cost_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    sale_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    returned_to_stock = models.BooleanField(default=True)
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "repair_material_change"


# ── stock count ──────────────────────────────────────────────────────────
class StockCount(AppModel):
    OPEN, CLOSED, CANCELLED = "OPEN", "CLOSED", "CANCELLED"
    STATUSES = [(OPEN, "Open"), (CLOSED, "Closed"), (CANCELLED, "Cancelled")]

    count_id = models.AutoField(primary_key=True)
    count_ref = models.CharField(max_length=64, unique=True)
    location = models.ForeignKey(Location, on_delete=models.PROTECT, db_column="location_id", related_name="counts")
    started_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default=OPEN)
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="counted_by", related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="approved_by", related_name="+"
    )
    notes = models.TextField(blank=True, null=True)
    result = models.JSONField(null=True, blank=True, help_text="Frozen at close. A closed count is never recomputed.")

    class Meta:
        db_table = "stock_count"
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["location"], condition=Q(status="OPEN"), name="stock_count_one_open_per_location"
            )
        ]

    def __str__(self):
        return self.count_ref


class StockCountScan(AppModel):
    FOUND, ELSEWHERE, NOT_STOCK = "FOUND", "ELSEWHERE", "NOT_STOCK"

    scan_id = models.BigAutoField(primary_key=True)
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, db_column="count_id", related_name="scans")
    piece = models.ForeignKey(Piece, on_delete=models.PROTECT, db_column="jewel_code_id", related_name="count_scans")
    scanned_at = models.DateTimeField(default=timezone.now)
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="scanned_by", related_name="+"
    )
    verdict = models.CharField(max_length=16, blank=True, null=True)

    class Meta:
        db_table = "stock_count_scan"
        unique_together = [("count", "piece")]
        indexes = [models.Index(fields=["count", "-scanned_at"], name="stock_count_scan_seen")]


# ── catalogue, job cards, inventory, audit ───────────────────────────────
class CatalogueTemplate(AppModel):
    template_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=120)
    layout = models.CharField(max_length=32, default="GRID_2x2")
    show_sale_price = models.BooleanField(default=True)
    show_cost_price = models.BooleanField(default=False)
    show_material_breakup = models.BooleanField(default=False)
    show_dimensions = models.BooleanField(default=True)
    show_gross_weight = models.BooleanField(default=True)
    show_location = models.BooleanField(default=False)
    show_in_stock_flag = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="created_by", related_name="+"
    )

    class Meta:
        db_table = "catalogue_template"

    def __str__(self):
        return self.name


class Catalogue(AppModel):
    catalogue_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=120)
    template = models.ForeignKey(CatalogueTemplate, on_delete=models.PROTECT, db_column="template_id", related_name="catalogues")
    generated_for = models.CharField(max_length=160, blank=True, null=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="generated_by", related_name="+"
    )
    generated_at = models.DateTimeField(default=timezone.now)
    output_url = models.URLField(max_length=500, blank=True, null=True)

    class Meta:
        db_table = "catalogue"

    def __str__(self):
        return self.name


class CatalogueItem(AppModel):
    catalogue = models.ForeignKey(Catalogue, on_delete=models.CASCADE, db_column="catalogue_id", related_name="items")
    piece = models.ForeignKey(Piece, on_delete=models.PROTECT, db_column="jewel_code_id", related_name="catalogue_items")
    sort_order = models.IntegerField(default=0)
    media = models.ForeignKey(
        "mediahub.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, db_column="media_id", related_name="+"
    )

    class Meta:
        db_table = "catalogue_item"
        unique_together = [("catalogue", "piece")]


class JobCard(AppModel):
    OPEN, WITH_VENDOR, RECEIVED, CANCELLED = "OPEN", "WITH_VENDOR", "RECEIVED", "CANCELLED"
    job_card_id = models.BigAutoField(primary_key=True)
    job_no = models.CharField(max_length=40, unique=True)
    style = models.ForeignKey(Style, on_delete=models.PROTECT, db_column="style_id", related_name="job_cards")
    piece = models.ForeignKey(
        Piece, null=True, blank=True, on_delete=models.SET_NULL, db_column="jewel_code_id", related_name="job_cards"
    )
    vendor = models.ForeignKey(
        Vendor, null=True, blank=True, on_delete=models.PROTECT, db_column="vendor_id", related_name="job_cards"
    )
    issued_on = models.DateField()
    expected_on = models.DateField(null=True, blank=True)
    received_on = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[(OPEN, "Open"), (WITH_VENDOR, "With vendor"), (RECEIVED, "Received"), (CANCELLED, "Cancelled")],
        default=OPEN,
    )
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    actual_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    digital_copy_url = models.URLField(max_length=500, blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="created_by", related_name="+"
    )

    class Meta:
        db_table = "job_card"

    def __str__(self):
        return self.job_no


class MaterialInventory(AppModel):
    material = models.ForeignKey(Material, on_delete=models.PROTECT, db_column="material_id", related_name="inventory")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, db_column="location_id", related_name="inventory")
    size_band = models.CharField(max_length=64, default="", blank=True)
    qty_value = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    qty_uom = models.CharField(max_length=8, choices=Uom.choices)
    pcs = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "material_inventory"
        unique_together = [("material", "location", "size_band")]
        verbose_name_plural = "material inventory"


class ActivityLog(AppModel):
    ACTIONS = [
        (a, a.title())
        for a in ["INSERT", "UPDATE", "DELETE", "VIEW_COST", "EXPORT", "LOGIN", "MELT", "REPAIR", "IMPORT", "SALE", "REVERSAL"]
    ]

    log_id = models.BigAutoField(primary_key=True)
    table_name = models.CharField(max_length=64)
    record_pk = models.CharField(max_length=120)
    action = models.CharField(max_length=16, choices=ACTIONS)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="user_id", related_name="+"
    )
    changed_at = models.DateTimeField(default=timezone.now)
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)
    export_id = models.CharField(max_length=64, blank=True, null=True)
    row_count = models.IntegerField(null=True, blank=True)
    detail = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "activity_log"
        ordering = ["-changed_at"]
        indexes = [models.Index(fields=["table_name", "record_pk", "-changed_at"], name="idx_log_rec")]

    def __str__(self):
        return f"{self.action} {self.table_name} {self.record_pk}"
