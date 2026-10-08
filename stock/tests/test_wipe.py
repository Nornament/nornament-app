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
