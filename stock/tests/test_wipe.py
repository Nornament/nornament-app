"""A full stock wipe leaves the app able to import again."""
from accounts.models import User
from stock import services
from stock.importers import guess
from stock.importers.ivy import ParsedLine
from stock.models import MaterialCategory, Metal, MetalPurity


def test_a_full_wipe_keeps_what_no_screen_can_recreate(rates):
    """Wiping every group used to take metals and purities too, which blocked
    every metal line of the next IVY import with no way to answer it."""
    MaterialCategory.objects.get_or_create(code="METAL", defaults={"name": "Metal", "sort_order": 1})
    owner = User.objects.create_superuser(username="root", password="fixture-value-not-a-credential")

    services.truncate_stock(owner)

    assert Metal.objects.filter(code="GOLD").exists()
    assert MetalPurity.objects.filter(karat="18K").exists()
    assert MaterialCategory.objects.filter(code="METAL").exists()
    _, problem = guess.material_fields(ParsedLine(band="metal", code="G18K", name="Gold18K"))
    assert problem is None


def test_wiping_a_photo_takes_its_thumbnail_with_it(piece, monkeypatch):
    """A thumbnail is an object of its own; leaving it would orphan it in the bucket."""
    from mediahub import storage
    from mediahub.models import MediaAsset

    MediaAsset.objects.create(
        piece=piece, storage_key="stock/piece/1/a.webp", thumb_key="stock/piece/1/a.thumb.webp",
        mime_type="image/webp",
    )
    gone = []
    monkeypatch.setattr(storage, "delete_keys", lambda keys: gone.extend(keys) or [])
    owner = User.objects.create_superuser(username="root", password="fixture-value-not-a-credential")
    services.truncate_stock(owner, delete_media_files=True)
    assert sorted(gone) == ["stock/piece/1/a.thumb.webp", "stock/piece/1/a.webp"]
