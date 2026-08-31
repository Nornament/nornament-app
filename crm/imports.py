"""Bulk CSV import — the legacy ``MassUploadModal`` and ``PurchaseBulkUpload``.

Both worked the same way: drop a CSV, the app guesses which column is which,
you see what it understood, and only then does it write. That two-step is the
whole point — a spreadsheet from a shop floor never has the headers you asked
for, and a silent import of the wrong column is worse than no import.

Header matching is deliberately loose (case, spaces and punctuation ignored,
several aliases per field) because the legacy did the same and the files it was
fed are the files this will be fed.
"""
import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

MAX_ROWS = 2000


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _pick(row, aliases):
    """First non-empty cell whose header matches one of ``aliases``."""
    for alias in aliases:
        key = _norm(alias)
        if key in row and str(row[key]).strip():
            return str(row[key]).strip()
    return ""


def text_of(upload):
    raw = upload.read()
    return raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw


def read_csv(raw):
    """Rows as ``{normalised_header: value}``, plus the headers as written.

    Takes the CSV as text — the confirm step posts back the same text it was
    shown, so what is written is exactly what was previewed, with no server-side
    state parked between two requests.

    Accepts a BOM (Excel writes one) and either comma or semicolon delimiters.
    """
    if not isinstance(raw, str):
        raw = text_of(raw)
    # the confirm step posts the text back, BOM and all, so strip it here
    # rather than only on the decode path
    raw = raw.lstrip("\ufeff")
    sample = raw[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(raw), delimiter=delimiter)
    headers = reader.fieldnames or []
    rows = []
    for index, line in enumerate(reader):
        if index >= MAX_ROWS:
            break
        if not any((value or "").strip() for value in line.values()):
            continue
        rows.append({_norm(k): (v or "") for k, v in line.items() if k is not None})
    return headers, rows


DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y")


