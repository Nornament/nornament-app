"""Copy the restored Supabase database into this one, preserving primary keys.

Wipe-and-reload, so it is idempotent by construction: run it nightly until
cutover and the final run is boring. Everything happens in one transaction —
a failed load leaves the database exactly as it was.

    manage.py load_legacy               # stock + crm
    manage.py load_legacy --only crm
    manage.py load_legacy --dry-run
"""
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import User, sync_role_groups
from crm.models import (
    ClientMaterial,
    CrmSetting,
    Customer,
    Enquiry,
    EtlException,
    Gift,
    Occasion,
    Order,
    OutreachEntry,
    RelatedPerson,
    Repair,
    Salesperson,
    StatusEvent,
)
# crm.Location and stock.Location are different tables with the same class
# name; stock's is imported below and would silently win.
from crm.models import Location as CrmLocation
from etl import legacy
from etl.crm_shapes import (
    _data_uri_parts,
    blob_of,
    media_from_blob,
    client_material_from_blob,
    customer_from_blob,
    enquiry_from_blob,
    order_from_blob,
    purchases_from_blob,
    repair_from_blob,
    status_events_from_blob,
)
from mediahub.models import MediaAsset
from stock.models import (
    BomLine,
    BomVersion,
    Category,
    Collection,
    Location,
    Material,
    MaterialCategory,
    MeltRecord,
    Metal,
    MetalPurity,
    Piece,
    RateCard,
    RateCardLine,
    RateChart,
    RateChartLine,
    RepairJob,
    RepairMaterialChange,
    Sale,
    Scenario,
    StockCount,
    StockCountScan,
    StockMovement,
    Style,
    SystemSetting,
    Vendor,
)

#: legacy table -> (model, column mapping). ``None`` means "same name".
STOCK_TABLES = [
    ("app.location", Location, {"location_id": "location_id"}),
    ("app.category", Category, None),
    ("app.collection", Collection, None),
    ("app.vendor", Vendor, None),
    ("app.metal", Metal, None),
    ("app.metal_purity", MetalPurity, None),
    ("app.material_category", MaterialCategory, None),
    ("app.material", Material, None),
    ("app.system_setting", SystemSetting, None),
    ("app.style", Style, None),
    ("app.rate_card", RateCard, None),
    ("app.rate_card_line", RateCardLine, None),
    ("app.rate_chart", RateChart, None),
    ("app.rate_chart_line", RateChartLine, None),
    ("app.scenario", Scenario, None),
    ("app.jewel_code", Piece, None),
    ("app.bom_version", BomVersion, None),
    ("app.jewel_material_line", BomLine, None),
    ("app.stock_movement", StockMovement, None),
    ("app.sale", Sale, None),
    ("app.melt_record", MeltRecord, None),
    ("app.repair_job", RepairJob, None),
    ("app.repair_material_change", RepairMaterialChange, None),
    ("app.stock_count", StockCount, None),
    ("app.stock_count_scan", StockCountScan, None),
    ("app.media_asset", MediaAsset, None),
]

#: legacy column -> model field, where the two names differ
RENAMES = {
    "jewel_code_id": "piece_id",
    "style_id": "style_id",
    "auth_uid": "legacy_auth_uid",
    "user_id": "user_id",
}

#: generated columns and columns this schema does not keep
SKIP_COLUMNS = {"margin_amt", "tat_days"}


