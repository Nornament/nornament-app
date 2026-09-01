"""The legacy CRM's modals, as Django forms.

Field-for-field with the React forms in ``legacy/CRM/nornament-crm.html`` —
the same fields, the same labels, the same choice lists. The constants below
are that file's, copied rather than re-derived so a diff against the original
is a diff of two lists rather than a reading exercise.
"""
from django import forms
from django.utils import timezone

from accounts.capabilities import VIEW_COST, VIEW_SALE, VIEW_VENDOR
from stock.models import Sale
from .models import (
    ClientMaterial,
    Customer,
    Enquiry,
    Gift,
    Location,
    Occasion,
    Order,
    OutreachEntry,
    RelatedPerson,
    Repair,
    Salesperson,
)

METALS = ["Gold", "Diamond", "Silver", "Platinum", "Rose Gold", "White Gold", "Polki", "Lab Diamond", "Gemstone"]
PAYMENTS = ["Cash", "Card", "UPI", "Cheque", "EMI", "Mixed"]
REFERENCES = [
    "Instagram",
    "Google",
    "Existing Customer",
    "Salesperson",
    "Employee",
    "Website",
    "Third Party",
    "Walk-in",
]
OCCASION_TYPES = [
    "Wedding",
    "Engagement",
    "Anniversary",
    "Birthday",
    "Baby Shower",
    "Naming Ceremony",
    "Diwali",
    "Dhanteras",
    "Akshaya Tritiya",
    "Festival",
    "Other",
]
METAL_TYPES = [
    "Gold 22k",
    "Gold 18k",
    "Gold 14k",
    "Silver 925",
    "Platinum 950",
    "White Gold 18k",
    "Rose Gold 18k",
]
CUSTOMER_TYPES = ["Regular", "VIP", "Occasional", "Wholesale"]
TEMPERATURES = ["Hot", "Warm", "Cold"]
PRODUCT_CATEGORIES = [
    ("cat1", "Cat 1 – Diamond/Polki"),
    ("cat2", "Cat 2 – Lab/AD/Gold"),
    ("cat3", "Cat 3 – Solitaires/Silver/Strings"),
]


def _choices(values, blank=None):
    rows = [(value, value) for value in values]
    return ([("", blank)] + rows) if blank is not None else rows


class DateInput(forms.DateInput):
    input_type = "date"


def _salesperson_choices():
    return [("", "Select…")] + [(name, name) for name in Salesperson.objects.filter(is_active=True).values_list("name", flat=True)]


def _location_choices():
    names = list(Location.objects.filter(is_active=True).values_list("name", flat=True))
    return [("", "Select…")] + [(name, name) for name in names]


