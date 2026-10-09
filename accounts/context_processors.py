from .capabilities import ALL


def capabilities(request):
    """``{{ caps.view_cost }}`` in any template, so masking reads the same everywhere.

    ``tabs`` and ``role_name`` drive the stock sidebar, which shows a padlock on
    every tab the role cannot open rather than hiding it — the legacy behaviour,
    and the reason nobody has to guess why a colleague sees more screens.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"caps": {perm.split(".", 1)[1]: False for perm in ALL}}
    return {
        "caps": user.capabilities,
        "is_admin": user.is_admin(),
        "role_code": user.role.code if user.role else "",
        "role_name": user.role_name,
        "tabs": user.screens,
    }