class Command(BaseCommand):
    help = "Load the restored Supabase database into this one, preserving primary keys."

    def add_arguments(self, parser):
        parser.add_argument("--only", choices=["stock", "crm", "users"], action="append", dest="only")
        parser.add_argument("--dry-run", action="store_true", help="Count what would be loaded and roll back.")

    def handle(self, *args, **options):
        try:
            legacy.connection()
        except legacy.LegacyUnavailable as error:
            raise CommandError(str(error))

        #: legacy app_user.user_id -> this database's user pk. Every other
        #: table's user columns are remapped through it, because Django assigns
        #: its own ids to users while every other row keeps its original pk.
        self.user_map = {}
        parts = options.get("only") or ["users", "stock", "crm"]
        counts = {}
        try:
            with transaction.atomic():
                sync_role_groups()
                counts |= self.load_users(write=("users" in parts))
                if "stock" in parts:
                    counts |= self.load_stock()
                # The stock load preserves primary keys, so every sequence is
                # still sitting behind the rows it just wrote. ``load_crm``
                # creates ``MediaAsset`` rows with assigned ids, which collide
                # with the preserved ``app.media_asset`` pks unless the reset
                # happens here as well as at the end.
                legacy.reset_sequences()
                if "crm" in parts:
                    counts |= self.load_crm()
                legacy.reset_sequences()
                if options["dry_run"]:
                    raise _Rollback()
        except _Rollback:
            self.stdout.write(self.style.WARNING("dry run — rolled back"))

        for name, count in counts.items():
            self.stdout.write(f"{name:<32} {count:>8}")
        self.stdout.write(self.style.SUCCESS("load_legacy finished"))

    # ── users ────────────────────────────────────────────────────────────
    def load_users(self, write=True):
        """``app.app_user`` + its GoTrue login become one Django user.

        The password hash is written in Django's ``bcrypt$<hash>`` form so the
        BCryptPasswordHasher verifies it and Django re-hashes to the modern
        default on that user's first successful login. A user with no usable
        hash comes in with ``must_change_password`` set, not with a password
        anybody can guess.
        """
        rows = list(legacy.rows("SELECT * FROM app.app_user"))
        role_names = {
            row["role_id"]: name
            for row, name in (
                (row, legacy.scalar("SELECT code FROM app.role WHERE role_id=%s", [row["role_id"]])) for row in rows
            )
        }
        groups = {group.name: group for group in Group.objects.all()}
        loaded = 0
        for row in rows:
            if not write:
                # still needed for the FK remap, even when only stock is loaded
                existing = User.objects.filter(legacy_user_id=row["user_id"]).first()
                if existing:
                    self.user_map[row["user_id"]] = existing.pk
                continue
            hashed = row.get("password_hash") or ""
            password = f"bcrypt${hashed}" if hashed.startswith("$2") else ""
            # Keyed on the immutable legacy id, not username — a rename in the
            # old system between loads must update the same user, not insert a
            # duplicate that trips the legacy_auth_uid unique constraint.
            user, _ = User.objects.update_or_create(
                legacy_user_id=row["user_id"],
                defaults={
                    "username": row["username"],
                    "email": row.get("email") or "",
                    "full_name": row.get("full_name") or "",
                    "phone": row.get("phone") or "",
                    "is_active": row.get("is_active", True),
                    "password": password,
                    "must_change_password": bool(row.get("must_change_password", True)) or not password,
                    "legacy_auth_uid": row.get("auth_uid"),
                    "home_location_id": row.get("home_location_id"),
                },
            )
            group = groups.get(role_names.get(row["role_id"]))
            if group:
                user.groups.set([group])
            if role_names.get(row["role_id"]) == "ADMIN":
                User.objects.filter(pk=user.pk).update(is_staff=True)
            location_ids = [
                r["location_id"]
                for r in legacy.rows("SELECT location_id FROM app.user_location WHERE user_id=%s", [row["user_id"]])
            ]
            if location_ids:
                user.locations.set(location_ids)
            self.user_map[row["user_id"]] = user.pk
            loaded += 1
        return {"accounts.User": loaded} if write else {}

    # ── stock ────────────────────────────────────────────────────────────
    def load_stock(self):
        counts = {}
        # clear in reverse dependency order first: deleting a metal while a
        # purity still points at it is a ProtectedError, not a wipe
        for _, model, _ in reversed(STOCK_TABLES):
            model.objects.all().delete()

        for table, model, _ in STOCK_TABLES:
            if not legacy.table_exists(table):
                self.stdout.write(self.style.WARNING(f"{table} is not in the dump — skipped"))
                continue
            objects = []
            for row in legacy.rows(f"SELECT * FROM {table}"):
                objects.append(model(**self.map_row(model, row)))
                if len(objects) >= 1000:
                    model.objects.bulk_create(objects, batch_size=1000)
                    counts[model._meta.label] = counts.get(model._meta.label, 0) + len(objects)
                    objects = []
            if objects:
                model.objects.bulk_create(objects, batch_size=1000)
                counts[model._meta.label] = counts.get(model._meta.label, 0) + len(objects)

        # Legacy has no confirmed_at — the column is this schema's. Every media
        # row just loaded is an object that has been in the bucket for months,
        # but an unconfirmed row reads as an upload nobody finished and every
        # media query hides it. Backfill, or the migrated photos never render.
        MediaAsset.objects.filter(confirmed_at=None).update(confirmed_at=F("uploaded_at"))
        return counts

    def map_row(self, model, row):
        """Legacy column names to model attributes, dropping what we do not keep.

        A column pointing at ``app_user`` is translated through ``user_map``;
        a legacy user id that no longer exists becomes null rather than a
        foreign key violation that stops the whole load.
        """
        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        fields = {field.column: field for field in model._meta.concrete_fields}
        mapped = {}
        for column, value in row.items():
            if column in SKIP_COLUMNS:
                continue
            field = fields.get(column)
            if field is None or getattr(field, "generated", False):
                continue
            if field.is_relation and field.related_model is user_model:
                value = self.user_map.get(value)
            mapped[field.attname] = value
        return mapped

    # ── crm ──────────────────────────────────────────────────────────────
    #: label -> the ``MediaAsset.scope`` a CRM asset of that entity carries
    MEDIA_SCOPES = {
        "crm.Enquiry": "enquiry",
        "crm.Order": "order",
        "crm.Repair": "repair",
        "crm.ClientMaterial": "client_material",
    }

    def load_crm(self):
        """The JSONB blobs become real rows, and purchases become sales.

        Nothing is dropped: any key without a column of its own lands in
        ``extra``, and a customer_id pointing at nothing becomes an
        ``EtlException`` row rather than a silent null.
        """
        counts = {}
        crm_media = 0
        for model in (StatusEvent, Occasion, RelatedPerson, Gift, OutreachEntry, Enquiry, Order, Repair, ClientMaterial):
            model.objects.all().delete()
        # CRM assets only — the stock ones come from app.media_asset and are
        # loaded by the table pass, so wiping all of them would lose 418 rows
        MediaAsset.objects.filter(scope__isnull=False).delete()
        Sale.objects.filter(source=Sale.CRM).delete()
        Customer.objects.all().delete()
        EtlException.objects.all().delete()

        by_legacy_id = {}
        for row in legacy.rows("SELECT * FROM public.customers"):
            customer = Customer.objects.create(**customer_from_blob(row))
            by_legacy_id[row["id"]] = customer
            for event in status_events_from_blob(blob_of(row), "customer", customer.pk):
                StatusEvent.objects.create(**event)
            self.load_customer_children(customer, blob_of(row))
            crm_media += self.load_crm_media("customer", customer.pk, blob_of(row))
        counts["crm.Customer"] = len(by_legacy_id)

        # second pass: referrals and FoN parents, now that every customer exists
        for row in legacy.rows("SELECT * FROM public.customers"):
            customer = by_legacy_id.get(row["id"])
            blob = blob_of(row)
            parent_id = ((blob.get("fonData") or {}).get("parentId")) or None
            if parent_id and (parent := by_legacy_id.get(parent_id)):
                customer.fon_parent = parent
            referrer_code = ((blob.get("referenceFrom") or {}).get("referrerCode")) or None
            if referrer_code:
                customer.referrer = Customer.objects.filter(customer_code=referrer_code).first()
            customer.save(update_fields=["fon_parent", "referrer"])

        counts["stock.Sale (CRM)"] = self.load_purchases(by_legacy_id)

        for table, builder, model, label in (
            ("public.enquiries", enquiry_from_blob, Enquiry, "crm.Enquiry"),
            ("public.orders", order_from_blob, Order, "crm.Order"),
            ("public.repairs", repair_from_blob, Repair, "crm.Repair"),
            ("public.client_materials", client_material_from_blob, ClientMaterial, "crm.ClientMaterial"),
        ):
            if not legacy.table_exists(table):
                continue
            loaded = 0
            for row in legacy.rows(f"SELECT * FROM {table}"):
                customer = by_legacy_id.get(row.get("customer_id"))
                if row.get("customer_id") and customer is None:
                    EtlException.objects.create(
                        entity=label,
                        legacy_id=row["id"],
                        problem="customer_id points at no customer",
                        detail={"customer_id": row.get("customer_id")},
                    )
                entity = model.objects.create(customer=customer, **builder(row))
                crm_media += self.load_crm_media(self.MEDIA_SCOPES[label], entity.pk, blob_of(row))
                for event in status_events_from_blob(blob_of(row), model.__name__.lower(), entity.pk):
                    StatusEvent.objects.create(**event)
                loaded += 1
            counts[label] = loaded

        if legacy.table_exists("public.settings"):
            CrmSetting.objects.all().delete()
            for row in legacy.rows("SELECT * FROM public.settings"):
                CrmSetting.objects.create(key=row["key"], value=_json_value(row.get("value")))
            # The legacy Settings modal kept its two pickers inside the `app`
            # settings blob. They are real lists a user maintains, so they land
            # in real tables rather than staying buried in JSON.
            app_settings = CrmSetting.objects.filter(key="app").values_list("value", flat=True).first() or {}
            CrmLocation.objects.all().delete()
            Salesperson.objects.all().delete()
            for name in app_settings.get("locations") or []:
                CrmLocation.objects.create(name=name)
            for name in app_settings.get("salespersons") or []:
                Salesperson.objects.create(name=name)
            counts["crm.Location"] = CrmLocation.objects.count()
            counts["crm.Salesperson"] = Salesperson.objects.count()
        counts["mediahub.MediaAsset (CRM)"] = crm_media
        return counts

    def load_crm_media(self, scope, entity_id, blob):
        """The CRM's base64 photos, as real media rows.

        They were never in a bucket, so they arrive with their bytes on the
        row. ``manage.py push_inline_media`` moves them into object storage.
        Anything under a media key that is not a base64 data URI is reported
        rather than dropped — that is the whole point of the exceptions table.
        """
        made = 0
        for spec in media_from_blob(blob):
            spec.pop("legacy_id", None)
            MediaAsset.objects.create(
                media_ref=self._next_media_ref(),
                scope=scope,
                scope_id=str(entity_id),
                confirmed_at=timezone.now(),
                **spec,
            )
            made += 1
        for key in ("media", "photos", "photo", "beforePhoto", "afterPhoto"):
            raw = blob.get(key)
            if raw is None:
                continue
            entries = raw if isinstance(raw, list) else [raw]
            for entry in entries:
                value = entry.get("data") if isinstance(entry, dict) else entry
                if not isinstance(value, str) or not value:
                    continue
                if not value.startswith("data:"):
                    EtlException.objects.create(
                        entity=f"{scope}.media",
                        legacy_id=str(entity_id),
                        problem="media value is not a base64 data URI",
                        detail={"key": key, "value": value[:200]},
                    )
                elif _data_uri_parts(value) is None:
                    # a data URI we refused: a type we will not serve, or bytes
                    # that would not decode. Reported, never silently skipped.
                    EtlException.objects.create(
                        entity=f"{scope}.media",
                        legacy_id=str(entity_id),
                        problem="media data URI refused (unsupported type or bad base64)",
                        detail={"key": key, "header": value[:80]},
                    )
        return made

    def _next_media_ref(self):
        self._media_seq = getattr(self, "_media_seq", None)
        if self._media_seq is None:
            last = (
                MediaAsset.objects.exclude(media_ref=None)
                .order_by("-media_ref")
                .values_list("media_ref", flat=True)
                .first()
            )
            self._media_seq = int(last[1:]) if last and last[1:].isdigit() else 0
        self._media_seq += 1
        return f"M{self._media_seq:06d}"

    def load_customer_children(self, customer, blob):
        for occasion in blob.get("occasions") or []:
            Occasion.objects.create(
                customer=customer,
                occasion_type=occasion.get("type") or "Other",
                date=occasion.get("date") or None,
                note=occasion.get("note") or "",
            )
        for person in blob.get("relatedPeople") or []:
            RelatedPerson.objects.create(
                customer=customer,
                name=person.get("name") or "",
                relation=person.get("relation") or "",
                phone=person.get("phone") or "",
                birth_date=person.get("birthDate") or None,
                note=person.get("note") or "",
            )
        for gift in blob.get("gifting") or []:
            Gift.objects.create(
                customer=customer,
                date=gift.get("date") or None,
                occasion=gift.get("occasion") or "",
                description=gift.get("item") or gift.get("description") or "",
                amount=_money(gift.get("amount")),
            )
        for entry in blob.get("outreachLog") or []:
            OutreachEntry.objects.create(
                customer=customer,
                date=entry.get("date") or None,
                type=entry.get("type") or OutreachEntry.PHONE,
                outcome=entry.get("outcome") or "",
                notes=entry.get("notes") or "",
                next_follow_up=entry.get("nextFollowUp") or None,
                by=entry.get("by") or "",
            )

    def load_purchases(self, by_legacy_id):
        """``customer.data.purchases[]`` unnests into the one sale ledger.

        This is where the two disagreeing revenue numbers become one. A CRM
        purchase has no cost, so ``cost_at_sale`` stays null and margin
        reporting filters on ``source='STOCK'`` explicitly.
        """
        loaded = 0
        for row in legacy.rows("SELECT * FROM public.customers"):
            customer = by_legacy_id.get(row["id"])
            for purchase in purchases_from_blob(blob_of(row)):
                Sale.objects.create(
                    customer=customer,
                    customer_name=customer.name,
                    customer_phone=customer.phone,
                    source=Sale.CRM,
                    cost_at_sale=None,
                    legacy_id=f"crm:{row['id']}:{purchase['legacy_id']}",
                    **{key: value for key, value in purchase.items() if key != "legacy_id"},
                )
                loaded += 1
        return loaded


def _json_value(raw):
    import json

    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw or {}


def _money(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError):
        return None


class _Rollback(Exception):
    """Ends the transaction cleanly on --dry-run."""
