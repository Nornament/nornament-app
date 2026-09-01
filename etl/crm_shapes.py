"""Turning one CRM JSONB blob into columns.

Every key the old React app reads gets a column; anything else survives in
``extra``. The mapping is spelled out rather than inferred so that a key
appearing in one customer's blob and not another's cannot quietly change the
shape of the import.
"""
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

#: blob key -> model field, for keys that map straight across
CUSTOMER_FIELDS = {
    "name": "name",
    "email": "email",
    "address": "address",
    "location": "location",
    "personalObservation": "personal_observation",
    "clientPersonalInfo": "client_personal_info",
    "salespersonPreference": "salesperson_preference",
    "paymentPreference": "payment_preference",
    "customerType": "customer_type",
    "temperature": "temperature",
}
CUSTOMER_DATES = {
    "birthDate": "birth_date",
    "anniversaryDate": "anniversary_date",
    "engagementDate": "engagement_date",
    "weddingDate": "wedding_date",
}
#: keys consumed by columns or by their own tables — not overflow
CUSTOMER_CONSUMED = set(CUSTOMER_FIELDS) | set(CUSTOMER_DATES) | {
    "phone",
    "referenceFrom",
    "fonData",
    "outreach",
    "metalPreference",
    "purchases",
    "occasions",
    "relatedPeople",
    "gifting",
    "outreachLog",
    "statusLog",
    "media",
    "createdAt",
    "updatedAt",
    "id",
    "customerCode",
    "photo",
}


def blob_of(row):
    """The ``data`` column as a dict.

    Django hands raw ``jsonb`` back as text on purpose — it registers a no-op
    loader so JSONField can apply its own decoder — so a cursor read has to
    decode it here.
    """
    raw = row.get("data")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw or {}


#: every shape a date reaches the blob in. ISO is what ``<input type=date>``
#: and ``todayDate()`` write, so it is tried first; the rest come from the
#: invoice OCR (``\d{1,2}[/-.]\d{1,2}[/-.]\d{2,4}``) and from CSV bulk
#: uploads, where Excel writes whatever the operator's locale says. Only
#: accepting ISO is what dropped those purchases on the floor.
#:
#: Day-first, because this is an Indian shop: ``04/08/2026`` is 4 August. A
#: month-first reading would silently move a purchase into the wrong month and
#: the wrong financial year, which is worse than the value being missing.
DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d.%m.%y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
)


def date_or_none(value):
    """Whatever the blob holds, as a ``date`` — or ``None`` if it is nothing.

    ``None`` here means "unreadable", and every caller that can lose a row
    over it is expected to report the row rather than skip it.
    """
    if value in (None, "", "-"):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # an ISO timestamp: keep the date half, drop the time and the zone
    head = text[:10]
    try:
        return datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def money_or_none(value):
    if value in (None, "", "-"):
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("₹", "").strip())
    except (InvalidOperation, TypeError, ValueError):
        return None


def without_empty_timestamps(fields):
    """A dump with no timestamp falls back to the model default rather than null."""
    return {key: value for key, value in fields.items() if not (key in ("created_at", "updated_at") and value is None)}


def overflow(blob, consumed):
    return {key: value for key, value in blob.items() if key not in consumed}


def customer_from_blob(row):
    """Row plus blob to columns. The row's own timestamps come across too —
    when a customer was created is part of the record, not an import detail."""
    blob = blob_of(row)
    phone = blob.get("phone") or {}
    fon = blob.get("fonData") or {}
    outreach = blob.get("outreach") or {}
    reference = blob.get("referenceFrom") or {}
    fields = {
        "legacy_id": row["id"],
        "created_at": row.get("created_at") or None,
        "updated_at": row.get("updated_at") or None,
        "customer_code": row.get("customer_code") or blob.get("customerCode") or row["id"],
        "mobile": phone.get("mobile") or "",
        "landline": phone.get("landline") or "",
        "preferred_phone": phone.get("preferred") or "mobile",
        "reference_type": reference.get("type") or "",
        "is_fon": bool(fon.get("isFoN")),
        "fon_level": fon.get("level") or None,
        "outreach_done": bool(outreach.get("done")),
        "outreach_last_date": date_or_none(outreach.get("lastDate")),
        "outreach_notes": outreach.get("notes") or "",
        "metal_preference": blob.get("metalPreference") or [],
        "extra": overflow(blob, CUSTOMER_CONSUMED),
    }
    for key, field in CUSTOMER_FIELDS.items():
        fields[field] = blob.get(key) or ""
    for key, field in CUSTOMER_DATES.items():
        fields[field] = date_or_none(blob.get(key))
    return without_empty_timestamps(fields)


