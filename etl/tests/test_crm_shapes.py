"""Turning a CRM blob into columns: nothing dropped, nothing guessed."""
from decimal import Decimal

import pytest

from etl import crm_shapes

BLOB = {
    "id": "c_abc",
    "customerCode": "NC0001",
    "name": "Anita Shah",
    "phone": {"mobile": "9820000000", "landline": "", "preferred": "mobile"},
    "email": "anita@example.com",
    "birthDate": "1985-03-04",
    "referenceFrom": {"type": "Existing Customer", "referrerCode": "NC0000"},
    "fonData": {"isFoN": True, "level": 2, "parentId": "c_parent"},
    "outreach": {"done": True, "lastDate": "2026-07-01", "notes": "Called about Diwali"},
    "metalPreference": ["Gold", "Polki"],
    "purchases": [
        {"id": "p1", "date": "2026-07-04", "amount": "125000", "category": "cat1", "invoiceNo": "INV-9"},
        {"id": "p2", "date": "2026-07-20", "amount": 40000, "category": "cat3"},
        {"id": "p3", "date": "", "amount": 999},
    ],
    "occasions": [{"type": "Wedding", "date": "2026-12-01"}],
    "aWholeNewFieldNobodyToldUsAbout": "keep me",
}


def test_promoted_columns():
    fields = crm_shapes.customer_from_blob({"id": "c_abc", "customer_code": "NC0001", "data": BLOB})
    assert fields["name"] == "Anita Shah"
    assert fields["mobile"] == "9820000000"
    assert fields["birth_date"].isoformat() == "1985-03-04"
    assert fields["is_fon"] is True and fields["fon_level"] == 2
    assert fields["outreach_done"] is True
    assert fields["metal_preference"] == ["Gold", "Polki"]
    assert fields["legacy_id"] == "c_abc"


def test_an_unknown_key_survives_in_extra():
    """No key is ever dropped — that was the risk of normalising at all."""
    fields = crm_shapes.customer_from_blob({"id": "c_abc", "data": BLOB})
    assert fields["extra"]["aWholeNewFieldNobodyToldUsAbout"] == "keep me"
    # keys that became columns or their own tables are not duplicated into extra
    assert "purchases" not in fields["extra"]
    assert "phone" not in fields["extra"]


def test_purchases_become_sale_rows_and_a_dateless_one_is_left_behind():
    purchases = crm_shapes.purchases_from_blob(BLOB)
    assert [p["sold_price"] for p in purchases] == [Decimal("125000"), Decimal("40000")]
    assert purchases[0]["product_category"] == "cat1"
    assert purchases[0]["invoice_no"] == "INV-9"
    assert all(p["sold_on"] for p in purchases)


def test_money_parsing_survives_what_people_type():
    assert crm_shapes.money_or_none("₹1,25,000") == Decimal("125000")
    assert crm_shapes.money_or_none("") is None
    assert crm_shapes.money_or_none("not a number") is None


def test_a_bad_date_is_none_not_an_exception():
    assert crm_shapes.date_or_none("31-02-2026") is None
    assert crm_shapes.date_or_none("2026-08-24T10:00:00Z").isoformat() == "2026-08-24"


def test_order_blob_maps_to_order_columns():
    fields = crm_shapes.order_from_blob(
        {
            "id": "o1",
            "order_code": "NO0001",
            "data": {
                "orderDate": "2026-08-01",
                "itemDescription": "Polki choker",
                "totalAmount": "450000",
                "advancePaid": 100000,
                "status": "Designing",
                "statusLog": [{"date": "2026-08-01", "status": "Order Confirmed", "by": "Priya"}],
                "unknownThing": 42,
            },
        }
    )
    assert fields["order_code"] == "NO0001"
    assert fields["total_amount"] == Decimal("450000")
    assert fields["status"] == "Designing"
    assert fields["extra"] == {"unknownThing": 42}


def test_status_log_becomes_events():
    events = list(
        crm_shapes.status_events_from_blob(
            {"statusLog": [{"date": "2026-08-01", "status": "Order Confirmed", "note": "n", "by": "Priya"}]},
            "order",
            7,
        )
    )
    assert events[0]["entity_type"] == "order" and events[0]["entity_id"] == 7
    assert events[0]["status"] == "Order Confirmed"


# ── the CRM's base64 photos ──────────────────────────────────────────────
def test_a_data_uri_becomes_bytes_on_the_row():
    """The CRM never used object storage — its photos are base64 in the JSONB."""
    from etl.crm_shapes import media_from_blob

    one_pixel = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGP4DwABAQEAWk1v8QAAAABJRU5ErkJggg=="
    assets = media_from_blob({"media": [{"id": "abc", "name": "front.png", "type": "image", "data": one_pixel}]})
    assert len(assets) == 1
    asset = assets[0]
    assert asset["mime_type"] == "image/png"
    assert asset["file_name"] == "front.png"
    assert asset["inline_data"].startswith(b"\x89PNG")
    assert asset["bytes"] == len(asset["inline_data"])
    assert len(asset["sha256"]) == 64


def test_every_key_the_legacy_hid_a_photo_under_is_walked():
    """``media[].data``, ``photos[]``, ``photo``, ``beforePhoto``, ``afterPhoto``.

    The React card read three of these and the avatar used a fourth; missing one
    loses pictures silently, which is what this is here to stop.
    """
    from etl.crm_shapes import media_from_blob

    uri = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP/AABEIAAEAAQMBIgACEQEDEQH/xAAfAAABBQEBAQEBAQAAAAAAAAAAAQIDBAUGBwgJCgv/2gAIAQEAAD8A0s8g/9k="
    blob = {
        "media": [{"data": uri, "name": "a.jpg"}],
        "photos": [uri, uri],
        "photo": uri,
        "beforePhoto": uri,
        "afterPhoto": uri,
    }
    assets = media_from_blob(blob)
    assert len(assets) == 6
    assert {a["caption"] for a in assets} == {None, "beforePhoto", "afterPhoto"}


def test_a_value_that_is_not_a_data_uri_is_skipped_not_guessed():
    """An http URL or a stray string is reported by the loader, never decoded."""
    from etl.crm_shapes import media_from_blob

    assert media_from_blob({"media": [{"data": "https://example.test/a.jpg"}]}) == []
    assert media_from_blob({"photo": ""}) == []
    assert media_from_blob({"photo": None}) == []
    assert media_from_blob({}) == []
