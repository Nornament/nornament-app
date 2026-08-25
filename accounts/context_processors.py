from .capabilities import ALL


def capabilities(request):
    """``{{ caps.view_cost }}`` in any template, so masking reads the same everywhere."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"caps": {perm.split(".", 1)[1]: False for perm in ALL}}
    return {"caps": user.capabilities, "is_admin": user.is_admin()}