CATEGORIES = ("cat1", "cat2", "cat3")


class _Statuses:
    """``crm.models``' own stage lists, read lazily.

    Lazily because this module is plain data-shaping and is imported by tests
    that never set Django up; the lists still live in one place, on the models
    the app renders from, so a stage added there is a stage the ETL accepts.
    """

    def __getitem__(self, kind):
        from crm.models import ClientMaterial, Enquiry, Order, Repair

        return {
            "enquiry": Enquiry,
            "order": Order,
            "repair": Repair,
            "clientmaterial": ClientMaterial,
        }[kind].STATUSES


STATUSES = _Statuses()


def category_or_none(value):
    """``purchases[].category`` as one of ``cat1``/``cat2``/``cat3``.

    The CRM's own bulk upload never ran its ``catFromStr`` over the CSV, so a
    purchase imported that way carries the label the operator typed —
    ``Cat 1 – Diamond/Polki`` — not the key. Matching the label back to the key
    here is what puts the money in the right FoN band instead of defaulting it
    into cat3.
    """
    if not value:
        return None
    text = str(value).strip().lower()
    if text in CATEGORIES:
        return text
    if "cat 1" in text or "cat1" in text or "diamond" in text or "polki" in text:
        return "cat1"
    if "cat 2" in text or "cat2" in text or "lab" in text or "gold" in text:
        return "cat2"
    if "cat 3" in text or "cat3" in text or "solitaire" in text or "silver" in text or "string" in text:
        return "cat3"
    return None


def purchases_from_blob(blob, row=None):
    """``purchases[]`` as ``stock.Sale`` kwargs — and what could not be shaped.

    Returns ``(usable, rejected)``. Nothing is dropped on the floor: a
    purchase with no readable amount or no readable date comes back in
    ``rejected`` so ``load_legacy`` can write it to ``EtlException`` and
    somebody can go and fix the source row. Silently skipping them is how a
    customer's purchase history came up short in the new app while the ETL
    reported success.

    The date falls back to the customer row's own ``created_at`` — the column,
    not ``blob["createdAt"]``, which the legacy app strips out of ``data``
    before every save and which was therefore always absent.
    """
    fallback = date_or_none((row or {}).get("created_at"))
    usable, rejected = [], []
    for index, purchase in enumerate(blob.get("purchases") or []):
        purchase = purchase if isinstance(purchase, dict) else {}
        legacy_id = purchase.get("id") or f"p{index}"
        amount = money_or_none(purchase.get("amount"))
        if amount is None:
            rejected.append({"legacy_id": legacy_id, "problem": "purchase has no readable amount", "purchase": purchase})
            continue
        sold_on = date_or_none(purchase.get("date")) or fallback
        if sold_on is None:
            rejected.append({"legacy_id": legacy_id, "problem": "purchase has no readable date", "purchase": purchase})
            continue
        usable.append(
            {
                "legacy_id": legacy_id,
                "sold_on": sold_on,
                "sold_price": amount,
                "product_category": category_or_none(purchase.get("category")),
                "invoice_no": purchase.get("invoiceNo") or None,
                "description": purchase.get("description") or None,
                "remarks": purchase.get("remarks") or None,
                # the legacy ``updateOrder`` stamped this on a purchase it
                # created from a delivered order; carrying it across is what
                # stops the new app opening a second purchase for that order.
                "source_order_legacy_id": purchase.get("sourceOrderId") or None,
            }
        )
    return usable, rejected


