"""Roles made and changed from Users & Settings, and the CRM as a screen."""
import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from accounts.models import Role, User
from conftest import _user

pytestmark = pytest.mark.django_db

ROLES = reverse("stock:settings") + "?tab=perms"


def _matrix(role_codes, caps=None, screens=None, names=None):
    """What the Save button posts: one tick per (role, capability|screen) left on."""
    data = {}
    for code in role_codes:
        for cap in (caps or {}).get(code, []):
            data[f"cap:{code}:{cap}"] = "on"
        for screen in (screens or {}).get(code, []):
            data[f"screen:{code}:{screen}"] = "on"
    for code, name in (names or {}).items():
        data[f"name:{code}"] = name
    return data


def _as_now():
    """Every non-admin role exactly as it stands, so a post changes only what a test says."""
    caps, screens, names = {}, {}, {}
    for role in Role.objects.select_related("group").exclude(group__name="ADMIN"):
        caps[role.code] = list(role.group.permissions.values_list("codename", flat=True))
        screens[role.code] = list(role.screens)
        names[role.code] = role.name
    return caps, screens, names


def test_every_built_in_role_keeps_its_screens_and_gains_the_crm():
    sales = Role.objects.get(group__name="SALES")
    assert sales.name == "Sales / Showroom"
    assert set(sales.screens) == {"dash", "stock", "count", "styles", "crm"}


def test_an_admin_adds_a_role_copied_from_another(client, admin_user_):
    client.force_login(admin_user_)
    client.post(ROLES, {"new_role": "Store manager", "copy_from": "ACCOUNTS"})
    role = Role.objects.get(name="Store manager")
    assert role.code == "STORE_MANAGER"
    accounts = Role.objects.get(group__name="ACCOUNTS")
    assert role.screens == accounts.screens
    assert set(role.group.permissions.all()) == set(accounts.group.permissions.all())


def test_unticking_the_crm_closes_it_and_the_nav_shows_a_padlock(client, admin_user_, sales_user):
    client.force_login(sales_user)
    assert client.get(reverse("crm:dashboard")).status_code == 200

    caps, screens, names = _as_now()
    screens["SALES"].remove("crm")
    client.force_login(admin_user_)
    client.post(ROLES, _matrix(screens.keys(), caps, screens, names))

    client.force_login(sales_user)
    assert client.get(reverse("crm:dashboard")).status_code == 403
    page = client.get(reverse("stock:dashboard")).content.decode()
    assert "Customers &amp; Orders<span class=\"lockicon\">" in page


def test_a_capability_ticked_on_screen_is_a_right_the_login_holds(client, admin_user_, sales_user):
    assert not sales_user.has_perm("accounts.view_cost")
    caps, screens, names = _as_now()
    caps["SALES"].append("view_cost")
    client.force_login(admin_user_)
    client.post(ROLES, _matrix(caps.keys(), caps, screens, names))
    assert User.objects.get(pk=sales_user.pk).has_perm("accounts.view_cost")


def test_the_admin_role_cannot_be_narrowed(client, admin_user_):
    """A post that names ADMIN's boxes is ignored: the way back in is never removed."""
    client.force_login(admin_user_)
    caps, screens, names = _as_now()
    client.post(ROLES, _matrix(caps.keys(), caps, screens, names) | {"name:ADMIN": "Nobody"})
    admin = Role.objects.get(group__name="ADMIN")
    assert admin.name == "Admin / Owner"
    assert User.objects.get(pk=admin_user_.pk).has_perm("accounts.edit_bom")
    assert "admin" in User.objects.get(pk=admin_user_.pk).screens


def test_the_screen_shows_what_the_database_holds_not_the_seed(client, admin_user_):
    from django.contrib.auth.models import Permission

    Group.objects.get(name="SALES").permissions.remove(
        Permission.objects.get(codename="view_sale", content_type__app_label="accounts")
    )
    client.force_login(admin_user_)
    page = client.get(ROLES).content.decode()

    def box(name):
        start = page.index(f'name="{name}"')
        return page[page.rindex("<input", 0, start):page.index(">", start)]

    assert "checked" not in box("cap:SALES:view_sale")
    assert "checked" in box("cap:SALES:manage_materials")


