"""Writing an approved plan.

Two phases, deliberately separated. The catalogue goes in inside one
transaction, so a failure leaves the database exactly as it was. The images do
not: S3 is not transactional, and one refused upload should not roll back 373
pieces. An orphaned object in the bucket is harmless; a half-imported
catalogue nobody can describe is not.
"""
import os
import shutil
import tempfile
import time
import zipfile
from datetime import datetime
from datetime import time as clock
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from django_tasks import task

from stock import services
from stock.enums import BomChangeReason, ChargeBasis, Uom
from stock.importers import guess, ivy
from stock.models import Category, Collection, Material, Piece, Style, Vendor

#: how far our recost may drift from IVY's own total before we mention it
VARIANCE_TOLERANCE = 1


def _decision(decisions, section, key):
    return (decisions.get(section) or {}).get(key) or {}


def _resolve_named(decisions, section, model, cache):
    """Create-or-map every name in a section once, and remember the result."""
    for key, choice in (decisions.get(section) or {}).items():
        if key in cache:
            continue
        if choice.get("action") == "map" and choice.get("target"):
            cache[key] = model.objects.filter(pk=choice["target"]).first()
        elif choice.get("action") == "create":
            fields = dict(choice.get("fields") or {})
            name = fields.pop("name", key)
            code = fields.pop("code", None)
            lookup = {"code": code} if code else {"name": name}
            cache[key], _ = model.objects.get_or_create(**lookup, defaults={"name": name, **fields})
        else:
            cache[key] = None
    return cache


def _resolve_materials(decisions):
    """code as written in the sheet -> the Material it means.

    Creations run before mappings, because a reviewer is allowed to point a
    code at a material this same import is about to create — on a fresh
    catalogue that is the only sensible answer available.
    """
    resolved = {}
    entries = list((decisions.get("materials") or {}).items())
    mappings = [(k, c) for k, c in entries if c.get("action") == "map"]

    for key, choice in entries:
        fields = dict(choice.get("fields") or {})
        code = fields.get("item_code", key)
        if choice.get("action") == "skip":
            # None here, and _bom_lines drops every line using it
            resolved[key] = None
            continue
        if choice.get("action") == "map":
            continue                      # second pass, below
        existing = Material.objects.filter(item_code=code).first()
        if existing:
            resolved[key] = existing
            continue
        if fields.get("category_id") == "METAL" and not fields.get("metal_id"):
            # the view blocks this too; refusing here as well keeps a bad
            # decisions blob from reaching material_metal_required as an
            # IntegrityError halfway through the transaction
            raise ValueError(
                f"{code} is a metal with no metal resolved. Set its metal and purity first."
            )
        resolved[key] = Material.objects.create(**fields)

    for key, choice in mappings:
        code = choice.get("map_to") or (choice.get("fields") or {}).get("item_code", key)
        resolved[key] = Material.objects.filter(item_code=code).first()
    return resolved


#: the piece-level making charge lands on this material
MAKING_CODE = "MAKING"


def _making_material():
    """The material the sheet's BG/BH making charge is booked against."""
    material, _ = Material.objects.get_or_create(
        item_code=MAKING_CODE,
        defaults={"item_name": "Making Charge", "category_id": "LABOUR", "default_uom": Uom.PCS},
    )
    return material


def _bom_lines(parsed, materials):
    """The sheet's lines in the shape ``services.set_bom`` wants.

    The making charge is not in any band — it sits with the totals in BG/BH —
    but it is a real cost, and the largest one after metal on most pieces.
    Left out, every imported piece reconciles short by exactly its making.
    """
    lines = []
    for line in parsed.lines:
        material = materials.get(line.code)
        if material is None:
            continue
        basis, uom = guess.bom_basis_and_uom(line, material.category_id)
        qty = line.qty
        if basis == "FLAT":
            qty = None
        lines.append({
            "material": material,
            "size_band": line.size_band,
            "pcs": line.pcs,
            "qty_value": qty,
            "qty_uom": uom,
            "basis": basis,
            # FLAT means base 1, so the sheet's amount is the rate
            "cost_rate": line.cost_amount if basis == "FLAT" else line.cost_rate,
            "sale_rate": line.sale_amount if basis == "FLAT" else line.sale_rate,
            "off_chart": True,
        })
    if parsed.making_cost or parsed.making_sale:
        lines.append({
            "material": _making_material(),
            "size_band": "",
            "pcs": None,
            "qty_value": None,
            "qty_uom": Uom.PCS,
            "basis": ChargeBasis.FLAT,
            "cost_rate": parsed.making_cost,
            "sale_rate": parsed.making_sale,
            "off_chart": True,
        })
    return lines


