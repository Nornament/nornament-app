"""The metal-rate ticker that sits in the stock app's top bar.

`SimpleLazyObject` so the query only runs when a template actually reads it —
the CRM shell never does.
"""
from django.conf import settings
from django.utils.functional import SimpleLazyObject


def _metals():
    from .models import Metal

    return list(Metal.objects.order_by("code"))


def ticker(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"nav_metals": SimpleLazyObject(_metals)}


def asset_version(request):
    """A cache-buster for the stylesheet, in development only.

    ``runserver`` serves static files with a Last-Modified and no
    Cache-Control, so a browser applies heuristic freshness and can sit on a
    stale app.css for hours — which reads as "my CSS did nothing" rather than
    as a caching problem. In production ManifestStaticFilesStorage already
    hashes the filename, so this stays out of the way.
    """
    if not settings.DEBUG:
        return {"asset_v": ""}
    sheets = [settings.BASE_DIR / "static" / "css" / name for name in ("app.css", "crm.css")]
    stamps = [int(sheet.stat().st_mtime) for sheet in sheets if sheet.exists()]
    return {"asset_v": f"?v={max(stamps)}" if stamps else ""}