def status_events_from_blob(blob, entity_type, entity_id):
    for event in blob.get("statusLog") or []:
        yield {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "date": date_or_none(event.get("date")),
            "status": event.get("status") or "",
            "note": event.get("note") or "",
            "by": event.get("by") or "",
        }


def normalise_status(value, statuses):
    """A blob's ``status`` matched to one the new app knows.

    Returns ``(status, problem)``. Whitespace and case are forgiven — the
    stored value came out of a ``<select>`` but has been through a CSV import
    and a hand-edited row or two since. A value that matches nothing is
    returned *as it stands*, with a problem for the caller to report: renaming
    it to something plausible would move the record to a stage nobody put it
    at, and dropping it would hide the record from the board entirely.
    """
    text = str(value or "").strip()
    if not text:
        return "", "no status on the record"
    collapsed = " ".join(text.split())
    for status in statuses:
        if collapsed.casefold() == status.casefold():
            return status, None
    return collapsed, f"status {collapsed!r} is not one of this pipeline's stages"


def _pipeline_common(row, code_key, code_field, blob_keys, statuses=(), problems=None):
    blob = blob_of(row)
    status, problem = normalise_status(blob.get("status"), statuses)
    if problem is not None and problems is not None:
        problems.append({"legacy_id": row["id"], "problem": problem, "detail": {"status": blob.get("status")}})
    fields = {
        "legacy_id": row["id"],
        "created_at": row.get("created_at") or None,
        "updated_at": row.get("updated_at") or None,
        code_field: row.get(code_key) or row["id"],
        "status": status,
        "salesperson": blob.get("salesperson") or blob.get("salespersonName") or "",
        "notes": blob.get("notes") or "",
        "extra": overflow(blob, set(blob_keys) | {"statusLog", "media", "status", "createdAt", "updatedAt", "id", "customerId", "notes", "salesperson"}),
    }
    return blob, fields


ENQUIRY_KEYS = {
    "enquiryDate": ("enquiry_date", date_or_none),
    "itemOfInterest": ("item_of_interest", str),
    "estimatedBudget": ("estimated_budget", money_or_none),
    "metalType": ("metal_type", str),
    "stoneDetails": ("stone_details", str),
    "designBrief": ("design_brief", str),
    "clientFeedback": ("client_feedback", str),
    "salespersonFeedback": ("salesperson_feedback", str),
    "temperature": ("temperature", str),
    "followUpDate": ("follow_up_date", date_or_none),
}

ORDER_KEYS = {
    "orderDate": ("order_date", date_or_none),
    "itemDescription": ("item_description", str),
    "metalType": ("metal_type", str),
    "metalPurity": ("metal_purity", str),
    "stoneDetails": ("stone_details", str),
    "diamondDetails": ("diamond_details", str),
    "designBrief": ("design_brief", str),
    "vendor": ("vendor", str),
    "weightGrams": ("weight_grams", money_or_none),
    "totalAmount": ("total_amount", money_or_none),
    "advancePaid": ("advance_paid", money_or_none),
    "billingDate": ("billing_date", date_or_none),
    "billingAmount": ("billing_amount", money_or_none),
    "expectedDelivery": ("expected_delivery", date_or_none),
}

REPAIR_KEYS = {
    "receivedDate": ("received_date", date_or_none),
    "jewelleryReceived": ("jewellery_received", str),
    "itemDescription": ("item_description", str),
    "issue": ("issue", str),
    "karigar": ("karigar", str),
    "estimatedCost": ("estimated_cost", money_or_none),
    "finalCost": ("final_cost", money_or_none),
    "expectedReturn": ("expected_return", date_or_none),
    "actualReturn": ("actual_return", date_or_none),
    "customerApprovalDate": ("customer_approval_date", date_or_none),
}

CLIENT_MATERIAL_KEYS = {
    "receivedDate": ("received_date", date_or_none),
    "jewelleryDescription": ("jewellery_description", str),
    "metalType": ("metal_type", str),
    "weightGrams": ("weight_grams", money_or_none),
    "issue": ("issue", str),
    "designNotes": ("design_notes", str),
    "estimatedValue": ("estimated_value", money_or_none),
}