def _received_at(parsed):
    """The sheet's inward date as an aware datetime.

    ``record_movement`` calls ``moved_at.date()`` and stamps a DateTimeField,
    so handing it the bare ``date`` the parser produced raises, and handing it
    a naive datetime logs a warning and stores an ambiguous instant.
    """
    if not parsed.inw_date:
        return None
    return timezone.make_aware(datetime.combine(parsed.inw_date, clock()))


def _apply_header(piece, parsed, style):
    piece.style = style
    piece.sub_category = parsed.sub_category or None
    piece.metal_purity = parsed.metal_purity or None
    piece.diamond_quality = parsed.diamond_quality or None
    piece.stock_type = parsed.stock_type or "FINISH_GOODS"
    piece.fg_date = parsed.fg_date
    piece.remarks = parsed.remarks or None
    piece.src_system = "IVY"
    piece.src_ref = parsed.sr_no or None
    piece.src_cost_price = parsed.src_cost_price
    piece.src_sale_price = parsed.src_sale_price
    piece.src_net_wt_gm = parsed.src_net_wt_gm
    piece.updated_at = timezone.now()


@transaction.atomic
def commit(pieces, decisions, user, location=None):
    """Write the approved plan. One transaction: it all lands, or none does."""
    materials = _resolve_materials(decisions)
    categories = _resolve_named(decisions, "categories", Category, {})
    collections = _resolve_named(decisions, "collections", Collection, {})
    vendors = _resolve_named(decisions, "vendors", Vendor, {})

    result = {
        "materials_created": sum(
            1 for c in (decisions.get("materials") or {}).values() if c.get("action") == "create"
        ),
        "styles_created": 0,
        "pieces_created": 0,
        "pieces_updated": 0,
        "pieces_skipped": 0,
        "lines_written": 0,
        "variances": [],
    }

    for parsed in pieces:
        choice = _decision(decisions, "pieces", parsed.jewel_code)
        action = choice.get("action", "create")
        existing = Piece.objects.filter(jewel_code=parsed.jewel_code).first()

        if existing and action != "update":
            result["pieces_skipped"] += 1
            continue

        style = Style.objects.filter(style_code=parsed.style_code).first()
        if style is None:
            category = categories.get(parsed.category)
            if category is None:
                # Style.category is NOT NULL PROTECT: a skipped category would
                # abort the whole transaction here rather than skip one row.
                raise ValueError(
                    f"{parsed.jewel_code} needs category {parsed.category!r}, which was "
                    "set to skip. Map it or create it."
                )
            style = Style.objects.create(
                style_code=parsed.style_code,
                category=category,
                collection=collections.get(parsed.collection),
                created_by=user,
            )
            result["styles_created"] += 1

        if existing:
            _apply_header(existing, parsed, style)
            existing.save()
            services.new_bom_version(
                user, existing, BomChangeReason.CORRECTION, note="IVY import"
            )
            piece = existing
            result["pieces_updated"] += 1
        else:
            piece = Piece(jewel_code=parsed.jewel_code, created_by=user)
            _apply_header(piece, parsed, style)
            piece.vendor = vendors.get(parsed.vendor)
            piece.save()
            result["pieces_created"] += 1

        lines = _bom_lines(parsed, materials)
        if lines:
            services.set_bom(user, piece, lines, reason=BomChangeReason.INITIAL, note="IVY import")
            result["lines_written"] += len(lines)

        if location is not None and piece.stock_state == "NOT_RECEIVED":
            services.receive_piece(user, piece, location, moved_at=_received_at(parsed))

        # our recost against IVY's own total — a big gap means a rule is wrong
        version = piece.current_bom()
        if version and parsed.src_cost_price is not None and version.total_cost_price is not None:
            drift = abs(version.total_cost_price - parsed.src_cost_price)
            if drift > VARIANCE_TOLERANCE:
                result["variances"].append(
                    {"jewel_code": piece.jewel_code, "ours": str(version.total_cost_price),
                     "theirs": str(parsed.src_cost_price), "drift": str(drift)}
                )
    return result


