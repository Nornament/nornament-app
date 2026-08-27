"""Presign, confirm, serve. Nothing here holds a file for longer than a request.

The browser PUTs straight to Contabo when ``MEDIA_DIRECT_UPLOAD`` is on. If the
Phase 0 CORS smoke test fails, the flag flips and :func:`proxy_upload` takes the
bytes through Django instead — a view change, not a redesign.
"""
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from stock.models import Piece, Style
from . import services, storage
from .models import MediaAsset

CRM_SCOPES = {"customer", "order", "enquiry", "repair", "client_material"}

logger = logging.getLogger(__name__)


def _resolve_owner(scope, entity_id):
    if scope == "piece":
        return {"piece": get_object_or_404(Piece, pk=entity_id)}
    if scope == "style":
        return {"style": get_object_or_404(Style, pk=entity_id)}
    if scope in CRM_SCOPES:
        return {"scope": scope, "scope_id": str(entity_id)}
    raise ValueError(f"unknown media scope {scope!r}")


def _next_media_ref():
    last = MediaAsset.objects.exclude(media_ref=None).order_by("-media_id").values_list("media_ref", flat=True).first()
    number = int(last[1:]) + 1 if last and last[1:].isdigit() else 1
    return f"M{number:06d}"


@login_required
@require_POST
def presign(request):
    """Reserve a row and hand back a one-shot upload URL.

    The row exists before the object does, unconfirmed. A reservation nobody
    completes is a row with no ``confirmed_at`` — visible, sweepable, and never
    mistaken for a photo that is there.
    """
    payload = json.loads(request.body or "{}")
    try:
        owner = _resolve_owner(payload.get("scope"), payload.get("entity_id"))
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    file_name = payload.get("file_name") or "upload.bin"
    content_type = payload.get("mime_type") or storage.guess_mime(file_name)
    if not storage.is_serveable(content_type):
        # the browser names its own content type; an object we would refuse to
        # serve has no business being in the bucket under that name either
        return HttpResponseBadRequest(f"{content_type} is not an accepted media type")
    key = storage.build_key(payload["scope"], payload["entity_id"], file_name)

    asset = MediaAsset.objects.create(
        media_ref=_next_media_ref(),
        kind=payload.get("kind", "PHOTO"),
        storage_key=key,
        file_name=file_name,
        mime_type=content_type,
        bytes=payload.get("bytes"),
        caption=payload.get("caption"),
        uploaded_by=request.user,
        **owner,
    )
    body = {"media_id": asset.pk, "media_ref": asset.media_ref, "key": key, "direct": settings.MEDIA_DIRECT_UPLOAD}
    if settings.MEDIA_DIRECT_UPLOAD:
        try:
            body["url"] = storage.presign_put(key, content_type)
        except storage.StorageNotConfigured as error:
            return JsonResponse({"error": str(error)}, status=503)
    else:
        body["url"] = f"/media/upload/?media_id={asset.pk}"
    return JsonResponse(body)


def _shrink(asset, data=None):
    """Re-encode to WebP once the object is known to be there.

    Best effort by design: the upload has already succeeded and been confirmed
    by this point, so a conversion that fails leaves the original photo intact
    and the row pointing at it. ``manage.py media_to_webp`` picks it up later.
    """
    if not settings.MEDIA_WEBP_ON_UPLOAD:
        return
    try:
        services.to_webp(asset, data)
    except Exception:  # noqa: BLE001 — a smaller file is never worth losing an upload over
        logger.exception("webp conversion failed for media %s", asset.pk)


@login_required
@require_POST
def confirm(request):
    """The browser says the PUT succeeded; we check the object is really there."""
    payload = json.loads(request.body or "{}")
    asset = get_object_or_404(MediaAsset, pk=payload.get("media_id"))
    try:
        head = storage.head(asset.storage_key)
    except storage.StorageNotConfigured as error:
        return JsonResponse({"error": str(error)}, status=503)
    except Exception:
        return JsonResponse({"error": "The object is not in the bucket."}, status=409)
    asset.bytes = head.get("ContentLength", asset.bytes)
    asset.file_size_kb = int((asset.bytes or 0) / 1024) or None
    asset.sha256 = payload.get("sha256", asset.sha256)
    asset.confirmed_at = timezone.now()
    asset.save(update_fields=["bytes", "file_size_kb", "sha256", "confirmed_at"])
    _shrink(asset)
    return JsonResponse(
        {"ok": True, "media_id": asset.pk, "media_ref": asset.media_ref, "bytes": asset.bytes}
    )


@login_required
@require_POST
def proxy_upload(request):
    """The fallback path: bytes through Django, same row, same key."""
    asset = get_object_or_404(MediaAsset, pk=request.GET.get("media_id"))
    upload = request.FILES.get("file")
    if upload is None:
        return HttpResponseBadRequest("no file")
    data = upload.read()
    try:
        storage.put_bytes(asset.storage_key, data, asset.mime_type or storage.guess_mime(asset.file_name))
    except storage.StorageNotConfigured as error:
        return JsonResponse({"error": str(error)}, status=503)
    asset.bytes = len(data)
    asset.file_size_kb = int(len(data) / 1024) or None
    asset.sha256 = storage.sha256_of(data)
    asset.confirmed_at = timezone.now()
    asset.save(update_fields=["bytes", "file_size_kb", "sha256", "confirmed_at"])
    _shrink(asset, data)
    return JsonResponse({"ok": True, "media_id": asset.pk, "bytes": asset.bytes})


@login_required
def media_redirect(request, media_id):
    """A short-lived GET URL. ``ResponseContentType`` so a HEIC renders as JPEG."""
    asset = get_object_or_404(MediaAsset, pk=media_id, is_archived=False)
    if asset.inline_data:
        # Never reached the bucket — the CRM stored these as base64 in the row,
        # so unlike the presigned path this is served from *our* origin. The
        # MIME came out of a data URI header that whoever uploaded through the
        # old CRM controlled, so it is not trusted: anything off the allowlist
        # is handed back as an octet-stream attachment, and the headers stop a
        # sniffing browser or an embedded script from making a photo into XSS.
        serveable = storage.is_serveable(asset.mime_type)
        response = HttpResponse(
            bytes(asset.inline_data),
            content_type=asset.mime_type if serveable else "application/octet-stream",
        )
        name = (asset.file_name or f"{asset.media_ref or asset.pk}").replace('"', "")
        response["Content-Disposition"] = f'{"inline" if serveable else "attachment"}; filename="{name}"'
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, max-age=3600"
        return response
    try:
        url = storage.presign_get(asset.storage_key, asset.mime_type, asset.file_name)
    except storage.StorageNotConfigured:
        return JsonResponse({"error": "media storage is not configured"}, status=503)
    return redirect(url)


@login_required
@permission_required("accounts.edit_bom", raise_exception=True)
@require_POST
def detach(request, media_id):
    """Archive, never delete: the object stays in the bucket, the row stops showing."""
    asset = get_object_or_404(MediaAsset, pk=media_id)
    asset.is_archived = True
    asset.save(update_fields=["is_archived"])
    return JsonResponse({"ok": True})
