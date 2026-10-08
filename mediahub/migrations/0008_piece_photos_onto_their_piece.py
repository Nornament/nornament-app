"""Hang import-attached piece photos off their piece, where the screens look.

The IVY importer saved each photo with ``scope='piece'`` and the piece's id
as text, never setting the ``piece`` FK that piece pages read — so the photos
were stored and shown nowhere. Moves any such row onto its piece; a row whose
piece no longer exists is left for the stock wipe, which matches on scope.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    MediaAsset = apps.get_model("mediahub", "MediaAsset")
    Piece = apps.get_model("stock", "Piece")
    stray = MediaAsset.objects.filter(scope="piece", piece__isnull=True)
    live = set(Piece.objects.values_list("pk", flat=True))
    for asset in stray.iterator():
        if asset.scope_id and asset.scope_id.isdigit() and int(asset.scope_id) in live:
            asset.piece_id = int(asset.scope_id)
            asset.scope = asset.scope_id = None
            asset.save(update_fields=["piece", "scope", "scope_id"])


class Migration(migrations.Migration):
    dependencies = [("mediahub", "0007_media_embedding"), ("stock", "0011_restore_reference")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
