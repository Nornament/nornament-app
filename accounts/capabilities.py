"""The seven capabilities, plus ``edit_bom``, as Django permissions.

In Supabase these were eight boolean columns on ``app.role``, read by
``app.has_cap()`` from 45 RLS policies and 111 inline gates. Here they are
ordinary permissions on a permission-only model, so ``user.has_perm`` answers
the same question and Django's own machinery (groups, admin, tests) applies.

``edit_bom`` is not in the plan's list of seven but is load-bearing: the SQL's
``app.is_privileged()`` is exactly ``has_cap('editBom')``, and every write
function gates on it. Dropping it would silently open the write path.
"""

VIEW_SALE = "accounts.view_sale"
VIEW_COST = "accounts.view_cost"
VIEW_VENDOR = "accounts.view_vendor"
MANAGE_MATERIALS = "accounts.manage_materials"
VIEW_MARGIN = "accounts.view_margin"
ADJUST_STOCK = "accounts.adjust_stock"
MELT = "accounts.melt"
EDIT_BOM = "accounts.edit_bom"

#: the inventory's rights — the prototype's purchase / job / assort / masters
#: columns. Seeing money reuses view_cost, view_sale and view_margin, so a
#: login sees the same numbers in the inventory as in the stock app.
INV_MASTERS = "accounts.inv_masters"
INV_PURCHASE = "accounts.inv_purchase"
INV_JOB = "accounts.inv_job"
INV_ASSORT = "accounts.inv_assort"

ALL = (
    VIEW_SALE,
    VIEW_COST,
    VIEW_VENDOR,
    MANAGE_MATERIALS,
    VIEW_MARGIN,
    ADJUST_STOCK,
    MELT,
    EDIT_BOM,
    INV_MASTERS,
    INV_PURCHASE,
    INV_JOB,
    INV_ASSORT,
)

#: legacy ``app.has_cap()`` argument -> permission, so ported logic reads the same
LEGACY_NAMES = {
    "sale": VIEW_SALE,
    "cost": VIEW_COST,
    "vendor": VIEW_VENDOR,
    "materials": MANAGE_MATERIALS,
    "margin": VIEW_MARGIN,
    "adjust": ADJUST_STOCK,
    "melt": MELT,
    "editBom": EDIT_BOM,
}

#: which stock tabs a role may open — the legacy app's ``ROLES[role].tabs``,
#: copied across. A tab it does not list is rendered locked, not hidden: the
#: legacy nav showed a padlock so people could see what the role withheld.
ROLE_TABS = {
    "ADMIN": ("dash", "stock", "repairs", "melt", "count", "styles", "reports", "data", "audit", "admin"),
    "ACCOUNTS": ("dash", "stock", "repairs", "count", "styles", "reports"),
    "SALES": ("dash", "stock", "count", "styles"),
    "GRAPHIC": ("styles",),
    "PRODUCTION": ("stock", "repairs", "styles"),
    "KARIGAR": (),
}

#: app.role seed (migration 0004), as groups
ROLE_GROUPS = {
    "ADMIN": {
        "name": "Admin / Owner",
        "caps": ALL,
        "is_system": True,
    },
    "ACCOUNTS": {
        "name": "Accounts",
        "caps": (
            VIEW_COST, VIEW_SALE, MANAGE_MATERIALS, VIEW_VENDOR, VIEW_MARGIN, EDIT_BOM, ADJUST_STOCK,
            INV_MASTERS, INV_PURCHASE, INV_JOB, INV_ASSORT,
        ),
        "is_system": False,
    },
    "SALES": {
        "name": "Sales / Showroom",
        "caps": (VIEW_SALE, MANAGE_MATERIALS),
        "is_system": False,
    },
    "GRAPHIC": {"name": "Graphic / Media", "caps": (), "is_system": False},
    "PRODUCTION": {
        "name": "Production",
        "caps": (MANAGE_MATERIALS, VIEW_VENDOR, EDIT_BOM, INV_JOB),
        "is_system": False,
    },
    #: the prototype's "Karigar desk": posts job-card movements, sees no money
    "KARIGAR": {"name": "Karigar desk", "caps": (INV_JOB,), "is_system": False},
}


def has_cap(user, legacy_name):
    """``app.has_cap('cost')`` in Python, for logic ported straight across."""
    return bool(user and user.is_authenticated and user.has_perm(LEGACY_NAMES[legacy_name]))
