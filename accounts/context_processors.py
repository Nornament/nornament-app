from .capabilities import ALL, ROLE_GROUPS, ROLE_TABS


def _role_code(user):
    """The one role group this user is in, or ADMIN for a superuser.

    The legacy app read `role` off the session and looked the whole thing up in
    `ROLES`. A Django user is in exactly one role group by policy, so the same
    lookup works — a user in none behaves as the most restricted role rather
    than crashing the nav.
    """
    if user.is_superuser:
        return "ADMIN"
    code = user.groups.values_list("name", flat=True).first()
    return code if code in ROLE_GROUPS else "GRAPHIC"


def capabilities(request):
    """``{{ caps.view_cost }}`` in any template, so masking reads the same everywhere.

    ``tabs`` and ``role_name`` drive the stock sidebar, which shows a padlock on
    every tab the role cannot open rather than hiding it — the legacy behaviour,
    and the reason nobody has to guess why a colleague sees more screens.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"caps": {perm.split(".", 1)[1]: False for perm in ALL}}
    code = _role_code(user)
    return {
        "caps": user.capabilities,
        "is_admin": user.is_admin(),
        "role_code": code,
        "role_name": ROLE_GROUPS[code]["name"],
        "tabs": ROLE_TABS[code],
    }