def attach_images(batch, pieces, read_photo, limit=10):
    """Upload the next few images. Returns how many this call got through.

    Runs outside the commit transaction and resumes from ``batch.images_done``,
    so a run that is cut off starts again where it stopped rather than over.
    ``read_photo`` turns a piece's photo path into bytes one photo at a time,
    so memory holds one photo however large the workbook is. One the bucket
    refuses is recorded against its jewel code and the rest carry on — those
    are the ones a person uploads by hand.
    """
    from mediahub.services import attach_uploads

    with_photos = [p for p in pieces if p.photo]
    todo = with_photos[batch.images_done:batch.images_done + limit]
    if not todo:
        return 0

    done, refused = 0, list((batch.result or {}).get("images_refused", []))
    for parsed in todo:
        done += 1
        piece = Piece.objects.filter(jewel_code=parsed.jewel_code).first()
        if piece is None or piece.media.exists():
            continue
        try:
            upload = SimpleUploadedFile(
                f"{parsed.jewel_code}.jpg", read_photo(parsed.photo), content_type="image/jpeg"
            )
            _, rejected = attach_uploads([upload], "piece", piece.pk, batch.created_by)
        except Exception as error:  # the bucket said no; the next photo may still go
            rejected = [str(error)]
        refused.extend({"jewel_code": parsed.jewel_code, "reason": reason} for reason in rejected)

    batch.images_done += done
    batch.result = {**(batch.result or {}), "images_refused": refused, "images_at": timezone.now().isoformat()}
    batch.save(update_fields=["images_done", "result"])
    return done


#: a photo job works this long, then queues the rest as a fresh job. A redeploy
#: waits out at most one chunk, and the remainder is still on the queue for the
#: new worker — nobody has to press Retry because a deploy landed mid-import.
PHOTO_CHUNK_SECONDS = 20

#: uploaded workbooks kept on local disk while they are reviewed and their
#: photos attached, so neither re-fetches hundreds of MB from the bucket.
#: ponytail: per-container and only emptied by a redeploy or a finished import;
#: put it on a volume with a sweep if abandoned uploads ever pile up.
IMPORT_CACHE = Path(tempfile.gettempdir()) / "nornament-imports"


def _workbook_path(batch):
    # the key carries a uuid, so one path can never mean two workbooks
    return IMPORT_CACHE / batch.media.storage_key.replace("/", "_")


def keep_workbook(batch, fileobj):
    """Cache a workbook already in hand (the upload) under this batch."""
    IMPORT_CACHE.mkdir(parents=True, exist_ok=True)
    with open(_workbook_path(batch), "wb") as cached:
        shutil.copyfileobj(fileobj, cached)


def workbook_file(batch):
    """The batch's workbook as an open file, off local disk.

    The bucket stays the truth: a copy missing here (a redeploy, the other
    container) is fetched once, into a temporary name, then moved into place so
    a half-written file is never read.
    """
    from mediahub import storage

    path = _workbook_path(batch)
    if not path.exists():
        IMPORT_CACHE.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f"{path.name}.{os.getpid()}.part")
        with open(partial, "wb") as workbook:
            storage.download_to(batch.media.storage_key, workbook)
        partial.replace(path)
    return open(path, "rb")


def attach_remaining_images(batch_id, seconds=PHOTO_CHUNK_SECONDS):
    """Attach photos for about ``seconds``, then queue the rest or finish.

    Photos come out of the workbook one at a time, so memory holds one photo
    however large the file is. Whatever happens, the batch ends DONE with how
    far it got, so the Data page can say which pieces still need a photo
    instead of spinning forever.
    """
    from stock.models import ImportBatch

    batch = ImportBatch.objects.get(pk=batch_id)
    deadline = time.monotonic() + seconds
    try:
        with workbook_file(batch) as workbook:
            pieces = ivy.parse(workbook)
            with zipfile.ZipFile(workbook) as archive:
                while attach_images(batch, pieces, archive.read):
                    if time.monotonic() > deadline:
                        _queue_next(batch)
                        return
    except Exception as error:
        batch.result = {**(batch.result or {}), "images_error": str(error)}
    batch.status = ImportBatch.Status.DONE
    batch.finished_at = timezone.now()
    batch.save(update_fields=["result", "status", "finished_at"])
    _workbook_path(batch).unlink(missing_ok=True)


@task()
def attach_photos(batch_id):
    """The queued job: run by ``manage.py db_worker``, never by the web process."""
    attach_remaining_images(batch_id)


def _queue_next(batch):
    queued = attach_photos.enqueue(batch.batch_id)
    batch.result = {**(batch.result or {}), "images_task": str(queued.id), "images_at": timezone.now().isoformat()}
    batch.save(update_fields=["result"])
    batch.__dict__.pop("images_waiting", None)  # cached before this job existed


def queue_photos(batch):
    """Put the batch's photos on the queue from the top.

    Pieces that already have their photo are passed over, so a rerun only
    sends what is missing, and refusals are counted afresh.
    """
    from stock.models import ImportBatch

    batch.result = {k: v for k, v in (batch.result or {}).items() if k not in ("images_refused", "images_error")}
    batch.images_done = 0
    batch.status = ImportBatch.Status.IMAGES
    batch.finished_at = None
    batch.save(update_fields=["status", "finished_at", "result", "images_done"])
    _queue_next(batch)
