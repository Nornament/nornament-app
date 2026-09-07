"""Template helpers the CRM screens need.

``status_class``, ``initials`` and ``inr`` are the legacy CRM's ``statusClass``,
``ini`` and ``inr`` from ``legacy/CRM/nornament-crm.html``, ported so the
templates can render the same class names and the same number formatting the
React app did.
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def lookup(mapping, key):
    """``{{ payout.billing|lookup:key }}`` — a dict lookup by variable key.

    Django templates cannot index a dict with a variable; the FoN tables are
    driven by the category list, so they need this.
    """
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def wa_number(phone):
    """A phone as wa.me digits — the legacy CRM's ``waNumber``, ported as-is.

    Digits only; an 11-digit number loses a leading 0; a bare 10-digit local
    number gains the 91 country code.
    """
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    return digits


#: the legacy ``statusClass`` map, verbatim. One map for every entity — an
#: enquiry's "Order Confirmed" and an order's wear the same pill.
STATUS_CLASSES = {
    "New Enquiry": "s-enquiry",
    "Pics Shared": "s-quote",
    "Quote Sent": "s-quote",
    "Design Brief": "s-dbr",
    "Design Approved": "s-dap",
    "Order Confirmed": "s-conf",
    "Materials Ordered": "s-mat",
    "Designing": "s-designing",
    "Stone Setting": "s-stone",
    "Polishing": "s-polish",
    "Quality Check": "s-qc",
    "Billing": "s-billing",
    "Ready": "s-ready",
    "Delivered": "s-delivered",
    "Cancelled": "s-cancelled",
    "Received": "s-received",
    "Diagnosed": "s-designing",
    "In Workshop": "s-karigar",
    "Customer Approved": "s-approved",
    "Design Pending": "s-dbr",
    "Moved to Order": "s-conf",
    "Moved to Repair": "s-conf",
    "Returned": "s-delivered",
    "Lost": "s-cancelled",
}


@register.filter
def status_class(status):
    return STATUS_CLASSES.get(status, "br")


@register.filter
def initials(name):
    """``ini`` — first letters of each word, upper, two at most."""
    if not name:
        return "?"
    return "".join(word[0] for word in str(name).split() if word).upper()[:2] or "?"


@register.filter
def inr(amount):
    """``₹`` plus Indian digit grouping — ``toLocaleString('en-IN')``.

    Lakh/crore grouping, not thousands: 1234567 renders ₹12,34,567. Rounded to
    whole rupees, which is what every legacy screen showed.
    """
    try:
        value = Decimal(amount if amount is not None else 0)
    except (TypeError, ValueError, InvalidOperation):
        return "₹0"
    sign = "-" if value < 0 else ""
    digits = f"{abs(value):.0f}"
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            head, group = head[:-2], head[-2:]
            groups.insert(0, group)
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"₹{sign}{digits}"


@register.filter
def first_word(value):
    """``c.name.split(' ')[0]`` — the first name on a pipeline card."""
    return str(value or "").split(" ")[0]


@register.filter
def pipeline_title(row):
    """Whatever the entity calls its one-line description.

    The legacy card read ``itemOfInterest || itemDescription ||
    jewelleryDescription``; the four models spell it four ways too.
    """
    for field in ("item_of_interest", "item_description", "jewellery_description"):
        value = getattr(row, field, None)
        if value:
            return value
    return ""


@register.filter
def pipeline_code(row):
    for field in ("enquiry_code", "order_code", "repair_code", "cm_code", "customer_code"):
        value = getattr(row, field, None)
        if value:
            return value
    return ""


@register.filter
def pipeline_subtitle(row):
    """The legacy card's second line, one ``getSubtitle`` per module.

    An enquiry showed its budget, else its date; an order its expected
    delivery; a repair its expected return; a client material the date it
    was received. ``fmtD`` printed dates as ``18 Jun 2026`` or an em dash.
    """
    from django.utils.dateformat import format as date_format

    budget = getattr(row, "estimated_budget", None)
    if budget:
        return inr(budget)
    for field in ("expected_delivery", "expected_return", "received_date", "enquiry_date"):
        value = getattr(row, field, None)
        if value:
            return date_format(value, "d M Y")
    return "—"


@register.filter
def next_status(status, statuses):
    """The stage after this one, or '' at the end — the kanban's › button."""
    statuses = list(statuses)
    if status in statuses:
        index = statuses.index(status)
        if index + 1 < len(statuses):
            return statuses[index + 1]
    return ""


@register.filter
def prev_status(status, statuses):
    statuses = list(statuses)
    if status in statuses:
        index = statuses.index(status)
        if index > 0:
            return statuses[index - 1]
    return ""


@register.filter
def wish_text(first_name, occasion):
    """``waMsgOccasion`` — the prefilled WhatsApp greeting, word for word."""
    occasion = "your birthday" if occasion == "birthday" else (
        "your anniversary" if occasion == "anniversary" else f"your {occasion}"
    )
    return (
        f"Hello {first_name}, warm wishes from Nornament! With {occasion} coming up, "
        "we would love to craft something special for the occasion. May we share a few ideas?"
    )


@register.filter
def follow_up_text(customer_name):
    """``waMsgFollowUp`` for the lead-gap rows."""
    first = str(customer_name or "").split(" ")[0]
    return (
        f"Hello {first}, this is Nornament. It has been a while — we have some new pieces "
        "we think you will love. May we share a few pictures?"
    )


@register.filter
def paired_fields(form):
    """Group a form's fields for the two-column pipeline layout.

    Short controls pair up; anything rendered as a textarea takes the full
    width on its own. Yields ``(is_wide, [fields])`` so the template stays a
    plain loop rather than four hand-written column layouts, one per module.
    """
    from django import forms as django_forms

    rows, pending = [], []
    for field in form:
        if isinstance(field.field.widget, django_forms.Textarea):
            if pending:
                rows.append((False, pending))
                pending = []
            rows.append((True, [field]))
            continue
        pending.append(field)
        if len(pending) == 2:
            rows.append((False, pending))
            pending = []
    if pending:
        rows.append((False, pending))
    return rows
