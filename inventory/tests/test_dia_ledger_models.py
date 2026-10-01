"""Part 4's tables and reads: the diamond document kinds, the new reasons, a line's own cost, the
code a description finds, and stones lists that never show a diamond document."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from inventory import dia_rows, dia_services, ledger
from inventory.models import DiamondCode, DiamondLineCost, DiamondTerm, Movement, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
K, R = StockDocument.Kind, Movement.Reason


def _line(pk):
    return dia_services.stocked_lines().get(pk=pk)


def _cost(line, rate, **extra):
    return DiamondLineCost.objects.create(line=line, cost_rate=D(rate), **extra)


def test_the_diamond_kinds_and_reasons_exist():
    assert (K.DIA_JOB.label, K.DIA_ASSORT.label, K.DIA_PURCHASE.label) == ("Job card", "Assortment", "Diamond purchase")
    assert (R.RETURNED_UNUSED, R.ASSORT_OUT, R.ASSORT_IN) == ("Returned Unused", "Assort Out", "Assort In")
    doc = StockDocument.objects.create(kind=K.DIA_PURCHASE, number="2026/0442")      # twelve letters fit
    assert str(doc) == "Diamond purchase 2026/0442"
    StockDocument.objects.create(kind=K.PURCHASE, number="2026/0442")                 # a stones purchase may share it
    with pytest.raises(IntegrityError), transaction.atomic():
        StockDocument.objects.create(kind=K.DIA_PURCHASE, number="2026/0442")


def test_each_diamond_kind_has_a_prefix_and_a_right():
    assert {k: ledger.PREFIX[k] for k in ledger.DIAMOND_KINDS} == {
        K.DIA_JOB: "JC-", K.DIA_ASSORT: "AS-", K.DIA_PURCHASE: "DP-"}
    assert {k: ledger.RIGHT_FOR_KIND[k] for k in ledger.DIAMOND_KINDS} == {
        K.DIA_JOB: "accounts.inv_job", K.DIA_ASSORT: "accounts.inv_assort", K.DIA_PURCHASE: "accounts.inv_purchase"}
    assert set(ledger.STONE_KINDS) | set(ledger.DIAMOND_KINDS) == set(K.values)
    assert not set(ledger.STONE_KINDS) & set(ledger.DIAMOND_KINDS)


def test_a_lines_own_cost_wins_over_the_rate_card(diamonds):
    rnd, princess = diamonds["round"], diamonds["princess"]
    rates = dia_services.rate_table()
    assert dia_services.price(_line(rnd.pk), rates) == (D("16517"), D("21013"))
    _cost(rnd, "17777")
    assert dia_services.price(_line(rnd.pk), rates) == (D("17777"), D("21013"))       # sale stays the rate card's
    assert dia_services.price(_line(princess.pk), rates) == (None, None)              # neither: "not set"
    _cost(princess, "20000")
    assert dia_services.price(_line(princess.pk), rates) == (D("20000"), None)


def test_the_latest_own_cost_wins_and_a_future_one_waits(diamonds):
    rnd, today = diamonds["round"], timezone.localdate()
    _cost(rnd, "17000", effective_from=today - timedelta(days=3))
    _cost(rnd, "17500", effective_from=today)
    _cost(rnd, "99999", effective_from=today + timedelta(days=1))
    assert _line(rnd.pk).own_cost == D("17500")


def test_price_finds_the_own_cost_of_a_line_not_read_through_stocked_lines(diamonds):
    _cost(diamonds["round"], "17777")
    assert dia_services.price(diamonds["round"], dia_services.rate_table())[0] == D("17777")


def test_search_values_and_margin_read_the_own_cost(client, accounts_user, sales_user, diamonds):
    _cost(diamonds["round"], "17777")                                  # 3.40 ct × ₹17,777 = ₹60,441.80
    row = next(r for r in dia_rows.line_rows(accounts_user) if r["pk"] == diamonds["round"].pk)
    assert row["cost_amount"] == D("60441.80") and round(row["margin"], 2) == D("18.20")
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "17,777" in body and "60,442" in body and "16,517" not in body
    client.force_login(sales_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "17,777" not in body and "60,442" not in body


def test_a_description_finds_its_code_or_makes_a_confirmed_one(admin_user_, diamonds):
    assert dia_services.code_for(admin_user_, "Round", "F-G-H", "VS-SI").pk == "DRFGH VS-SI"
    made = dia_services.code_for(admin_user_, "Round", "G", "VS1")
    assert (made.pk, made.confirmed, made.note) == ("DRG VS1", True, "")
    assert (made.shape.value, made.colour.value, made.clarity.value) == ("Round", "G", "VS1")
    assert dia_services.code_for(admin_user_, "Round", "G", "VS1") == made              # found the second time
    assert dia_services.code_for(admin_user_, "Polki", "I-J", "SI-I").pk == "D Polki I-J SI-I"   # no token: words


@pytest.mark.parametrize("shape, colour, clarity, words", [
    ("", "G", "VS1", "Give the shape, colour and clarity"),
    ("Cushion", "G", "VS1", "Cushion is not on the shape list"),
    ("Round", "G", "VVS9", "VVS9 is not on the clarity list"),
])
def test_a_description_must_use_the_master_lists(admin_user_, diamonds, shape, colour, clarity, words):
    with pytest.raises(ServiceError, match=words):
        dia_services.code_for(admin_user_, shape, colour, clarity)
    assert not DiamondTerm.objects.filter(value__in=("Cushion", "VVS9")).exists()


def test_a_made_name_already_taken_is_refused(admin_user_, diamonds):
    DiamondCode.objects.create(item_code="DRG VS1", note="read another way")
    with pytest.raises(ServiceError, match="DRG VS1 already reads differently"):
        dia_services.code_for(admin_user_, "Round", "G", "VS1")


def test_a_blank_clarity_finds_or_makes_a_fancy_code(admin_user_, diamonds):
    # controller ruling, 2026-10-01: a blank clarity is accepted only for a Fancy colour.
    round_shape = DiamondTerm.objects.get(kind="shape", value="Round")
    fancy_yellow = DiamondTerm.objects.get(kind="colour", value="Fancy Yellow")
    existing = DiamondCode.objects.create(item_code="DFY", shape=round_shape, colour=fancy_yellow, confirmed=True)
    assert dia_services.code_for(admin_user_, "Round", "Fancy Yellow", "") == existing

    made = dia_services.code_for(admin_user_, "Princess", "Fancy Pink", "")
    assert (made.pk, made.confirmed, made.clarity) == ("D Princess Fancy Pink", True, None)
    assert (made.shape.value, made.colour.value) == ("Princess", "Fancy Pink")


def test_a_blank_clarity_with_a_non_fancy_colour_is_refused(admin_user_, diamonds):
    with pytest.raises(ServiceError, match="Give the shape, colour and clarity"):
        dia_services.code_for(admin_user_, "Round", "G", "")


def test_a_new_line_takes_the_next_reference_and_holds_nothing(diamonds):
    rnd = diamonds["round"]
    fresh = dia_services.new_line(category=rnd.category, code=rnd.code, band=rnd.band, size_text="+6-12")
    assert fresh.ref == "NRD-000004" and _line(fresh.pk).on_ct is None


def test_size_bands_follow_part_3_including_the_per_stone_rule():
    assert dia_services.sized("+2").band == "+2-6"
    per_stone = dia_services.sized("mixed", 4, D("1"))
    assert (per_stone.band, per_stone.ct_lo, per_stone.ct_hi) == ("carat band", D("0.250"), D("0.250"))
    assert dia_services.sized("mixed", None, D("1")).band == "?"


def test_a_line_reads_as_ref_code_size_and_batch(diamonds):
    assert dia_services.line_label(_line(diamonds["round"].pk)) == "NRD-000001 · DRFGH VS-SI · +6-12 · B-771"
    choices = dia_services.line_choices()
    assert choices[0] == {"pk": diamonds["round"].pk, "label": "NRD-000001 · DRFGH VS-SI · +6-12 · B-771",
                          "ct": D("3.40")}
    assert [c["pk"] for c in choices] == [diamonds[k].pk for k in ("round", "princess", "polki")]


def test_pickers_never_offer_an_unresolved_value(diamonds):
    DiamondTerm.objects.create(kind="shape", value="? RD8")
    assert "? RD8" not in dia_services.term_values("shape") and "Round" in dia_services.term_values("shape")


def test_no_stones_list_or_page_shows_a_diamond_document(client, accounts_user, shelf, diamonds):
    doc = StockDocument.objects.create(kind=K.DIA_JOB, number="JC-000001")
    Movement.objects.create(diamond=diamonds["round"], document=doc, reason=R.JOB_WORK_OUT,
                            direction=Movement.OUT, ct=D("1"))
    client.force_login(accounts_user)
    for query in ("", "?kind=dia_job"):
        body = client.get(reverse("inventory:recent") + query).content.decode()
        assert "JC-000001" not in body and "Job card" not in body
    assert client.get(reverse("inventory:document", args=[doc.pk])).status_code == 404
    for name in ("inventory:document_settle", "inventory:document_undo", "inventory:document_reverse"):
        assert client.post(reverse(name, args=[doc.pk])).status_code == 404, name
    assert ledger.out_summary() == {"ct": D("0"), "value": D("0"), "documents": 0}
    assert ledger.owed_by_document([doc]) == {}
