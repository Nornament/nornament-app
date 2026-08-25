"""The CRM, normalised.

The old CRM stored six tables shaped ``{id, code, customer_id, data JSONB}``
with no foreign keys. Every field the app actually reads is promoted to a real
column here; anything else in the blob lands in ``extra`` so nothing is
dropped, and ``legacy_id`` keeps the original text primary key so the ETL is
re-runnable and a row can always be traced back.

Purchases do not appear here at all: ``customer.data.purchases[]`` unnests into
``stock.Sale`` rows with ``source='CRM'``. One revenue ledger — which is the
whole point of the exercise.
"""
from decimal import Decimal

from django.db import models
from django.utils import timezone


class Timestamped(models.Model):
    # settable rather than auto_now_add/auto_now: the ETL carries the original
    # timestamps across, and an auto column would quietly replace them with the
    # moment of the import.
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True


class LegacyBacked(Timestamped):
    legacy_id = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)
    extra = models.JSONField(
        default=dict, blank=True, help_text="Keys from the original JSONB blob that have no column of their own."
    )

    class Meta:
        abstract = True


class Salesperson(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Customer(LegacyBacked):
    REGULAR, VIP, WHOLESALE = "Regular", "VIP", "Wholesale"
    TEMPERATURES = [("Hot", "Hot"), ("Warm", "Warm"), ("Cold", "Cold")]

    customer_code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=200)
    mobile = models.CharField(max_length=40, blank=True)
    landline = models.CharField(max_length=40, blank=True)
    preferred_phone = models.CharField(max_length=16, default="mobile", blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    location = models.CharField(max_length=120, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    anniversary_date = models.DateField(null=True, blank=True)
    engagement_date = models.DateField(null=True, blank=True)
    wedding_date = models.DateField(null=True, blank=True)

    reference_type = models.CharField(max_length=40, blank=True, default="Walk-in")
    referrer = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="referred_customers"
    )

    customer_type = models.CharField(max_length=32, default=REGULAR, blank=True)
    temperature = models.CharField(max_length=16, choices=TEMPERATURES, default="Warm", blank=True)
    metal_preference = models.JSONField(default=list, blank=True)
    salesperson_preference = models.CharField(max_length=120, blank=True)
    payment_preference = models.CharField(max_length=32, blank=True)
    personal_observation = models.TextField(blank=True)
    client_personal_info = models.TextField(blank=True)

    # Friends of Nornament
    is_fon = models.BooleanField(default=False)
    fon_level = models.PositiveSmallIntegerField(null=True, blank=True)
    fon_parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="fon_children"
    )

    outreach_done = models.BooleanField(default=False)
    outreach_last_date = models.DateField(null=True, blank=True)
    outreach_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.customer_code})"

    @property
    def phone(self):
        return self.mobile or self.landline


class Occasion(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="occasions")
    occasion_type = models.CharField(max_length=60)
    date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["date"]


class RelatedPerson(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="related_people")
    name = models.CharField(max_length=200)
    relation = models.CharField(max_length=60, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)


class Gift(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="gifts")
    date = models.DateField(null=True, blank=True)
    occasion = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-date"]


class PipelineEntity(LegacyBacked):
    """Everything with a code, a customer, a status and a status log."""

    customer = models.ForeignKey(
        Customer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)ss",
        help_text="Nullable on purpose: an orphaned customer_id becomes an exceptions-report row, never a silent drop.",
    )
    status = models.CharField(max_length=40)
    salesperson = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        abstract = True


class StatusEvent(models.Model):
    """One entry of the old ``statusLog[]``, for any pipeline entity."""

    entity_type = models.CharField(max_length=24)
    entity_id = models.IntegerField()
    date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=60)
    note = models.TextField(blank=True)
    by = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]


class Enquiry(PipelineEntity):
    STATUSES = [
        "New Enquiry",
        "Pics Shared",
        "Quote Sent",
        "Design Brief",
        "Design Approved",
        "Order Confirmed",
        "Lost",
    ]

    enquiry_code = models.CharField(max_length=32, unique=True)
    enquiry_date = models.DateField(null=True, blank=True)
    item_of_interest = models.CharField(max_length=255, blank=True)
    estimated_budget = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    metal_type = models.CharField(max_length=60, blank=True)
    stone_details = models.TextField(blank=True)
    design_brief = models.TextField(blank=True)
    client_feedback = models.TextField(blank=True)
    salesperson_feedback = models.TextField(blank=True)
    temperature = models.CharField(max_length=16, default="Warm", blank=True)
    follow_up_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-enquiry_date", "-id"]
        verbose_name_plural = "enquiries"

    def __str__(self):
        return self.enquiry_code


class Order(PipelineEntity):
    STATUSES = [
        "Order Confirmed",
        "Materials Ordered",
        "Designing",
        "Stone Setting",
        "Polishing",
        "Quality Check",
        "Billing",
        "Ready",
        "Delivered",
        "Cancelled",
    ]

    order_code = models.CharField(max_length=32, unique=True)
    order_date = models.DateField(null=True, blank=True)
    item_description = models.TextField(blank=True)
    metal_type = models.CharField(max_length=60, blank=True)
    metal_purity = models.CharField(max_length=32, blank=True)
    stone_details = models.TextField(blank=True)
    diamond_details = models.TextField(blank=True)
    design_brief = models.TextField(blank=True)
    vendor = models.CharField(max_length=120, blank=True)
    weight_grams = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    advance_paid = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    billing_date = models.DateField(null=True, blank=True)
    billing_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    expected_delivery = models.DateField(null=True, blank=True)
    enquiry = models.ForeignKey(Enquiry, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")

    class Meta:
        ordering = ["-order_date", "-id"]

    def __str__(self):
        return self.order_code

    @property
    def balance_due(self):
        total = self.billing_amount or self.total_amount or Decimal("0")
        return total - (self.advance_paid or Decimal("0"))


class Repair(PipelineEntity):
    STATUSES = ["Received", "Diagnosed", "In Workshop", "Ready", "Customer Approved", "Delivered"]

    repair_code = models.CharField(max_length=32, unique=True)
    received_date = models.DateField(null=True, blank=True)
    jewellery_received = models.TextField(blank=True)
    item_description = models.TextField(blank=True)
    issue = models.TextField(blank=True)
    karigar = models.CharField(max_length=120, blank=True)
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    final_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    expected_return = models.DateField(null=True, blank=True)
    actual_return = models.DateField(null=True, blank=True)
    customer_approved = models.BooleanField(default=False)
    customer_approval_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-received_date", "-id"]

    def __str__(self):
        return self.repair_code


class ClientMaterial(PipelineEntity):
    STATUSES = ["Received", "Design Pending", "Design Approved", "Moved to Order", "Moved to Repair", "Returned"]

    cm_code = models.CharField(max_length=32, unique=True)
    received_date = models.DateField(null=True, blank=True)
    jewellery_description = models.TextField(blank=True)
    metal_type = models.CharField(max_length=60, blank=True)
    weight_grams = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    issue = models.TextField(blank=True)
    design_notes = models.TextField(blank=True)
    estimated_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-received_date", "-id"]

    def __str__(self):
        return self.cm_code


class CrmSetting(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.key


class EtlException(models.Model):
    """What the ETL could not place. An orphan is reported, never dropped."""

    run_at = models.DateTimeField(auto_now_add=True)
    entity = models.CharField(max_length=40)
    legacy_id = models.CharField(max_length=64)
    problem = models.CharField(max_length=200)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-run_at", "entity"]

    def __str__(self):
        return f"{self.entity} {self.legacy_id}: {self.problem}"
