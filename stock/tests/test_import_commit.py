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
    assert lines.count() == 7          # 3 diamond + 1 metal + 2 stone + making


def test_the_making_charge_becomes_a_labour_line(parsed, materials, import_reference, admin_user_):
    """BG/BH sit with the totals, not in a band, and are easy to lose.

    Without this line every piece reconciles short by exactly its making, so
    the assertion is really about the reconciliation staying honest.
    """
    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)
    piece = Piece.objects.get(jewel_code="24P00111")
    making = BomLine.objects.get(
        piece=piece, version_no=piece.current_bom_version, material__category="LABOUR"
    )
    assert making.basis == "FLAT"          # base is 1, so the rate is the amount
    assert making.cost_rate == Decimal("8558.0000")
    assert making.cost_amount == Decimal("8558.00")


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


def test_the_whole_flow_works_through_the_browser(client, admin_user_, materials, import_reference, monkeypatch, settings):
    """Upload, review, commit, then the image loop — over real HTTP.

    Storage is stubbed at the boundary: the point here is the wiring between
    the four views, not that boto3 works.
    """
    settings.ALLOWED_HOSTS = ["testserver"]
    from mediahub import services as media_services
    from mediahub import storage
    from mediahub.models import MediaAsset

    book = build_workbook().getvalue()

    def fake_attach(files, scope, entity_id, user, kind=None):
        asset = MediaAsset.objects.create(
            file_name=getattr(files[0], "name", "x.xlsx"),
            scope=scope, scope_id=str(entity_id), storage_key="k",
        )
        return [asset], []

    monkeypatch.setattr(media_services, "attach_uploads", fake_attach)
    monkeypatch.setattr("stock.views.media_services.attach_uploads", fake_attach)
    monkeypatch.setattr(storage, "get_bytes", lambda key: book)

    client.force_login(admin_user_)
    upload = _xlsx_upload()
    response = client.post(reverse("stock:import_upload"), {"workbook": upload})
    batch = ImportBatch.objects.get()
    assert response.status_code == 302
    assert response["Location"].endswith(f"/{batch.batch_id}/")

    # the review screen renders and pre-fills its decisions
    review = client.get(reverse("stock:import_review", args=[batch.batch_id]))
    assert review.status_code == 200
    assert b"24P00088" in review.content
    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.REVIEWING
    assert batch.decisions["pieces"]["24P00088"]["action"] == "create"

    # committing writes the catalogue and hands over to the image loop
    committed = client.post(reverse("stock:import_commit", args=[batch.batch_id]), {"location": ""})
    assert committed.status_code == 200
    batch.refresh_from_db()
    assert batch.result["pieces_created"] == 3
    assert Piece.objects.filter(jewel_code="24P00088").exists()
    # the fixture carries no images, so it finishes in one go
    assert batch.status == ImportBatch.Status.DONE
    assert b"Import finished" in committed.content
    assert b"hx-trigger" not in committed.content


# ── resolving a blocker ──────────────────────────────────────────────────
@pytest.fixture
def blocked_book():
    """A workbook whose only metal is G12K — a purity that does not exist."""
    from stock.tests.fixtures_ivy import THREE_PRODUCTS
    from stock.tests.fixtures_ivy import build_workbook as build

    header, block = THREE_PRODUCTS[0]
    return build(products=[(dict(header), [{**block[0], 37: "G12K", 38: "Gold12K"}])])


def test_a_blocker_nobody_answered_is_still_unresolved(blocked_book, materials):
    plan = analyse(ivy.parse(blocked_book))
    assert analyse_mod.unresolved(plan, default_decisions(plan))


def test_mapping_a_blocker_onto_a_real_material_resolves_it(blocked_book, materials):
    """The reviewer says 'use G, the gold I already have' — that is an answer."""
    plan = analyse(ivy.parse(blocked_book))
    decisions = default_decisions(plan)
    decisions["materials"]["G12K"].update({"action": "map", "map_to": "G"})
    assert analyse_mod.unresolved(plan, decisions) == []


def test_skipping_a_blocker_resolves_it_and_drops_its_lines(
    blocked_book, materials, import_reference, admin_user_
):
    parsed = ivy.parse(blocked_book)
    plan = analyse(parsed)
    decisions = default_decisions(plan)
    decisions["materials"]["G12K"]["action"] = "skip"
    assert analyse_mod.unresolved(plan, decisions) == []

    commit(parsed, decisions, admin_user_)
    piece = Piece.objects.get(jewel_code="24P00088")
    assert not BomLine.objects.filter(
        piece=piece, material__item_code="G12K"
    ).exists(), "a skipped material must not be written"
    assert not Material.objects.filter(item_code="G12K").exists()


def test_a_mapped_blocker_books_its_lines_against_the_material_chosen(
    blocked_book, materials, import_reference, admin_user_
):
    parsed = ivy.parse(blocked_book)
    plan = analyse(parsed)
    decisions = default_decisions(plan)
    decisions["materials"]["G12K"].update({"action": "map", "map_to": "G"})
    commit(parsed, decisions, admin_user_)
    piece = Piece.objects.get(jewel_code="24P00088")
    metal = BomLine.objects.get(piece=piece, material__category="METAL")
    assert metal.material.item_code == "G"
    assert not Material.objects.filter(item_code="G12K").exists()


def test_the_commit_screen_refuses_and_keeps_the_form_when_unanswered(
    client, admin_user_, materials, import_reference, monkeypatch, settings, blocked_book
):
    """A refusal must not throw away what the reviewer already typed."""
    settings.ALLOWED_HOSTS = ["testserver"]
    from mediahub import storage
    from mediahub.models import MediaAsset

    book = blocked_book.getvalue()
    monkeypatch.setattr(storage, "get_bytes", lambda key: book)
    batch = ImportBatch.objects.create(
        media=MediaAsset.objects.create(file_name="x.xlsx", scope="import", scope_id="w", storage_key="k"),
        created_by=admin_user_,
    )
    client.force_login(admin_user_)
    refused = client.post(reverse("stock:import_commit", args=[batch.batch_id]), {"location": ""})
    assert refused.status_code == 200
    assert b"still need resolving" in refused.content
    assert b"existing item code" in refused.content     # the form is still there
    assert Piece.objects.count() == 0

    answered = client.post(
        reverse("stock:import_commit", args=[batch.batch_id]),
        {"location": "", "materials:G12K:map_to": "G"},
    )
    batch.refresh_from_db()
    assert answered.status_code == 200
    assert batch.result["pieces_created"] == 1
    assert Piece.objects.filter(jewel_code="24P00088").exists()
