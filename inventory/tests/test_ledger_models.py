"""The ledger's tables: documents, settles, reversals, a split's parent, and the new right."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.capabilities import INV_MOVE
from accounts.models import sync_role_groups
from inventory import dia_services, services
from inventory.models import Movement, Pouch, StockDocument
from stock.masking import mask

pytestmark = pytest.mark.django_db
D = Decimal
R = Movement.Reason


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def _move(pouch, reason, direction, ct, pcs=None, **extra):
    return Movement.objects.create(pouch=pouch, reason=reason, direction=direction, ct=D(ct), pcs=pcs, **extra)


def test_a_settle_never_changes_a_pouch_balance(shelf):
    _move(shelf["onyx"], R.CONSUMED, Movement.SETTLE, "2", pcs=3)
    held = _held(shelf["onyx"])
    assert (held.on_pcs, held.on_ct) == (20, D("12.5"))


def test_a_reversal_counts_with_the_opposite_sign(shelf):
    onyx, ruby = shelf["onyx"], shelf["ruby"]
    sale = _move(onyx, R.SALE, Movement.OUT, "2.5", pcs=5)
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (15, D("10"))
    _move(onyx, R.SALE, Movement.OUT, "2.5", pcs=5, reverses=sale)
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (20, D("12.5"))
    back = _move(ruby, R.SALES_RETURN, Movement.IN, "1")
    _move(ruby, R.SALES_RETURN, Movement.IN, "1", reverses=back)
    lost = _move(ruby, R.WASTAGE, Movement.SETTLE, "4")
    _move(ruby, R.WASTAGE, Movement.SETTLE, "4", reverses=lost)
    assert _held(ruby).on_ct == D("40")


def test_a_movement_is_reversed_at_most_once(shelf):
    sale = _move(shelf["onyx"], R.SALE, Movement.OUT, "1")
    _move(shelf["onyx"], R.SALE, Movement.OUT, "1", reverses=sale)
    with pytest.raises(IntegrityError), transaction.atomic():
        _move(shelf["onyx"], R.SALE, Movement.OUT, "1", reverses=sale)


def test_diamond_balances_follow_the_same_rule(diamonds):
    line = diamonds["round"]

    def ct():
        return dia_services.stocked_lines().get(pk=line.pk).on_ct

    sale = Movement.objects.create(diamond=line, reason=R.SALE, direction=Movement.OUT, ct=D("1.4"))
    assert ct() == D("2.00")
    Movement.objects.create(diamond=line, reason=R.CONSUMED, direction=Movement.SETTLE, ct=D("0.5"))
    assert ct() == D("2.00")
    Movement.objects.create(diamond=line, reason=R.SALE, direction=Movement.OUT, ct=D("1.4"), reverses=sale)
    assert ct() == D("3.40")


def test_the_movements_page_runs_its_balance_by_the_same_rule(client, admin_user_, shelf):
    onyx = shelf["onyx"]
    sale = _move(onyx, R.SALE, Movement.OUT, "2.5", pcs=5)
    _move(onyx, R.SALE, Movement.OUT, "2.5", pcs=5, reverses=sale)
    _move(onyx, R.CONSUMED, Movement.SETTLE, "1", pcs=1)
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:movements", args=[onyx.ref])).content.decode()
    assert "4 movements" in body and "10.00 ct" in body
    assert body.count("12.50 ct<div") == 3      # balance after the opening, the reversal and the settle


def test_a_document_number_is_unique_per_kind_until_reversed():
    K = StockDocument.Kind
    first = StockDocument.objects.create(kind=K.JOB_WORK, number="2026/0431")
    with pytest.raises(IntegrityError), transaction.atomic():
        StockDocument.objects.create(kind=K.JOB_WORK, number="2026/0431")
    StockDocument.objects.create(kind=K.MEMO, number="2026/0431")          # another kind may share it
    first.status = StockDocument.Status.REVERSED
    first.save()
    StockDocument.objects.create(kind=K.JOB_WORK, number="2026/0431")      # a reversed one's number is free


def test_movements_hang_off_their_document(shelf):
    doc = StockDocument.objects.create(kind=StockDocument.Kind.SINGLE, number="MOV-000001")
    _move(shelf["onyx"], R.BREAKAGE, Movement.OUT, "1", document=doc)
    assert doc.movements.get().reason == R.BREAKAGE and doc.status == StockDocument.Status.OPEN
    assert str(doc) == "Single MOV-000001"


def test_a_split_pouch_remembers_its_parent(shelf):
    child = Pouch.objects.create(ref="NRN-000099", batch=shelf["batch"], pouch_no="9", parent=shelf["onyx"])
    assert list(shelf["onyx"].children.all()) == [child]


def test_record_stock_movements_belongs_to_admin_and_accounts(
    admin_user_, accounts_user, sales_user, production_user, karigar_user, graphic_user
):
    assert admin_user_.has_perm(INV_MOVE) and accounts_user.has_perm(INV_MOVE)
    for user in (sales_user, production_user, karigar_user, graphic_user):
        assert not user.has_perm(INV_MOVE), user


def test_the_add_only_sync_grants_the_new_right():
    Permission.objects.filter(codename="inv_move").delete()      # as if the right were brand new
    sync_role_groups()
    holders = set(Group.objects.filter(permissions__codename="inv_move").values_list("name", flat=True))
    assert holders == {"ADMIN", "ACCOUNTS"}


def test_both_rights_matrices_carry_it(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:dia_settings")).content.decode()
    assert "Record stock movements" in body and 'value="inv_move"' in body
    body = client.get(reverse("stock:settings"), {"tab": "perms"}).content.decode()
    assert "Record stock movements" in body and "inv_move" in body


def test_karigar_and_customer_names_mask_by_their_rights(
    karigar_user, production_user, sales_user, graphic_user, accounts_user
):
    row = {"karigar_name": "Mahesh Karigar", "customer_name": "Kalyan Retail"}
    assert mask(karigar_user, row) == {"karigar_name": "Mahesh Karigar"}
    assert mask(production_user, row) == {"karigar_name": "Mahesh Karigar"}
    assert mask(sales_user, row) == {"customer_name": "Kalyan Retail"}
    assert mask(graphic_user, row) == {}
    assert mask(accounts_user, row) == row
