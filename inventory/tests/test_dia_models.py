from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from inventory import dia_seed, services
from inventory.models import DiamondCode, DiamondLine, DiamondTerm, Movement

pytestmark = pytest.mark.django_db


@pytest.fixture
def terms():
    dia_seed.load(DiamondTerm)
    return {(t.kind, t.value): t for t in DiamondTerm.objects.all()}


def test_the_ladders_and_ranges_are_seeded_in_order(terms):
    colours = list(DiamondTerm.objects.filter(kind=DiamondTerm.COLOUR).values_list("value", flat=True))
    assert colours[:4] == ["D", "E", "F", "G"]
    assert terms[("colour", "F-G-H")].grades() == ["F", "G", "H"]
    assert terms[("clarity", "SI-I")].grades() == ["SI1", "SI2", "SI3", "I1"]
    assert terms[("colour", "G")].grades() == ["G"]
    assert terms[("colour", "Fancy Yellow")].grades() == []
    assert list(DiamondTerm.objects.filter(kind=DiamondTerm.BAND).values_list("value", flat=True)) == dia_seed.BANDS


def test_seeding_twice_changes_nothing(terms):
    before = DiamondTerm.objects.count()
    dia_seed.load(DiamondTerm)
    assert DiamondTerm.objects.count() == before


def test_a_movement_belongs_to_a_pouch_or_a_diamond_never_both(terms, shelf):
    code = DiamondCode.objects.create(item_code="DRFGH VS-SI")
    line = DiamondLine.objects.create(ref="NRD-000001", category=terms[("category", "Natural Diamond")],
                                      code=code, band=terms[("band", "+6-11")], size_text="+6-12")
    Movement.objects.create(diamond=line, reason=Movement.Reason.OPENING_BALANCE, direction=Movement.IN,
                            ct=Decimal("3.4"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Movement.objects.create(reason=Movement.Reason.SALE, direction=Movement.OUT, ct=Decimal("1"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Movement.objects.create(pouch=shelf["onyx"], diamond=line, reason=Movement.Reason.SALE,
                                direction=Movement.OUT, ct=Decimal("1"))


def test_pouch_stock_is_unchanged_by_the_new_link(shelf):
    held = services.stocked().get(pk=shelf["onyx"].pk)
    assert held.on_ct == Decimal("12.5")
