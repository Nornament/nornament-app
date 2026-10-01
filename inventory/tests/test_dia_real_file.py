"""The owner's own diamond file, imported whole (skipped when it is not beside the repo)."""
from decimal import Decimal

import pytest
from django.conf import settings

from inventory import dia_seed, dia_services
from inventory.importers import dia_plan, diamonds
from inventory.models import DiamondTerm

pytestmark = [pytest.mark.django_db, pytest.mark.golden]

REAL = settings.BASE_DIR.parent / "Dia_Stock_Nitesh.xlsx"


def test_the_owners_file_imports_whole(admin_user_):
    if not REAL.exists():
        pytest.skip(f"{REAL} is not beside the repo")
    dia_seed.load(DiamondTerm)
    rows = diamonds.parse(str(REAL))
    assert len(rows) == 320
    plan = dia_plan.analyse(rows)
    counts = plan.counts()
    assert (counts["blocked"], counts["empty"]) == (0, 39)
    dia_plan.commit(plan, admin_user_)
    lines = list(dia_services.stocked_lines())
    assert len(lines) == 281
    assert sum(line.on_ct for line in lines) == Decimal("546.96")
    rates = dia_services.rate_table()
    cost = sum(line.on_ct * dia_services.price(line, rates)[0] for line in lines)
    assert abs(cost - Decimal("14798794")) <= 10
