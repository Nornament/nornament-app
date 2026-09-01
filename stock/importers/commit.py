"""Writing an approved plan.

Two phases, deliberately separated. The catalogue goes in inside one
transaction, so a failure leaves the database exactly as it was. The images do
not: S3 is not transactional, and one refused upload should not roll back 373
pieces. An orphaned object in the bucket is harmless; a half-imported
catalogue nobody can describe is not.
"""
from datetime import datetime, time

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from stock import services
from stock.enums import BomChangeReason
from stock.importers import guess
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
    """code as written in the sheet -> the Material it means."""
    resolved = {}
    for key, choice in (decisions.get("materials") or {}).items():
        fields = dict(choice.get("fields") or {})
        code = fields.get("item_code", key)
        if choice.get("action") == "map":
            resolved[key] = Material.objects.filter(item_code=code).first()
            continue
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
    return resolved


def _bom_lines(parsed, materials):
    """The sheet's lines in the shape ``services.set_bom`` wants."""
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
    return lines


def _received_at(parsed):
    """The sheet's inward date as an aware datetime.

    ``record_movement`` calls ``moved_at.date()`` and stamps a DateTimeField,
    so handing it the bare ``date`` the parser produced raises, and handing it
    a naive datetime logs a warning and stores an ambiguous instant.
    """
    if not parsed.inw_date:
        return None
    return timezone.make_aware(datetime.combine(parsed.inw_date, time()))


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


def attach_images(batch, pieces, limit=10):
    """Upload the next few images. Returns how many this call got through.

    Runs outside the commit transaction, and is driven a chunk at a time by the
    browser, so a closed tab resumes from ``batch.images_done`` rather than
    starting over or double-attaching.
    """
    from mediahub.models import MediaAsset
    from mediahub.services import attach_uploads

    with_images = [p for p in pieces if p.image]
    todo = with_images[batch.images_done:batch.images_done + limit]
    if not todo:
        return 0

    done, refused = 0, list((batch.result or {}).get("images_refused", []))
    for parsed in todo:
        piece = Piece.objects.filter(jewel_code=parsed.jewel_code).first()
        if piece is None:
            done += 1
            continue
        if MediaAsset.objects.filter(scope="piece", scope_id=str(piece.pk)).exists():
            done += 1
            continue
        upload = SimpleUploadedFile(
            f"{parsed.jewel_code}.jpg", parsed.image, content_type="image/jpeg"
        )
        saved, rejected = attach_uploads([upload], "piece", piece.pk, batch.created_by)
        refused.extend(rejected)
        done += 1

    batch.images_done += done
    batch.result = {**(batch.result or {}), "images_refused": refused}
    batch.save(update_fields=["images_done", "result"])
    return done
