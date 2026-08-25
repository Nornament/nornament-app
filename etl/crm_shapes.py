"""Turning one CRM JSONB blob into columns.

Every key the old React app reads gets a column; anything else survives in
``extra``. The mapping is spelled out rather than inferred so that a key
appearing in one customer's blob and not another's cannot quietly change the
shape of the import.
"""
import json
from datetime import datetime
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


def date_or_none(value):
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
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


def purchases_from_blob(blob):
    """Each ``purchases[]`` entry, shaped as a ``stock.Sale`` kwargs dict."""
    out = []
    for index, purchase in enumerate(blob.get("purchases") or []):
        amount = money_or_none(purchase.get("amount"))
        if amount is None:
            continue
        category = purchase.get("category")
        out.append(
            {
                "legacy_id": purchase.get("id") or f"p{index}",
                "sold_on": date_or_none(purchase.get("date")) or date_or_none(blob.get("createdAt")),
                "sold_price": amount,
                "product_category": category if category in ("cat1", "cat2", "cat3") else None,
                "invoice_no": purchase.get("invoiceNo") or None,
                "description": purchase.get("description") or purchase.get("remarks") or None,
            }
        )
    return [row for row in out if row["sold_on"]]


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


def _pipeline_common(row, code_key, code_field, blob_keys):
    blob = blob_of(row)
    fields = {
        "legacy_id": row["id"],
        "created_at": row.get("created_at") or None,
        "updated_at": row.get("updated_at") or None,
        code_field: row.get(code_key) or row["id"],
        "status": blob.get("status") or "",
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


def enquiry_from_blob(row):
    blob, fields = _pipeline_common(row, "enquiry_code", "enquiry_code", ENQUIRY_KEYS)
    fields = _apply(blob, fields, ENQUIRY_KEYS)
    fields["temperature"] = blob.get("temperature") or "Warm"
    return fields


def order_from_blob(row):
    blob, fields = _pipeline_common(row, "order_code", "order_code", ORDER_KEYS)
    return _apply(blob, fields, ORDER_KEYS)


def repair_from_blob(row):
    blob, fields = _pipeline_common(row, "repair_code", "repair_code", REPAIR_KEYS)
    fields = _apply(blob, fields, REPAIR_KEYS)
    fields["customer_approved"] = bool(blob.get("customerApproved"))
    return fields


def client_material_from_blob(row):
    blob, fields = _pipeline_common(row, "cm_code", "cm_code", CLIENT_MATERIAL_KEYS)
    return _apply(blob, fields, CLIENT_MATERIAL_KEYS)
