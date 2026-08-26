"""Presigned URLs against Contabo S3.

boto3 is imported lazily so the app boots — and the test suite runs — with no
credentials configured at all.
"""
import hashlib
import mimetypes
import uuid
from functools import lru_cache

from django.conf import settings


#: The only content types this app will hand back from its own origin.
#:
#: An asset's MIME comes from the legacy data URI header, which whoever
#: uploaded through the old CRM controlled. Serving ``text/html`` or
#: ``image/svg+xml`` same-origin turns a stored photo into stored XSS with the
#: viewer's session, so anything outside this list is rejected on the way in
#: and coerced to a download on the way out.
SERVEABLE_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/heic",
        "image/heif",
        "image/avif",
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "application/pdf",
    }
)


def is_serveable(mime_type):
    return (mime_type or "").split(";", 1)[0].strip().lower() in SERVEABLE_TYPES


class StorageNotConfigured(RuntimeError):
    pass


@lru_cache(maxsize=1)
def client():
    if not settings.MEDIA_ACCESS_KEY or not settings.MEDIA_ENDPOINT_URL:
        raise StorageNotConfigured("MEDIA_ENDPOINT_URL and MEDIA_ACCESS_KEY are not set")
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.MEDIA_ENDPOINT_URL,
        region_name=settings.MEDIA_REGION,
        aws_access_key_id=settings.MEDIA_ACCESS_KEY,
        aws_secret_access_key=settings.MEDIA_SECRET_KEY,
        config=Config(signature_version="s3v4", s3={"addressing_style": settings.MEDIA_ADDRESSING_STYLE}),
    )


def build_key(scope, entity_id, file_name):
    """``crm/<scope>/<entity>/<uuid>.<ext>`` — the R2 scheme, unchanged.

    A uuid rather than the file name: two phones both send IMG_0001.HEIC.
    """
    suffix = ""
    if "." in (file_name or ""):
        suffix = "." + file_name.rsplit(".", 1)[1].lower()
    prefix = "crm" if scope not in ("style", "piece") else "stock"
    return f"{prefix}/{scope}/{entity_id}/{uuid.uuid4().hex}{suffix}"


def guess_mime(file_name, fallback="application/octet-stream"):
    return mimetypes.guess_type(file_name or "")[0] or fallback


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def presign_put(key, content_type):
    return client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.MEDIA_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.MEDIA_PRESIGN_TTL,
    )


def presign_get(key, content_type=None, download_name=None):
    params = {"Bucket": settings.MEDIA_BUCKET, "Key": key}
    if content_type:
        params["ResponseContentType"] = content_type
    if download_name:
        params["ResponseContentDisposition"] = f'inline; filename="{download_name}"'
    return client().generate_presigned_url("get_object", Params=params, ExpiresIn=settings.MEDIA_PRESIGN_TTL)


def put_bytes(key, data, content_type):
    client().put_object(Bucket=settings.MEDIA_BUCKET, Key=key, Body=data, ContentType=content_type)


def head(key):
    return client().head_object(Bucket=settings.MEDIA_BUCKET, Key=key)