def test_only_an_admin_manages_roles_and_users(client, admin_user_):
    """A role given Users & Settings is not thereby given the power to hand out rights."""
    client.force_login(admin_user_)
    client.post(ROLES, {"new_role": "Office", "copy_from": "SALES"})
    office = Role.objects.get(name="Office")
    office.screens = [*office.screens, "admin"]
    office.save()
    clerk = _user("clerk", office.code)

    client.force_login(clerk)
    assert client.get(ROLES).status_code == 200                       # may look
    assert client.post(ROLES, {"new_role": "Mine"}).status_code == 403
    assert client.post(reverse("stock:user_add"), {"username": "x"}).status_code == 403
    assert not Role.objects.filter(name="Mine").exists()


def test_a_role_with_logins_or_a_built_in_one_is_not_deleted(client, admin_user_, sales_user):
    client.force_login(admin_user_)
    client.post(ROLES, {"new_role": "Temp", "copy_from": ""})
    client.post(ROLES, {"new_role": "Busy", "copy_from": ""})
    _user("someone", Role.objects.get(name="Busy").code)

    client.post(ROLES, {"delete_role": "SALES"})
    client.post(ROLES, {"delete_role": "BUSY"})
    client.post(ROLES, {"delete_role": "TEMP"})
    assert Role.objects.filter(group__name="SALES").exists()
    assert Role.objects.filter(name="Busy").exists()
    assert not Role.objects.filter(name="Temp").exists()
    assert not Group.objects.filter(name="TEMP").exists()


def test_two_roles_cannot_share_a_name(client, admin_user_):
    client.force_login(admin_user_)
    caps, screens, names = _as_now()
    names["SALES"] = "Accounts"
    client.post(ROLES, _matrix(caps.keys(), caps, screens, names))
    assert Role.objects.get(group__name="SALES").name == "Sales / Showroom"


def test_a_login_with_no_role_opens_no_gated_screen(client):
    """It used to fall back to Graphic; no role now means no screens."""
    nobody = _user("nobody", None)
    client.force_login(nobody)
    assert client.get(reverse("stock:style_list")).status_code == 403
    assert client.get(reverse("crm:dashboard")).status_code == 403


def test_a_new_role_appears_in_the_add_user_form(client, admin_user_):
    client.force_login(admin_user_)
    client.post(ROLES, {"new_role": "Store manager", "copy_from": "SALES"})
    page = client.get(reverse("stock:settings") + "?tab=users").content.decode()
    assert '<option value="STORE_MANAGER">Store manager</option>' in page


# ── stock pages check their screen too ───────────────────────────────────
def test_the_design_library_browses_pieces_but_cannot_act_on_them(client, graphic_user, piece):
    """Graphic manages piece photos, so it reaches pieces — but never sells or moves one."""
    client.force_login(graphic_user)
    assert client.get(reverse("stock:piece_list")).status_code == 200
    assert client.get(reverse("stock:piece_detail", args=[piece.jewel_code])).status_code == 200
    assert client.post(reverse("stock:move_piece", args=[piece.jewel_code])).status_code == 403
    assert client.post(reverse("stock:reserve_piece", args=[piece.jewel_code])).status_code == 403
    assert client.get(reverse("stock:piece_export")).status_code == 403
    assert client.get(reverse("stock:count_list")).status_code == 403


def test_a_role_without_the_dashboard_lands_on_its_first_screen(client, production_user, graphic_user):
    client.force_login(production_user)
    assert client.get(reverse("stock:dashboard"))["Location"] == reverse("stock:piece_list")
    client.force_login(graphic_user)
    assert client.get(reverse("stock:dashboard"))["Location"] == reverse("stock:style_list")
    nobody = _user("nobody", None)
    client.force_login(nobody)
    assert client.get(reverse("stock:dashboard")).status_code == 403


def test_unticking_stock_and_the_library_closes_the_piece_pages(client, admin_user_, sales_user, piece):
    caps, screens, names = _as_now()
    screens["SALES"] = [s for s in screens["SALES"] if s not in ("stock", "styles")]
    client.force_login(admin_user_)
    client.post(ROLES, _matrix(caps.keys(), caps, screens, names))
    client.force_login(sales_user)
    assert client.get(reverse("stock:piece_list")).status_code == 403
    assert client.get(reverse("stock:piece_detail", args=[piece.jewel_code])).status_code == 403