def _apply(blob, fields, keys):
    for key, (field, cast) in keys.items():
        value = blob.get(key)
        if cast is str:
            fields[field] = value or ""
        else:
            fields[field] = cast(value)
    return without_empty_timestamps(fields)


def enquiry_from_blob(row, problems=None):
    blob, fields = _pipeline_common(row, "enquiry_code", "enquiry_code", ENQUIRY_KEYS, STATUSES["enquiry"], problems)
    fields = _apply(blob, fields, ENQUIRY_KEYS)
    fields["temperature"] = blob.get("temperature") or "Warm"
    return fields


def order_from_blob(row, problems=None):
    blob, fields = _pipeline_common(row, "order_code", "order_code", ORDER_KEYS, STATUSES["order"], problems)
    return _apply(blob, fields, ORDER_KEYS)


def repair_from_blob(row, problems=None):
    blob, fields = _pipeline_common(row, "repair_code", "repair_code", REPAIR_KEYS, STATUSES["repair"], problems)
    fields = _apply(blob, fields, REPAIR_KEYS)
    fields["customer_approved"] = bool(blob.get("customerApproved"))
    return fields


def client_material_from_blob(row, problems=None):
    blob, fields = _pipeline_common(row, "cm_code", "cm_code", CLIENT_MATERIAL_KEYS, STATUSES["clientmaterial"], problems)
    return _apply(blob, fields, CLIENT_MATERIAL_KEYS)


#: every key a legacy CRM row could hold an image under. The React app read
#: ``media[0].data || photos[0] || beforePhoto``, and the customer avatar sat on
#: ``photo`` — so all four shapes have to be walked or images go missing.
MEDIA_KEYS = ("media", "photos", "photo", "beforePhoto", "afterPhoto")


def _data_uri_parts(value):
    """``data:image/jpeg;base64,…`` -> ``(mime, bytes)``, or ``None``.

    Anything that is not a base64 data URI — an http URL, a stray string — is
    returned as ``None`` so the caller can report it rather than guess.

    A type the app would not serve is refused here too. ``text/html`` and
    ``image/svg+xml`` can carry script, and these bytes are served from the
    app's own origin until they reach the bucket; keeping them out entirely is
    cheaper than remembering to be careful later.
    """
    import base64

    from mediahub.storage import is_serveable

    if not isinstance(value, str) or not value.startswith("data:"):
        return None
    header, _, payload = value.partition(",")
    if not payload or ";base64" not in header:
        return None
    mime = header[5:].split(";", 1)[0] or "application/octet-stream"
    if not is_serveable(mime):
        return None
    try:
        return mime, base64.b64decode(payload, validate=False)
    except Exception:
        return None


def media_from_blob(blob):
    """Every image on one CRM row, as ``dict`` kwargs for ``MediaAsset``.

    The CRM never used object storage: its photos are base64 data URIs inside
    the JSONB. They come across as bytes on the row, which
    ``manage.py push_inline_media`` later moves into the bucket.
    """
    import hashlib

    out = []
    for key in MEDIA_KEYS:
        raw = blob.get(key)
        if raw is None:
            continue
        entries = raw if isinstance(raw, list) else [raw]
        for index, entry in enumerate(entries):
            if isinstance(entry, dict):
                value, name = entry.get("data"), entry.get("name")
                legacy_id = entry.get("id")
                kind = "VIDEO" if entry.get("type") == "video" else "PHOTO"
            else:
                value, name, legacy_id, kind = entry, None, None, "PHOTO"
            parts = _data_uri_parts(value)
            if parts is None:
                continue
            mime, payload = parts
            out.append(
                {
                    "kind": "VIDEO" if mime.startswith("video/") else kind,
                    "file_name": name or f"{key}-{index + 1}",
                    "mime_type": mime,
                    "inline_data": payload,
                    "bytes": len(payload),
                    "file_size_kb": int(len(payload) / 1024) or None,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "rank_order": (index + 1) * 10,
                    "caption": None if key in ("media", "photos", "photo") else key,
                    "storage_provider": "INLINE",
                    "legacy_id": legacy_id,
                }
            )
    return out
