"""One WebP encoder, used on the way in and by the backfill.

A photo that leaves the phone at 4 MB of JPEG is 4 MB down every wire that ever
shows it. WebP is the same picture at roughly half that, and every browser the
showroom uses has read it for years.

Two modes, chosen by what the image is rather than by a flag:

* **Lossless** for anything with transparency or a palette — logos, scanned
  certificates, screenshots. Lossless WebP is genuinely smaller than PNG.
* **Quality-based** for photographs, where lossless WebP would come out *larger*
  than the JPEG it replaced. ``MEDIA_WEBP_QUALITY`` is the knob; 82 is the point
  where jewellery photos stop showing it on a showroom screen, but that is a
  judgement about these photos on those screens, so it is a setting.

Whatever comes out, it is only kept if it is actually smaller. An encoder that
can make a file bigger and does it anyway is a regression with a nice name.
"""
from django.conf import settings

#: What Pillow can open and we are willing to re-encode. HEIC and AVIF need
#: ``pillow-heif`` registered; without it they simply fail the open and are
#: skipped, which is why they are not listed.
CONVERTIBLE_TYPES = frozenset({"image/jpeg", "image/png", "image/tiff", "image/bmp"})


class NotSmaller(Exception):
    """The WebP came out no smaller than the original. Keep the original."""


def convertible(mime_type):
    return (mime_type or "").split(";", 1)[0].strip().lower() in CONVERTIBLE_TYPES


def webp_key(key):
    """``stock/piece/12/abc.jpg`` -> ``stock/piece/12/abc.webp``, same folder."""
    stem = key.rsplit(".", 1)[0] if "." in (key or "").rsplit("/", 1)[-1] else key
    return f"{stem}.webp"


def webp_name(file_name):
    stem = (file_name or "image").rsplit(".", 1)[0] or "image"
    return f"{stem}.webp"


def encode(data, quality=None):
    """``(webp_bytes, width, height)`` — or raise if it is not worth keeping.

    Raises :class:`NotSmaller` when the result is no smaller than the input, and
    lets Pillow's own errors through when the bytes are not an image at all.
    """
    import io

    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        image.load()
        # a palette or an alpha channel means flat art, and flat art is where
        # lossless actually wins; a photograph is not
        lossless = image.mode in ("P", "LA", "PA") or "transparency" in image.info or image.mode == "RGBA"
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if lossless else "RGB")
        buffer = io.BytesIO()
        image.save(
            buffer,
            format="WEBP",
            lossless=lossless,
            quality=100 if lossless else (quality or settings.MEDIA_WEBP_QUALITY),
            method=6,  # slowest, smallest — this runs once per image, ever
        )
        out = buffer.getvalue()
        if len(out) >= len(data):
            raise NotSmaller(f"{len(out)} >= {len(data)} bytes")
        return out, image.width, image.height
