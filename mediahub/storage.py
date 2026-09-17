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


#: Extensions that belong in the bucket but never come back from our origin.
#:
#: A studio TIFF, a Rhino file and a zip of STLs are all legitimate stock media
#: and none of them is in :data:`SERVEABLE_TYPES`, because a browser cannot
#: draw them and we will not hand them back same-origin. They are fetched with
#: a presigned GET straight from the bucket instead, so widening this does not
#: widen what this app will serve — :func:`is_serveable` still decides that.
STORABLE_SUFFIXES = frozenset(
    {
        ".tif", ".tiff",
        ".3dm", ".stl", ".obj", ".step", ".stp", ".iges", ".igs", ".dwg", ".dxf",
        ".zip", ".rar",
    }
)


#: What an ``<img>`` can actually draw, which is narrower than "an image".
#:
#: A studio TIFF and an iPhone HEIC are images and are stored as such, but only
#: Safari draws HEIC and nothing draws TIFF, so a tile that puts them in an
#: ``<img>`` renders an empty box. They get a file card and a "no preview" note
#: instead. Upload-time WebP conversion turns most of them into a drawable row
#: anyway; this is what the screen does when it could not.
DRAWABLE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"})


def is_serveable(mime_type):
    return (mime_type or "").split(";", 1)[0].strip().lower() in SERVEABLE_TYPES


def is_drawable(mime_type):
    return (mime_type or "").split(";", 1)[0].strip().lower() in DRAWABLE_TYPES


def is_storable(mime_type, file_name=None):
    """May this file go into the bucket at all? Wider than :func:`is_serveable`."""
    if is_serveable(mime_type):
        return True
    name = (file_name or "").lower()
    return any(name.endswith(suffix) for suffix in STORABLE_SUFFIXES)


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


def get_bytes(key):
    return client().get_object(Bucket=settings.MEDIA_BUCKET, Key=key)["Body"].read()


def delete_keys(keys, chunk=1000):
    """Remove objects from the bucket, in batches of 1000 — the S3 API's limit.

    Returns the keys the bucket refused, so a caller can report what it failed
    to remove rather than claim a clean sweep it did not get. A key that is
    already gone is not an error: the end state is what was asked for.
    """
    keys = [key for key in keys if key]
    failed = []
    for start in range(0, len(keys), chunk):
        batch = keys[start : start + chunk]
        response = client().delete_objects(
            Bucket=settings.MEDIA_BUCKET, Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True}
        )
        failed += [error.get("Key") for error in response.get("Errors", [])]
    return failed


def remote_client(endpoint_url, access_key, secret_key, region="auto", addressing_style="path"):
    """A client for some *other* bucket — the one being migrated away from.

    Deliberately not cached, unlike :func:`client`: these credentials arrive on
    a form, live for one request and are never written down anywhere.
    """
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region or "auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": addressing_style or "path"}),
    )


def exists(key, s3=None, bucket=None):
    """Is this object in the bucket? A miss is an answer here, not an error."""
    from botocore.exceptions import ClientError

    try:
        (s3 or client()).head_object(Bucket=bucket or settings.MEDIA_BUCKET, Key=key)
    except ClientError:
        return False
    return True


def copy_into_bucket(keys, source, source_bucket):
    """Pull each key out of ``source`` and into ours, keeping the key identical.

    A GET then a PUT rather than a server-side copy: the two buckets are
    different accounts in different regions, so there is no copy the
    destination could perform on its own. An object already here is skipped,
    which is what makes a re-run cheap and an interrupted run safe.

    Returns ``(copied, skipped, failures)`` — one bad object never stops a run.
    """
    copied = skipped = 0
    failures = []
    for key in keys:
        if exists(key):
            skipped += 1
            continue
        try:
            obj = source.get_object(Bucket=source_bucket, Key=key)
            put_bytes(key, obj["Body"].read(), obj.get("ContentType") or guess_mime(key))
            head(key)  # it moved only when this bucket agrees that it did
        except Exception as error:  # noqa: BLE001 — a bad object is a finding, not a crash
            failures.append((key, str(error)))
            continue
        copied += 1
    return copied, skipped, failures
