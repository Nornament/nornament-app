"""Deciding what an import will do, and then doing it."""
import pytest

from stock.importers import analyse as analyse_mod, ivy
from stock.importers.analyse import analyse, default_decisions
from stock.models import Material, Piece, Style
from stock.tests.fixtures_ivy import build_workbook

pytestmark = pytest.mark.django_db


@pytest.fixture
def parsed():
    return ivy.parse(build_workbook())


@pytest.fixture
def import_reference(db, rates, materials):
    """What the shared fixtures do not cover but this workbook needs.

    ``materials`` creates METAL/DIAMOND/SETTING/LABOUR only, and ``rates``
    creates 18K and 925 only. The sample workbook carries a Foil Polki line
    and 14K gold, so without these the guesser produces a category that does
    not exist and a purity it is right to refuse.
    """
    from stock.models import MaterialCategory, MetalPurity

    for order, code in enumerate(["POLKI", "OTHER"], start=5):
        MaterialCategory.objects.get_or_create(
            code=code, defaults={"name": code.title(), "sort_order": order}
        )
    MetalPurity.objects.get_or_create(
        karat="14K",
        defaults={
            "sale_factor": "0.6000", "true_fineness": "0.5833",
            "metal": rates["gold"], "sort_order": 4,
        },
    )


def test_a_material_already_in_the_register_is_mapped_not_created(parsed, materials):
    """``materials`` fixture creates DRFGH SI-I among others."""
    Material.objects.get_or_create(
        item_code="DRFGH SI-I",
        defaults={"item_name": "Diamond", "category_id": "DIAMOND", "default_uom": "CT"},
    )
    plan = analyse(parsed)
    row = next(r for r in plan.materials if r.key == "DRFGH SI-I")
    assert row.action == "map"


def test_an_unknown_material_is_proposed_as_a_creation(parsed, materials, import_reference):
    plan = analyse(parsed)
    row = next(r for r in plan.materials if r.key == "SP01C")
    assert row.action == "create"
    assert row.fields["category_id"] == "SETTING"


def test_a_material_the_guesser_cannot_place_becomes_a_blocker(materials):
    """A workbook whose only metal is G12K, a purity that does not exist."""
    from stock.tests.fixtures_ivy import THREE_PRODUCTS, build_workbook as build

    header, block = THREE_PRODUCTS[0]
    broken = [(dict(header), [{**block[0], 37: "G12K", 38: "Gold12K"}])]
    plan = analyse(ivy.parse(build(products=broken)))
    row = next(r for r in plan.materials if r.key == "G12K")
    assert row.problem is not None
    assert plan.blockers


def test_categories_match_existing_ones_by_fuzzy_name(parsed):
    from stock.models import Category

    Category.objects.get_or_create(code="EAR", defaults={"name": "Earrings"})
    plan = analyse(parsed)
    row = next(r for r in plan.categories if r.key == "Earring")
    assert row.action == "map"
    assert row.target.name == "Earrings"


def test_a_singular_category_maps_onto_the_seeded_plural(parsed):
    """The seed migration ships 'Rings'; the sheet writes 'Ring'."""
    plan = analyse(parsed)
    row = next(r for r in plan.categories if r.key == "Ring")
    assert row.action == "map"
    assert row.target.name == "Rings"


def test_a_category_matching_nothing_is_proposed_as_a_creation():
    """'Idol' has no seeded counterpart, so it must be offered as new."""
    from stock.tests.fixtures_ivy import THREE_PRODUCTS
    from stock.tests.fixtures_ivy import build_workbook as build

    header, block = THREE_PRODUCTS[0]
    plan = analyse(ivy.parse(build(products=[({**header, 5: "Idol"}, block)])))
    row = next(r for r in plan.categories if r.key == "Idol")
    assert row.action == "create"


def test_a_piece_already_present_defaults_to_untouched(parsed, piece, materials):
    """An existing jewel code is offered for update, but not ticked."""
    existing = Piece.objects.first()
    existing.jewel_code = "24P00095"
    existing.save(update_fields=["jewel_code"])
    plan = analyse(parsed)
    row = next(r for r in plan.pieces if r.key == "24P00095")
    assert row.action == "skip"
    assert row.detail  # the diff that explains what an update would change


def test_a_new_piece_defaults_to_being_created(parsed, materials):
    plan = analyse(parsed)
    row = next(r for r in plan.pieces if r.key == "24P00088")
    assert row.action == "create"


def test_default_decisions_round_trip_the_plan(parsed, materials):
    plan = analyse(parsed)
    decisions = default_decisions(plan)
    assert decisions["materials"]["SP01C"]["action"] == "create"
    assert decisions["pieces"]["24P00088"]["action"] == "create"


# ── committing ───────────────────────────────────────────────────────────
from decimal import Decimal

from stock.importers.commit import attach_images, commit
from stock.models import BomLine, BomVersion, ImportBatch


def test_commit_creates_materials_styles_and_pieces(parsed, materials, import_reference, admin_user_):
    plan = analyse(parsed)
    result = commit(parsed, default_decisions(plan), admin_user_)
    assert result["pieces_created"] == 3
    assert Piece.objects.filter(jewel_code="24P00088").exists()
    assert Style.objects.filter(style_code="ER00502").exists()


def test_imported_pieces_carry_what_the_source_system_said(parsed, materials, import_reference, admin_user_):
    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)
    piece = Piece.objects.get(jewel_code="24P00111")
    assert piece.src_system == "IVY"
    assert piece.src_cost_price == Decimal("84438.00")
    assert piece.src_net_wt_gm == Decimal("8.228")