class CustomerForm(forms.ModelForm):
    """The six-tab New/Edit Customer modal.

    ``metal_preference`` is a JSON list on the model and a checkbox group in
    the legacy UI, so it is declared here rather than left to the ModelForm.
    """

    metal_preference = forms.MultipleChoiceField(
        choices=_choices(METALS), required=False, widget=forms.CheckboxSelectMultiple, label="Metal Preference"
    )
    reference_type = forms.ChoiceField(choices=_choices(REFERENCES), required=False, label="Referred By")
    customer_type = forms.ChoiceField(choices=_choices(CUSTOMER_TYPES), required=False, label="Customer Type")
    temperature = forms.ChoiceField(choices=_choices(TEMPERATURES), required=False, label="Temperature")
    payment_preference = forms.ChoiceField(
        choices=_choices(PAYMENTS, blank="Select…"), required=False, label="Payment Preference"
    )

    class Meta:
        model = Customer
        fields = [
            "customer_code",
            "name",
            "mobile",
            "landline",
            "preferred_phone",
            "email",
            "address",
            "location",
            "birth_date",
            "anniversary_date",
            "engagement_date",
            "wedding_date",
            "reference_type",
            "referrer",
            "customer_type",
            "temperature",
            "metal_preference",
            "salesperson_preference",
            "payment_preference",
            "personal_observation",
            "client_personal_info",
            "is_fon",
            "fon_level",
            "fon_parent",
            "outreach_done",
            "outreach_last_date",
            "outreach_notes",
        ]
        labels = {
            "customer_code": "Customer Code",
            "name": "Full Name *",
            "mobile": "Mobile",
            "landline": "Landline",
            "preferred_phone": "Preferred",
            "email": "Email",
            "address": "Address",
            "location": "Location",
            "birth_date": "Birthday",
            "anniversary_date": "Anniversary",
            "engagement_date": "Engagement Date",
            "wedding_date": "Wedding Date",
            "referrer": "Referring Customer",
            "salesperson_preference": "Salesperson Preference",
            "personal_observation": "Personal Observations",
            "client_personal_info": "Client Personal Info",
            "is_fon": "This customer is a Friend of Nornament",
            "fon_level": "FoN Level",
            "fon_parent": "Parent (who introduced them)",
            "outreach_done": "Outreach done",
            "outreach_last_date": "Last outreach",
            "outreach_notes": "Outreach notes",
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
            "personal_observation": forms.Textarea(attrs={"rows": 3}),
            "client_personal_info": forms.Textarea(attrs={"rows": 3}),
            "outreach_notes": forms.Textarea(attrs={"rows": 2}),
            "birth_date": DateInput,
            "anniversary_date": DateInput,
            "engagement_date": DateInput,
            "wedding_date": DateInput,
            "outreach_last_date": DateInput,
            "preferred_phone": forms.Select(choices=[("mobile", "Mobile"), ("landline", "Landline")]),
            "fon_level": forms.Select(choices=[("", "—"), (1, "Level 1"), (2, "Level 2"), (3, "Level 3")]),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["salesperson_preference"] = forms.ChoiceField(
            choices=_salesperson_choices(), required=False, label="Salesperson Preference"
        )
        locations = _location_choices()
        if len(locations) > 1:
            self.fields["location"] = forms.ChoiceField(choices=locations, required=False, label="Location")
        others = Customer.objects.exclude(pk=self.instance.pk) if self.instance.pk else Customer.objects.all()
        self.fields["referrer"].queryset = others
        self.fields["fon_parent"].queryset = others.filter(is_fon=True)
        self.fields["fon_parent"].label_from_instance = lambda c: f"{c.name} ({c.customer_code}) — L{c.fon_level or '?'}"
        self.fields["referrer"].label_from_instance = lambda c: f"{c.name} ({c.customer_code})"

    def clean(self):
        cleaned = super().clean()
        # The legacy form let you tick FoN and leave the level blank, which
        # made the payout run treat them as level 3 by accident.
        if cleaned.get("is_fon") and not cleaned.get("fon_level"):
            self.add_error("fon_level", "A Friend of Nornament needs a level.")
        if not cleaned.get("is_fon"):
            cleaned["fon_level"] = None
            cleaned["fon_parent"] = None
        return cleaned


class PipelineForm(forms.ModelForm):
    """Shared plumbing: the salesperson picker, a customer label that shows the
    code (two customers really do share a name), and the masking rule.

    ``GATED`` is the form-side half of ``stock.masking``: a field a login may
    not read is not merely hidden on the detail screen, it is absent from the
    edit form too. A hidden input still ships the value in the HTML, which is
    the leak the masking test exists to catch.
    """

    GATED = {}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name, permission in self.GATED.items():
            if name in self.fields and not (user and user.has_perm(permission)):
                del self.fields[name]
        if "customer" in self.fields:
            self.fields["customer"].queryset = Customer.objects.all()
            self.fields["customer"].label_from_instance = lambda c: f"{c.name} ({c.customer_code})"
            # the model's help_text explains a schema decision to a developer;
            # it is not a caption for a salesperson filling in a form
            self.fields["customer"].help_text = ""
            self.fields["customer"].empty_label = "Select…"
        if "salesperson" in self.fields:
            self.fields["salesperson"] = forms.ChoiceField(
                choices=_salesperson_choices(), required=False, label="Salesperson"
            )


class EnquiryForm(PipelineForm):
    GATED = {"estimated_budget": VIEW_SALE}

    metal_type = forms.ChoiceField(choices=_choices(METAL_TYPES, blank="Select…"), required=False, label="Metal Type")
    temperature = forms.ChoiceField(choices=_choices(TEMPERATURES), required=False, label="Temperature", initial="Warm")
    status = forms.ChoiceField(choices=_choices(Enquiry.STATUSES), label="Status")

    class Meta:
        model = Enquiry
        fields = [
            "enquiry_code",
            "enquiry_date",
            "customer",
            "item_of_interest",
            "estimated_budget",
            "metal_type",
            "follow_up_date",
            "stone_details",
            "design_brief",
            "client_feedback",
            "salesperson_feedback",
            "temperature",
            "status",
            "salesperson",
        ]
        labels = {
            "enquiry_code": "Enquiry Code",
            "enquiry_date": "Date",
            "customer": "Customer *",
            "item_of_interest": "Item of Interest *",
            "estimated_budget": "Est. Budget (₹)",
            "follow_up_date": "Follow-up Date",
            "stone_details": "Stone / Diamond Details",
            "design_brief": "Design Brief / Notes",
            "client_feedback": "Client Feedback",
            "salesperson_feedback": "Salesperson Feedback",
        }
        widgets = {
            "enquiry_date": DateInput,
            "follow_up_date": DateInput,
            "stone_details": forms.Textarea(attrs={"rows": 2}),
            "design_brief": forms.Textarea(attrs={"rows": 3}),
            "client_feedback": forms.Textarea(attrs={"rows": 2}),
            "salesperson_feedback": forms.Textarea(attrs={"rows": 2}),
        }


class OrderForm(PipelineForm):
    GATED = {
        "vendor": VIEW_VENDOR,
        "total_amount": VIEW_SALE,
        "advance_paid": VIEW_SALE,
        "billing_amount": VIEW_SALE,
        "billing_date": VIEW_SALE,
    }

    metal_type = forms.ChoiceField(choices=_choices(METAL_TYPES, blank="Select…"), required=False, label="Metal Type")
    status = forms.ChoiceField(choices=_choices(Order.STATUSES), label="Status")

    class Meta:
        model = Order
        fields = [
            "order_code",
            "order_date",
            "customer",
            "item_description",
            "metal_type",
            "metal_purity",
            "weight_grams",
            "expected_delivery",
            "stone_details",
            "diamond_details",
            "design_brief",
            "vendor",
            "total_amount",
            "advance_paid",
            "billing_date",
            "billing_amount",
            "status",
            "salesperson",
        ]
        labels = {
            "order_code": "Order Code",
            "order_date": "Order Date",
            "customer": "Customer *",
            "item_description": "Item Description *",
            "metal_purity": "Metal Purity",
            "weight_grams": "Weight (g)",
            "expected_delivery": "Expected Delivery",
            "stone_details": "Stone Details",
            "diamond_details": "Diamond Details",
            "design_brief": "Design Brief",
            "vendor": "Vendor / Supplier",
            "total_amount": "Total Amount (₹)",
            "advance_paid": "Advance Paid (₹)",
            "billing_date": "Billing Date",
            "billing_amount": "Billing Amount (₹)",
        }
        widgets = {
            "order_date": DateInput,
            "expected_delivery": DateInput,
            "billing_date": DateInput,
            "item_description": forms.Textarea(attrs={"rows": 2}),
            "stone_details": forms.Textarea(attrs={"rows": 2}),
            "diamond_details": forms.Textarea(attrs={"rows": 2}),
            "design_brief": forms.Textarea(attrs={"rows": 3}),
        }


class RepairForm(PipelineForm):
    GATED = {"estimated_cost": VIEW_COST, "final_cost": VIEW_COST}

    status = forms.ChoiceField(choices=_choices(Repair.STATUSES), label="Status")

    class Meta:
        model = Repair
        fields = [
            "repair_code",
            "received_date",
            "customer",
            "jewellery_received",
            "item_description",
            "issue",
            "karigar",
            "expected_return",
            "actual_return",
            "estimated_cost",
            "final_cost",
            "customer_approved",
            "customer_approval_date",
            "status",
            "salesperson",
        ]
        labels = {
            "repair_code": "Repair Code",
            "received_date": "Received Date",
            "customer": "Customer *",
            "jewellery_received": "Jewellery Received — Full Description *",
            "item_description": "Item (short label)",
            "issue": "Issue / Problem",
            "karigar": "Karigar / Workshop",
            "expected_return": "Expected Return Date",
            "actual_return": "Actual Return Date",
            "estimated_cost": "Estimated Cost (₹)",
            "final_cost": "Final Cost (₹)",
            "customer_approved": "Customer approved",
            "customer_approval_date": "Approval date",
        }
        widgets = {
            "received_date": DateInput,
            "expected_return": DateInput,
            "actual_return": DateInput,
            "customer_approval_date": DateInput,
            "jewellery_received": forms.Textarea(attrs={"rows": 2}),
            "item_description": forms.Textarea(attrs={"rows": 2}),
            "issue": forms.Textarea(attrs={"rows": 2}),
        }


class ClientMaterialForm(PipelineForm):
    GATED = {"estimated_value": VIEW_SALE}

    metal_type = forms.ChoiceField(choices=_choices(METAL_TYPES, blank="Select…"), required=False, label="Metal Type")
    status = forms.ChoiceField(choices=_choices(ClientMaterial.STATUSES), label="Status")

    class Meta:
        model = ClientMaterial
        fields = [
            "cm_code",
            "received_date",
            "customer",
            "jewellery_description",
            "metal_type",
            "weight_grams",
            "estimated_value",
            "issue",
            "design_notes",
            "status",
            "salesperson",
        ]
        labels = {
            "cm_code": "CM Code",
            "received_date": "Received Date",
            "customer": "Customer *",
            "jewellery_description": "Jewellery Description *",
            "weight_grams": "Weight (g)",
            "estimated_value": "Estimated Value (₹)",
            "issue": "Issue / Problem",
            "design_notes": "Design Notes (if any)",
        }
        widgets = {
            "received_date": DateInput,
            "jewellery_description": forms.Textarea(attrs={"rows": 2}),
            "issue": forms.Textarea(attrs={"rows": 2}),
            "design_notes": forms.Textarea(attrs={"rows": 3}),
        }


class StatusUpdateForm(forms.Form):
    """The "＋ Update" modal on every pipeline detail screen.

    On an order it carries one extra field: the bill. Delivering an order is
    the moment the money is known, and it is the moment the legacy CRM wrote
    the customer's purchase — so this is where it gets typed.
    """

    status = forms.ChoiceField(label="New Status")
    by = forms.ChoiceField(required=False, label="By")
    billing_amount = forms.DecimalField(
        required=False,
        max_digits=14,
        decimal_places=2,
        label="Bill Amount (₹)",
        help_text="Filled in when the order is delivered — it becomes the customer's purchase.",
    )
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3, "placeholder": "What happened?"}), label="Note")

    def __init__(self, statuses, *args, bills=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = _choices(statuses)
        self.fields["by"].choices = _salesperson_choices()
        if not bills:
            del self.fields["billing_amount"]


class PurchaseForm(forms.ModelForm):
    """Add/Edit Purchase — writes a ``stock.Sale`` row, not a CRM row.

    ``category`` is not a Sale column under that name; it maps to
    ``product_category``, which is what FoN commission bands read.
    """

    category = forms.ChoiceField(choices=PRODUCT_CATEGORIES, label="Category")

    class Meta:
        model = Sale
        fields = ["sold_price", "sold_on", "invoice_no", "description", "remarks"]
        labels = {
            "sold_price": "Amount (₹) *",
            "sold_on": "Date *",
            "invoice_no": "Invoice no.",
            "description": "Description",
            "remarks": "Remarks",
        }
        widgets = {
            "sold_on": DateInput,
            "description": forms.Textarea(attrs={"rows": 2}),
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sold_price"].required = True
        self.fields["sold_on"].required = True
        if self.instance and self.instance.pk:
            self.fields["category"].initial = self.instance.product_category or "cat1"
        else:
            self.fields["sold_on"].initial = timezone.localdate()


class CsvUploadForm(forms.Form):
    """The one control both bulk-upload screens need."""

    csv_file = forms.FileField(label="CSV file", widget=forms.FileInput(attrs={"accept": ".csv,text/csv"}))

    def clean_csv_file(self):
        upload = self.cleaned_data["csv_file"]
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError("That file is over 5 MB — split it, or import it in parts.")
        if not upload.name.lower().endswith((".csv", ".txt")):
            raise forms.ValidationError("Save the sheet as CSV first — .xlsx cannot be read here.")
        return upload


class GiftForm(forms.ModelForm):
    occasion = forms.ChoiceField(choices=_choices(OCCASION_TYPES), label="Occasion")

    class Meta:
        model = Gift
        fields = ["occasion", "date", "description", "amount"]
        labels = {"date": "Date *", "description": "Item", "amount": "Amount (₹)"}
        widgets = {"date": DateInput}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].required = True


class OccasionForm(forms.ModelForm):
    occasion_type = forms.ChoiceField(choices=_choices(OCCASION_TYPES), label="Occasion")

    class Meta:
        model = Occasion
        fields = ["occasion_type", "date", "note"]
        labels = {"date": "Date *", "note": "Observations"}
        widgets = {"date": DateInput}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].required = True


class RelatedPersonForm(forms.ModelForm):
    class Meta:
        model = RelatedPerson
        fields = ["name", "relation", "phone", "birth_date", "note"]
        labels = {"name": "Name *", "relation": "Relation", "phone": "Phone", "birth_date": "Birthday", "note": "Note"}
        widgets = {"birth_date": DateInput}


class OutreachForm(forms.ModelForm):
    class Meta:
        model = OutreachEntry
        fields = ["type", "date", "outcome", "notes", "next_follow_up", "by"]
        labels = {
            "type": "Type",
            "date": "Date *",
            "outcome": "Outcome",
            "notes": "Notes",
            "next_follow_up": "Next follow-up",
            "by": "By",
        }
        widgets = {"date": DateInput, "next_follow_up": DateInput, "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].initial = timezone.localdate()
        self.fields["by"] = forms.ChoiceField(choices=_salesperson_choices(), required=False, label="By")


class SalespersonForm(forms.ModelForm):
    class Meta:
        model = Salesperson
        fields = ["name", "is_active"]
        labels = {"name": "Salesperson", "is_active": "Active"}


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name", "is_active"]
        labels = {"name": "Location", "is_active": "Active"}