def parse_date(text):
    text = (text or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(text):
    text = re.sub(r"[^\d.\-]", "", (text or "").replace(",", ""))
    if not text or text in {"-", "."}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


# ── customers ────────────────────────────────────────────────────────────
CUSTOMER_TEMPLATE = [
    "Name", "Mobile", "Customer Code", "Email", "Address", "Location",
    "Birth Date", "Anniversary", "Source", "Observation", "Type", "Temperature",
]

CUSTOMER_FIELDS = {
    "name": ["name", "customer name", "full name", "client name"],
    "mobile": ["mobile", "phone", "mobile no", "contact", "phone number"],
    "customer_code": ["customer code", "code", "cust code"],
    "email": ["email", "email id", "e-mail"],
    "address": ["address"],
    "location": ["location", "city", "branch", "showroom"],
    "birth_date": ["birth date", "birthday", "dob", "date of birth"],
    "anniversary_date": ["anniversary", "anniversary date"],
    "reference_type": ["source", "reference", "referred by", "reference from"],
    "personal_observation": ["observation", "notes", "remarks", "personal observation"],
    "customer_type": ["type", "customer type"],
    "temperature": ["temperature", "temp"],
}


def preview_customers(rows):
    """What the file means, before anything is written."""
    from .models import Customer

    seen_codes = set(Customer.objects.values_list("customer_code", flat=True))
    seen_mobiles = {m for m in Customer.objects.values_list("mobile", flat=True) if m}
    out = []
    for line in rows:
        parsed = {field: _pick(line, aliases) for field, aliases in CUSTOMER_FIELDS.items()}
        parsed["birth_date"] = parse_date(parsed["birth_date"])
        parsed["anniversary_date"] = parse_date(parsed["anniversary_date"])
        problem = ""
        if not parsed["name"]:
            problem = "no name — skipped"
        elif parsed["customer_code"] and parsed["customer_code"] in seen_codes:
            problem = f"{parsed['customer_code']} already exists — skipped"
        elif parsed["mobile"] and parsed["mobile"] in seen_mobiles:
            problem = f"mobile {parsed['mobile']} already on file — skipped"
        else:
            if parsed["customer_code"]:
                seen_codes.add(parsed["customer_code"])
            if parsed["mobile"]:
                seen_mobiles.add(parsed["mobile"])
        out.append({"parsed": parsed, "problem": problem})
    return out


def import_customers(preview):
    """Write the rows the preview did not object to. Returns (created, skipped)."""
    from . import services
    from .models import Customer

    created = 0
    for entry in preview:
        if entry["problem"]:
            continue
        parsed = dict(entry["parsed"])
        code = parsed.pop("customer_code", "") or services.next_code(Customer, "customer")
        now = timezone.now()
        Customer.objects.create(
            customer_code=code,
            created_at=now,
            updated_at=now,
            reference_type=parsed.pop("reference_type", "") or "Walk-in",
            customer_type=parsed.pop("customer_type", "") or Customer.REGULAR,
            temperature=parsed.pop("temperature", "") or "Warm",
            **{k: v for k, v in parsed.items() if v not in ("", None)},
        )
        created += 1
    return created, sum(1 for e in preview if e["problem"])


# ── purchases ────────────────────────────────────────────────────────────
PURCHASE_TEMPLATE = ["Customer Code", "Date", "Amount", "Category", "Description", "Invoice No", "Remarks"]

PURCHASE_FIELDS = {
    "customer_code": ["customer code", "code", "cust code", "customer"],
    "mobile": ["mobile", "phone", "contact"],
    "sold_on": [
        "date", "purchase date", "order date", "bill date", "invoice date",
        "transaction date", "sale date",
    ],
    "sold_price": [
        "amount", "bill amount", "invoice amount", "net amount", "sale amount",
        "value", "total",
    ],
    "category": ["category", "item type", "item category", "cat"],
    "description": ["description", "item name", "product name", "item description", "item"],
    "invoice_no": ["invoice no", "invoice", "bill no", "invoice number"],
    "remarks": ["remarks", "note", "notes", "comment"],
}

#: the legacy `catFromStr` — cat1 diamond/polki, cat2 lab/AD/gold, cat3 the rest
CATEGORY_WORDS = (
    ("cat1", ("diamond", "polki", "cat 1", "cat1")),
    ("cat2", ("lab", "ad ", "american", "gold", "cat 2", "cat2")),
    ("cat3", ("solitaire", "silver", "string", "cat 3", "cat3")),
)


def category_from(text):
    lowered = f" {(text or '').lower()} "
    for key, words in CATEGORY_WORDS:
        if any(word in lowered for word in words):
            return key
    return "cat3"


def preview_purchases(rows):
    from .models import Customer

    by_code = {c.customer_code: c for c in Customer.objects.all()}
    by_mobile = {c.mobile: c for c in Customer.objects.exclude(mobile="")}
    out = []
    for line in rows:
        parsed = {field: _pick(line, aliases) for field, aliases in PURCHASE_FIELDS.items()}
        customer = by_code.get(parsed["customer_code"]) or by_mobile.get(parsed["mobile"])
        amount = parse_amount(parsed["sold_price"])
        when = parse_date(parsed["sold_on"])
        category = parsed["category"] if parsed["category"] in {"cat1", "cat2", "cat3"} else category_from(
            f"{parsed['category']} {parsed['description']}"
        )
        problem = ""
        if customer is None:
            problem = "no customer matched that code or mobile — skipped"
        elif amount is None:
            problem = "amount is not a number — skipped"
        elif when is None:
            problem = "date could not be read — skipped"
        out.append(
            {
                "customer": customer,
                "sold_on": when,
                "sold_price": amount,
                "category": category,
                "description": parsed["description"],
                "invoice_no": parsed["invoice_no"],
                "remarks": parsed["remarks"],
                "problem": problem,
            }
        )
    return out


def import_purchases(preview):
    from . import services

    created = 0
    for entry in preview:
        if entry["problem"]:
            continue
        services.record_purchase(
            entry["customer"],
            sold_on=entry["sold_on"],
            sold_price=entry["sold_price"],
            product_category=entry["category"],
            description=entry["description"] or None,
            invoice_no=entry["invoice_no"] or None,
            remarks=entry["remarks"] or None,
        )
        created += 1
    return created, sum(1 for e in preview if e["problem"])


def template_csv(header):
    buffer = io.StringIO()
    csv.writer(buffer).writerow(header)
    return buffer.getvalue()


def demo():  # pragma: no cover - a runnable check, not a test suite
    assert _norm(" Bill Amount ") == "billamount"
    assert parse_date("14/08/2026") == date(2026, 8, 14)
    assert parse_date("2026-08-14") == date(2026, 8, 14)
    assert parse_date("nonsense") is None
    assert parse_amount("₹ 1,20,500.50") == Decimal("120500.50")
    assert parse_amount("") is None
    assert category_from("Polki necklace") == "cat1"
    assert category_from("22k gold bangle") == "cat2"
    assert category_from("silver anklet") == "cat3"
    assert category_from("") == "cat3"
    print("crm.imports demo ok")


if __name__ == "__main__":  # pragma: no cover
    demo()