def test_every_material_line_lands_on_the_bom(parsed, materials, import_reference, admin_user_):
    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)
    piece = Piece.objects.get(jewel_code="24P00111")
    lines = BomLine.objects.filter(piece=piece, version_no=piece.current_bom_version)
    assert lines.count() == 6          # 3 diamond + 1 metal + 2 stone


def test_metal_lines_keep_their_own_weight(parsed, materials, import_reference, admin_user_):
    """BY_NET_METAL_WT would have snapped this to the piece total."""
    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)
    piece = Piece.objects.get(jewel_code="24P00111")
    metal = BomLine.objects.get(
        piece=piece, version_no=piece.current_bom_version, material__category="METAL"
    )
    assert metal.qty_value == Decimal("8.2280")
    assert metal.basis == "BY_QTY"


def test_pieces_land_not_received_when_no_location_is_chosen(parsed, materials, import_reference, admin_user_):
    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)
    piece = Piece.objects.get(jewel_code="24P00088")
    assert piece.stock_state == "NOT_RECEIVED"
    assert piece.location_id is None


def test_choosing_a_location_receives_the_piece(parsed, materials, import_reference, admin_user_, locations):
    from stock.models import Location

    plan = analyse(parsed)
    where = Location.objects.first()
    commit(parsed, default_decisions(plan), admin_user_, location=where)
    piece = Piece.objects.get(jewel_code="24P00088")
    assert piece.stock_state == "IN_STOCK"
    assert piece.location_id == where.pk


def test_an_existing_piece_is_left_alone_when_skipped(parsed, piece, materials, import_reference, admin_user_):
    existing = Piece.objects.first()
    existing.jewel_code = "24P00095"
    existing.sub_category = "UNTOUCHED"
    existing.save(update_fields=["jewel_code", "sub_category"])
    plan = analyse(parsed)
    result = commit(parsed, default_decisions(plan), admin_user_)
    existing.refresh_from_db()
    assert existing.sub_category == "UNTOUCHED"
    assert result["pieces_skipped"] == 1


def test_updating_an_existing_piece_adds_a_version_and_keeps_the_old_one(
    parsed, piece, materials, import_reference, admin_user_
):
    existing = Piece.objects.first()
    existing.jewel_code = "24P00095"
    existing.save(update_fields=["jewel_code"])
    was = existing.current_bom_version
    plan = analyse(parsed)
    decisions = default_decisions(plan)
    decisions["pieces"]["24P00095"]["action"] = "update"
    result = commit(parsed, decisions, admin_user_)

    existing.refresh_from_db()
    assert result["pieces_updated"] == 1
    assert existing.current_bom_version == was + 1
    # the old version survives, and is no longer current
    old = BomVersion.objects.get(piece=existing, version_no=was)
    assert old.is_current is False
    new = BomVersion.objects.get(piece=existing, version_no=was + 1)
    assert new.is_current is True
    assert new.reason == "CORRECTION"


def test_images_are_attached_in_chunks_and_are_resumable(
    parsed, materials, import_reference, admin_user_, settings, tmp_path
):
    """Each chunk does its share, and the counter is what makes it resumable."""
    from mediahub.models import MediaAsset

    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)

    # the fixture workbook has no embedded images, so plant one
    parsed[0].image = b"\xff\xd8\xff\xe0fake-jpeg"
    batch = ImportBatch.objects.create(
        # media_asset_has_an_owner needs style, piece or scope set
        media=MediaAsset.objects.create(file_name="x.xlsx", scope="import", scope_id="workbook"),
        images_total=1,
        created_by=admin_user_,
    )
    done = attach_images(batch, parsed, limit=10)
    batch.refresh_from_db()
    assert done == 1
    assert batch.images_done == 1
    # running again does nothing, rather than attaching a second copy
    assert attach_images(batch, parsed, limit=10) == 0


# ── the screens ──────────────────────────────────────────────────────────
from django.urls import reverse


def _xlsx_upload(name="stock.xlsx", products=None):
    """The fixture workbook as something a form POST would carry."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from stock.tests.fixtures_ivy import build_workbook

    return SimpleUploadedFile(
        name,
        build_workbook(products=products).getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def test_a_workbook_with_wrong_headers_is_refused_at_upload(client, admin_user_):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from openpyxl import Workbook

    book = Workbook()
    book.active["A1"] = "not an IVY export"
    stream = io.BytesIO()
    book.save(stream)

    client.force_login(admin_user_)
    response = client.post(
        reverse("stock:import_upload"),
        {"workbook": SimpleUploadedFile("wrong.xlsx", stream.getvalue())},
        follow=True,
    )
    assert ImportBatch.objects.count() == 0
    assert b"not an IVY stock export" in response.content


def test_a_non_admin_cannot_reach_the_importer(client, sales_user):
    """Only the data tab opens this, and only ADMIN has it."""
    client.force_login(sales_user)
    assert client.post(reverse("stock:import_upload"), {}).status_code == 403


def test_the_progress_partial_stops_asking_once_it_is_done(client, admin_user_):
    from mediahub.models import MediaAsset

    batch = ImportBatch.objects.create(
        media=MediaAsset.objects.create(file_name="x.xlsx", scope="import", scope_id="workbook"),
        status=ImportBatch.Status.DONE,
        images_done=3,
        images_total=3,
        result={"pieces_created": 3, "pieces_updated": 0, "pieces_skipped": 0, "lines_written": 9},
        created_by=admin_user_,
    )
    client.force_login(admin_user_)
    response = client.post(reverse("stock:import_images", args=[batch.batch_id]))
    assert b"hx-trigger" not in response.content
    assert b"Import finished" in response.content
