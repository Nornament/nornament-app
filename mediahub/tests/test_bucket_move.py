"""The copy that moves a bucket without touching a single linkage."""
import pytest

from mediahub import storage


class FakeSource:
    """The old bucket. Hands back bytes, or raises for the one that is gone."""

    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):  # noqa: N803 — boto3's own spelling
        if Key not in self.objects:
            raise RuntimeError("NoSuchKey")
        return {"Body": _Body(self.objects[Key]), "ContentType": "image/jpeg"}


class _Body:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


def test_copies_what_is_missing_and_leaves_what_is_there(monkeypatch):
    destination = {"already/there.jpg": b"old"}
    monkeypatch.setattr(storage, "exists", lambda key, s3=None, bucket=None: key in destination)
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, ct: destination.__setitem__(key, data))
    monkeypatch.setattr(storage, "head", lambda key: {"ok": True})

    source = FakeSource({"already/there.jpg": b"new", "moves/across.jpg": b"bytes"})
    copied, skipped, failures = storage.copy_into_bucket(
        ["already/there.jpg", "moves/across.jpg", "vanished.jpg"], source, "old-bucket"
    )

    assert (copied, skipped) == (1, 1)
    # an object already in the destination is never re-fetched, so it keeps its bytes
    assert destination["already/there.jpg"] == b"old"
    assert destination["moves/across.jpg"] == b"bytes"
    # one unreadable object is reported, not raised — the rest of the run still happened
    assert len(failures) == 1 and failures[0][0] == "vanished.jpg"


@pytest.mark.django_db
def test_the_screen_lists_what_needs_moving(client, django_user_model):
    from mediahub.models import MediaAsset

    MediaAsset.objects.create(scope="customer", scope_id="1", storage_key="crm/a.jpg")
    MediaAsset.objects.create(scope="customer", scope_id="2", inline_data=b"bytes")

    user = django_user_model.objects.create_superuser("mover@nornament.test", "pw")
    user.must_change_password = False
    user.save(update_fields=["must_change_password"])
    client.force_login(user)

    response = client.get("/media/migrate/")
    assert response.status_code == 200
    assert response.context["keyed"] == 1
    assert response.context["inline"] == 1
