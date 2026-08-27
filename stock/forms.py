"""The legacy Stock app's modals, as Django forms.

`newPieceModal`, `editPieceModal`, `matModal`, `locModal`, `catModal`,
`repairModal`, `meltModal` and `pastSaleModal` in
``legacy/Stock/app/nornament.html`` — the same fields, the same required marks,
the same refusals.

Nothing here writes: a form validates, a service in ``stock/services.py``
writes. That is the rule the whole app is built on and it is what keeps the
ledger honest.
"""
from django import forms
from django.utils import timezone

from .enums import MaterialClass, Uom
from .models import (
    Category,
    Collection,
    Location,
    Material,
    MaterialCategory,
    Piece,
    RateChartLine,
    Scenario,
    Style,
    Vendor,
)


class DateInput(forms.DateInput):
    input_type = "date"


class PieceForm(forms.ModelForm):
    """New piece / Edit details.

    ``jewel_code`` is the one field the legacy refused to change once set — it
    is the identity of a physical object, and every movement, sale and BOM row
    points at it.
    """

    class Meta:
        model = Piece
        fields = [
            "jewel_code",
            "style",
            "sub_category",
            "metal_purity",
            "metal_colour",
            "size_label",
            "diamond_quality",
            "measured_gross_wt_gm",
            "length_mm",
            "breadth_mm",
            "height_mm",
            "huid",
            "hallmarked_on",
            "hallmark_centre",
            "fg_date",
            "vendor",
            "scenario",
            "location",
            "received_on",
            "on_website",
            "website_url",
            "remarks",
        ]
        labels = {
            "jewel_code": "Jewel code *",
            "style": "Style / design no *",
            "sub_category": "Sub category",
            "metal_purity": "Karat",
            "metal_colour": "Colour",
            "size_label": "Size",
            "diamond_quality": "Quality",
            "measured_gross_wt_gm": "Gross weight (g)",
            "length_mm": "Length (mm)",
            "breadth_mm": "Breadth (mm)",
            "height_mm": "Height (mm)",
            "huid": "HUID",
            "hallmarked_on": "Hallmarked on",
            "hallmark_centre": "Hallmarking centre",
            "fg_date": "FG date",
            "vendor": "Vendor",
            "scenario": "Pricing scenario",
            "location": "Location *",
            "received_on": "Received on",
            "on_website": "On the website",
            "website_url": "Website URL",
            "remarks": "Remarks",
        }
        widgets = {
            "hallmarked_on": DateInput,
            "fg_date": DateInput,
            "received_on": DateInput,
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ``modelform_factory`` narrows this form to one field for the inline
        # editors on the detail screen, so every touch here has to survive the
        # field simply not being present.
        if "style" in self.fields:
            self.fields["style"].queryset = Style.objects.filter(is_active=True).select_related("category")
            self.fields["style"].label_from_instance = lambda s: f"{s.style_code} — {s.name or ''}".strip(" —")
        if "location" in self.fields:
            self.fields["location"].queryset = Location.objects.filter(is_active=True)
            self.fields["location"].required = True
        if "vendor" in self.fields:
            self.fields["vendor"].queryset = Vendor.objects.filter(is_active=True)
        if "scenario" in self.fields:
            self.fields["scenario"].queryset = Scenario.objects.all()
        if self.instance.pk and "jewel_code" in self.fields:
            # the identity of a physical object, not a label on a record
            self.fields["jewel_code"].disabled = True
            self.fields["jewel_code"].help_text = "Cannot be changed."

    def clean_huid(self):
        # blank must land as NULL, not '': the column is unique and a second
        # empty string collides with the first
        return self.cleaned_data.get("huid") or None


class BomLineForm(forms.Form):
    """One row of the bill of materials editor."""

    material = forms.CharField(label="Material", max_length=64)
    size_band = forms.CharField(label="Size", max_length=64, required=False)
    qty_value = forms.DecimalField(label="Qty", max_digits=12, decimal_places=4, min_value=0)
    qty_uom = forms.ChoiceField(label="Unit", choices=Uom.choices)

    def clean_material(self):
        code = self.cleaned_data["material"].strip()
        if not Material.objects.filter(item_code=code).exists():
            raise forms.ValidationError(f"{code} is not a material code.")
        return code


BomLineFormSet = forms.formset_factory(BomLineForm, extra=0, can_delete=True)


class RepairForm(forms.Form):
    """Send for repair. A repair forks the BOM, so the fault is on the record."""

    fault_description = forms.CharField(
        label="Fault *", widget=forms.Textarea(attrs={"rows": 3, "placeholder": "What is wrong with it?"})
    )
    vendor = forms.ModelChoiceField(
        label="Karigar / workshop", queryset=Vendor.objects.filter(is_active=True), required=False
    )
    return_location = forms.ModelChoiceField(
        label="Return to", queryset=Location.objects.filter(is_active=True), required=False
    )

    def clean_fault_description(self):
        fault = self.cleaned_data["fault_description"].strip()
        if len(fault) < 5:
            raise forms.ValidationError("Say what is actually wrong — this forks the bill of materials.")
        return fault


class MeltForm(forms.Form):
    """Melting is terminal and irreversible, so the reason is not optional.

    Ten characters is the legacy's floor and the database function's floor; it
    exists because "scrap" is not a reason anyone can audit a year later.
    """

    reason = forms.CharField(
        label="Reason *",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Why is this piece being destroyed?"}),
        min_length=10,
    )
    confirm = forms.CharField(label="Type the jewel code to confirm *", max_length=64)

    def __init__(self, piece, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.piece = piece

    def clean_confirm(self):
        typed = self.cleaned_data["confirm"].strip()
        if typed != self.piece.jewel_code:
            raise forms.ValidationError("That is not this piece's jewel code.")
        return typed


class SaleForm(forms.Form):
    """Sell a piece, or backfill one that was sold before the app existed."""

    sold_price = forms.DecimalField(label="Sold price *", max_digits=14, decimal_places=2, min_value=0)
    sold_on = forms.DateField(label="Sold on", widget=DateInput, required=False)
    invoice_no = forms.CharField(label="Invoice no.", max_length=64, required=False)
    customer_name = forms.CharField(label="Customer", max_length=200, required=False)
    customer_phone = forms.CharField(label="Phone", max_length=40, required=False)
    product_category = forms.ChoiceField(
        label="Commission category",
        choices=[("cat1", "Cat 1 – Diamond/Polki"), ("cat2", "Cat 2 – Lab/AD/Gold"), ("cat3", "Cat 3 – Solitaires/Silver/Strings")],
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sold_on"].initial = timezone.localdate()


class MoveForm(forms.Form):
    to_location = forms.ModelChoiceField(
        label="Move to *", queryset=Location.objects.filter(is_active=True)
    )
    reference_no = forms.CharField(label="Reference", max_length=64, required=False)


# ── reference data ───────────────────────────────────────────────────────
class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["code", "name", "code_prefix", "sort_order"]
        labels = {"code": "Code", "name": "Category", "code_prefix": "Code prefix", "sort_order": "Sort"}
        help_texts = {
            "code_prefix": "New jewel codes are built from this. Changing it never moves an existing code.",
        }


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ["code", "name", "kind", "city", "is_active"]
        labels = {"code": "Code", "name": "Name", "kind": "Kind", "city": "City", "is_active": "Active"}


class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ["item_code", "item_name", "size", "mat_class", "category", "default_uom", "metal", "is_active"]
        labels = {
            "item_code": "Code",
            "item_name": "Description",
            "size": "Size",
            "mat_class": "Class",
            "category": "Category",
            "default_uom": "Unit",
            "metal": "Metal",
            "is_active": "Active",
        }
        help_texts = {
            "item_code": "What a bill of materials points at. Changing it moves every line that uses it.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = MaterialCategory.objects.all()

    def clean(self):
        cleaned = super().clean()
        # the table's own check constraint: a METAL material without a metal is
        # a row the database refuses, so say so here rather than 500 later
        if cleaned.get("mat_class") == MaterialClass.METAL and not cleaned.get("metal"):
            self.add_error("metal", "A metal material has to say which metal.")
        return cleaned


class StyleForm(forms.ModelForm):
    class Meta:
        model = Style
        fields = [
            "style_code",
            "name",
            "category",
            "collection",
            "state",
            "story",
            "website_description",
            "designed_on",
            "nos_min_qty",
            "is_active",
        ]
        labels = {
            "style_code": "Style code *",
            "name": "Design name",
            "category": "Category *",
            "collection": "Collection",
            "state": "Design state",
            "story": "Story",
            "website_description": "Website description",
            "designed_on": "Designed on",
            "nos_min_qty": "NOS floor",
            "is_active": "Active",
        }
        widgets = {
            "designed_on": DateInput,
            "story": forms.Textarea(attrs={"rows": 3}),
            "website_description": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "nos_min_qty": "How many live pieces of this design the floor should hold.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.all()
        self.fields["collection"].queryset = Collection.objects.all()
        if self.instance.pk:
            self.fields["style_code"].disabled = True


class RateChartLineForm(forms.ModelForm):
    """One rate on a chart. Metal is not offered: it prices from its live rate."""

    class Meta:
        model = RateChartLine
        fields = ["chart", "material", "size_band", "cost_rate", "sale_rate", "rate_uom"]
        labels = {
            "material": "Material *",
            "size_band": "Size",
            "cost_rate": "Cost rate",
            "sale_rate": "Sale rate",
            "rate_uom": "Unit",
        }
        widgets = {
            "chart": forms.HiddenInput(),
            "rate_uom": forms.Select(choices=[("", "—")] + Uom.choices),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["material"].queryset = Material.objects.exclude(mat_class=MaterialClass.METAL).order_by(
            "item_code"
        )
