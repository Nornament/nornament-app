"""Media objects. Keys are unchanged from R2, so the rclone copy is the migration."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from stock.enums import MediaKind


class MediaAsset(models.Model):
    """``app.media_asset``, widened to carry CRM attachments as well.

    A stock asset points at a style or a piece; a CRM asset points at one of the
    CRM entities through ``scope``/``scope_id``. Both live in one bucket under
    one key scheme, which is what makes ``get_many`` one query at render time.
    """

    STOCK_SCOPES = {"style", "piece"}

    media_id = models.BigAutoField(primary_key=True)
    media_ref = models.CharField(max_length=32, unique=True, null=True, blank=True)
    style = models.ForeignKey(
        "stock.Style", null=True, blank=True, on_delete=models.CASCADE, db_column="style_id", related_name="media"
    )
    piece = models.ForeignKey(
        "stock.Piece", null=True, blank=True, on_delete=models.CASCADE, db_column="jewel_code_id", related_name="media"
    )
    # CRM side: ('customer'|'order'|'enquiry'|'repair'|'client_material', <pk>)
    scope = models.CharField(max_length=32, blank=True, null=True)
    scope_id = models.CharField(max_length=64, blank=True, null=True)

    kind = models.CharField(max_length=24, choices=MediaKind.choices, default=MediaKind.PHOTO)
    storage_provider = models.CharField(max_length=16, default="CONTABO")
    storage_key = models.CharField(max_length=500, blank=True, null=True)
    storage_url = models.URLField(max_length=1000, blank=True, null=True)
    thumb_url = models.URLField(max_length=1000, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    mime_type = models.CharField(max_length=120, blank=True, null=True)
    sha256 = models.CharField(max_length=64, blank=True, null=True)
    bytes = models.BigIntegerField(null=True, blank=True)
    caption = models.TextField(blank=True, null=True)
    view_angle = models.CharField(max_length=40, blank=True, null=True)
    rank_order = models.IntegerField(default=100)
    is_catalogue_default = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    width_px = models.IntegerField(null=True, blank=True)
    height_px = models.IntegerField(null=True, blank=True)
    file_size_kb = models.IntegerField(null=True, blank=True)
    derivative_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, db_column="derivative_of", related_name="derivatives"
    )
    derivative_kind = models.CharField(max_length=32, blank=True, null=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, db_column="uploaded_by", related_name="+"
    )
    # The CRM kept its photos as base64 inside the JSONB blob — they were never
    # in a bucket at all. They land here on import so nothing is lost, and
    # ``manage.py push_inline_media`` moves them into object storage and clears
    # this column once credentials exist.
    inline_data = models.BinaryField(
        null=True, blank=True, help_text="Bytes held in the row because the object is not in the bucket yet."
    )
    uploaded_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(
        null=True, blank=True, help_text="Set when the object is known to exist in the bucket. An unconfirmed row is a reservation."
    )

    class Meta:
        db_table = "media_asset"
        ordering = ["rank_order", "media_id"]
        indexes = [
            models.Index(fields=["piece", "rank_order"], name="idx_media_jc"),
            models.Index(fields=["style", "rank_order"], name="idx_media_st"),
            models.Index(fields=["scope", "scope_id"], name="idx_media_scope"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(style__isnull=False)
                    | models.Q(piece__isnull=False)
                    | models.Q(scope__isnull=False)
                ),
                name="media_asset_has_an_owner",
            )
        ]

    def __str__(self):
        return self.media_ref or self.storage_key or str(self.media_id)

    @property
    def is_confirmed(self):
        return self.confirmed_at is not None

    @property
    def is_video(self):
        """An <img> cannot draw a video, so every tile has to ask this first."""
        return self.kind == MediaKind.VIDEO or (self.mime_type or "").startswith("video/")

    @property
    def is_image(self):
        """The only kind an <img> can draw. A KYC PDF gets a file card instead."""
        return not self.is_video and (self.mime_type or "").startswith("image/")
