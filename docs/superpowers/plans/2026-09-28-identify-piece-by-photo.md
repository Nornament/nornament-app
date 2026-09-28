# Identify a Piece by Photo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A phone screen at `stock/identify/` that takes a camera photo of a piece and shows the five of our pieces it most likely is.

**Architecture:** DINOv2-small (ONNX, run by `onnxruntime`) turns an image into a 384-float unit vector. Each piece `PHOTO` stores its vector on `MediaAsset.embedding` (a plain `ArrayField`). A query photo is embedded in memory and dotted against every visible piece photo in numpy, and the best photo per piece wins. Vectors are written on upload confirm and by a backfill command.

**Tech Stack:** Django 5.2, Postgres 17 (no pgvector), onnxruntime, numpy, Pillow, htmx 2.0.4, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-identify-piece-by-photo-design.md`

## Global Constraints

- No torch, no pgvector, no ChromaDB, no task queue, no Django signals.
- New requirements, exactly: `onnxruntime==1.30.*`, `numpy==2.*`.
- Model: `https://huggingface.co/onnx-community/dinov2-small/resolve/8b1f705a3a7f6f062f6bdd21986c1583d3ef105d/onnx/model.onnx`, sha256 `f22797eabf810a75e41de68d378541ebea372122b25c4ce3ef25ff618250c20a`, 88,532,934 bytes. Never committed to git, never under `static/`.
- Preprocess: EXIF transpose → RGB → shortest edge 256 (bicubic) → centre crop 224 → /255 → mean `(0.485, 0.456, 0.406)` std `(0.229, 0.224, 0.225)` → NCHW float32.
- Only `kind=PHOTO`, piece-owned (`piece_id` set), confirmed, not archived media is searchable. Never filter stock vs CRM media by `storage_key` prefix.
- Candidates are restricted by `Piece.objects.visible_to(user)` **before** ranking. Result rows come from `masking.piece_row(user, piece)`.
- Embedding on upload is best-effort: an exception is logged, the upload still succeeds.
- The query photo is never stored.
- Max upload 15 MB. Not an image → 400. Model file missing → 503.
- Tests never need the real model, except one test that skips when the file is absent.
- Run tests with `.venv/bin/pytest` (Postgres must be running; see README).
- Comments explain *why*, in the codebase's voice; mark deliberate ceilings with `ponytail:`.
- When a step appends code that starts with imports, move those imports into the file's top import block.

## File map

| File | Responsibility |
|---|---|
| `stock/identify.py` (create) | `embed`, `preprocess`, `embed_asset`, `search`, `coverage`, `ModelMissing`, `NotAnImage` |
| `stock/tests/test_identify.py` (create) | engine, search, backfill, upload hook, screen tests |
| `mediahub/models.py` (modify) | `embedding` field |
| `mediahub/migrations/00xx_media_embedding.py` (generated) | the column |
| `mediahub/views.py` (modify) | `_embed` beside `_shrink` in `confirm`/`proxy_upload` |
| `mediahub/management/commands/embed_media.py` (create) | backfill |
| `stock/views.py`, `stock/urls.py` (modify) | `identify_view`, route `stock:identify` |
| `stock/templates/stock/identify.html`, `_identify_results.html` (create) | screen, results partial |
| `stock/templates/stock/_nav.html` (modify) | nav link |
| `stock/tests/test_masking.py` (modify) | register `stock:identify` in `SALES_SCREENS` |
| `config/settings.py`, `requirements.txt`, `deploy/Dockerfile`, `docs/RUNBOOK.md`, `.gitignore` (modify) | settings, deps, model fetch, ops notes |

---

### Task 1: The embedder

**Files:**
- Create: `stock/identify.py`
- Create: `stock/tests/test_identify.py`
- Modify: `requirements.txt`, `config/settings.py`, `.gitignore`

**Interfaces:**
- Produces:
  - `identify.preprocess(data: bytes) -> numpy.ndarray` — shape `(1, 3, 224, 224)`, float32.
  - `identify.embed(data: bytes) -> list[float]` — 384 floats, L2 norm 1.
  - `identify.NotAnImage(Exception)` — Pillow could not open the bytes.
  - `identify.ModelMissing(Exception)` — `settings.IDENTIFY_MODEL_PATH` does not exist.
  - Settings: `IDENTIFY_MODEL_PATH: Path`, `IDENTIFY_MIN_SCORE: float`, `IDENTIFY_MAX_BYTES: int`.

- [ ] **Step 1: Add dependencies and install**

Append to `requirements.txt`:

```
onnxruntime==1.30.*
numpy==2.*
```

Run: `.venv/bin/pip install -r requirements.txt`
Expected: installs onnxruntime and numpy without error.

- [ ] **Step 2: Add settings**

In `config/settings.py`, after the `MEDIA_WEBP_ON_UPLOAD` line:

```python
# ── identify a piece by photo ────────────────────────────────────────────
#: DINOv2-small, ONNX. The Dockerfile fetches it at a pinned revision and
#: checksum; locally, see RUNBOOK "Photo search".
IDENTIFY_MODEL_PATH = Path(env("IDENTIFY_MODEL_PATH", str(BASE_DIR / "models" / "dinov2-small.onnx")))
#: below this cosine similarity the screen says "no confident match". 0.5 is
#: a starting guess; set it from what real phone photos score.
IDENTIFY_MIN_SCORE = float(env("IDENTIFY_MIN_SCORE", "0.5"))
IDENTIFY_MAX_BYTES = 15 * 1024 * 1024
```

(`Path` and `env` are already imported/defined at the top of settings — confirm with `grep -n "^from pathlib\|^def env" config/settings.py`.)

Append to `.gitignore`:

```
/models/
```

- [ ] **Step 3: Download the model locally**

```bash
mkdir -p models
curl -L -o models/dinov2-small.onnx \
  https://huggingface.co/onnx-community/dinov2-small/resolve/8b1f705a3a7f6f062f6bdd21986c1583d3ef105d/onnx/model.onnx
shasum -a 256 models/dinov2-small.onnx
```

Expected: `f22797eabf810a75e41de68d378541ebea372122b25c4ce3ef25ff618250c20a  models/dinov2-small.onnx`

Then check the output names so the CLS pick in Step 5 is right:

```bash
.venv/bin/python -c "import onnxruntime as o; s=o.InferenceSession('models/dinov2-small.onnx'); print([(i.name,i.shape) for i in s.get_inputs()], [(x.name,x.shape) for x in s.get_outputs()])"
```

Expected: input `pixel_values`; outputs include `last_hidden_state` and (probably) `pooler_output`. Step 5's code handles either.

- [ ] **Step 4: Write the failing tests**

Create `stock/tests/test_identify.py`:

```python
"""Identify a piece by photo: the embedder, the search, and the screen.

Everything except one test runs on a fake embedder, so CI never needs the
88 MB model. The one that needs it skips when the file is absent.
"""
import io

import numpy as np
import pytest
from django.conf import settings
from PIL import Image

from stock import identify


def _jpeg(size=(640, 480), colour=(200, 160, 40), exif_orientation=None):
    image = Image.new("RGB", size, colour)
    # a stripe, so a crop or rotation actually changes the picture
    for x in range(size[0] // 3):
        for y in range(size[1]):
            image.putpixel((x, y), (20, 20, 20))
    buffer = io.BytesIO()
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        image.save(buffer, format="JPEG", exif=exif)
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_preprocess_is_the_models_own_recipe():
    pixels = identify.preprocess(_jpeg())
    assert pixels.shape == (1, 3, 224, 224)
    assert pixels.dtype == np.float32
    # a mid-gold pixel from the right of the frame, normalised per channel
    r, g, b = (200 / 255 - 0.485) / 0.229, (160 / 255 - 0.456) / 0.224, (40 / 255 - 0.406) / 0.225
    # abs=0.1 in normalised units is ~6 levels of 255: room for JPEG, not for a wrong mean/std
    assert pixels[0, :, 112, 200] == pytest.approx([r, g, b], abs=0.1)


def test_a_phone_photo_stored_sideways_is_turned_upright_first():
    """Orientation 6 means "rotate 90° to view": the stripe must end up on top."""
    upright = identify.preprocess(_jpeg(size=(480, 640)))
    sideways = identify.preprocess(_jpeg(size=(640, 480), exif_orientation=6))
    assert upright.shape == sideways.shape
    # the dark stripe runs along one edge either way; after transpose the
    # sideways shot's stripe is a top band, not a left band
    assert sideways[0, 0, 5, 112] < sideways[0, 0, 200, 112]


def test_bytes_that_are_not_an_image_are_refused():
    with pytest.raises(identify.NotAnImage):
        identify.preprocess(b"%PDF-1.7 not a photo")


def test_a_missing_model_says_so(settings, tmp_path):
    settings.IDENTIFY_MODEL_PATH = tmp_path / "absent.onnx"
    identify._session.cache_clear()
    with pytest.raises(identify.ModelMissing):
        identify.embed(_jpeg())
    identify._session.cache_clear()


@pytest.mark.skipif(not settings.IDENTIFY_MODEL_PATH.exists(), reason="model file not downloaded")
def test_the_real_model_knows_a_photo_from_a_different_one():
    photo = _jpeg()
    same = np.asarray(identify.embed(photo))
    assert np.linalg.norm(same) == pytest.approx(1.0, abs=1e-4)
    assert same.shape == (384,)
    assert float(same @ np.asarray(identify.embed(photo))) > 0.99

    cropped = Image.open(io.BytesIO(photo)).crop((20, 20, 620, 460)).rotate(8)
    buffer = io.BytesIO()
    cropped.save(buffer, format="JPEG")
    other = io.BytesIO()
    Image.new("RGB", (640, 480), (30, 90, 200)).save(other, format="JPEG")

    near = float(same @ np.asarray(identify.embed(buffer.getvalue())))
    far = float(same @ np.asarray(identify.embed(other.getvalue())))
    assert near > far
```

- [ ] **Step 5: Run the tests to see them fail**

Run: `.venv/bin/pytest stock/tests/test_identify.py -p no:warnings`
Expected: FAIL / ERROR — `cannot import name 'identify' from 'stock'`.

- [ ] **Step 6: Implement `stock/identify.py`**

```python
"""Which of our pieces is this? A phone photo, matched against piece photos.

DINOv2 turns an image into 384 numbers; two photos of the same piece land
close together even across lighting, angle and background, which is the one
thing a classifier backbone is not trained for. The vector for every piece
photo sits on its ``MediaAsset`` row, and a search is a dot product against
all of them — no vector database, because a few thousand rows is a
millisecond of numpy.

The model runs through onnxruntime rather than torch: the VPS has 2 GB, and
torch alone is bigger than everything else in the image put together.
"""
import io
from functools import lru_cache

import numpy as np
from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

#: DINOv2's own ``preprocessor_config.json``
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)
_SHORT_EDGE, _CROP = 256, 224


class NotAnImage(Exception):
    """Pillow could not read it — a PDF, a HEIC, a truncated upload."""


class ModelMissing(Exception):
    """The model file is not on this server, so photo search is off."""


def preprocess(data):
    """Bytes to the ``(1, 3, 224, 224)`` float32 tensor the model expects."""
    try:
        image = Image.open(io.BytesIO(data))
        # a 12 MP JPEG decoded at full size is 36 MB for a 224 px crop; draft
        # lets the decoder skip straight to a smaller scale. No-op for PNG/WebP.
        image.draft("RGB", (_SHORT_EDGE * 2, _SHORT_EDGE * 2))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise NotAnImage(str(error)) from error

    width, height = image.size
    scale = _SHORT_EDGE / min(width, height)
    image = image.resize((round(width * scale), round(height * scale)), Image.Resampling.BICUBIC)
    left = (image.width - _CROP) // 2
    top = (image.height - _CROP) // 2
    image = image.crop((left, top, left + _CROP, top + _CROP))

    pixels = np.asarray(image, dtype=np.float32).transpose(2, 0, 1) / 255.0
    return ((pixels - _MEAN) / _STD)[np.newaxis].astype(np.float32)


@lru_cache(maxsize=1)
def _session():
    """One session per process, built the first time anyone searches.

    ponytail: one copy per gunicorn worker (~200 MB each); move it to a single
    embedder sidecar if the box runs short of memory.
    """
    path = settings.IDENTIFY_MODEL_PATH
    if not path.exists():
        raise ModelMissing(f"no model at {path}")
    import onnxruntime  # heavy; only the processes that embed pay for it

    options = onnxruntime.SessionOptions()
    # two vCPUs shared with Postgres and two other workers: don't let one
    # search spin up a thread per core
    options.intra_op_num_threads = 1
    return onnxruntime.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def embed(data):
    """A unit-length list of 384 floats, so cosine similarity is a dot product."""
    pixels = preprocess(data)
    session = _session()
    names = [output.name for output in session.get_outputs()]
    outputs = session.run(None, {session.get_inputs()[0].name: pixels})
    if "pooler_output" in names:
        vector = outputs[names.index("pooler_output")][0]
    else:
        vector = outputs[names.index("last_hidden_state")][0, 0]  # the CLS token
    vector = vector / np.linalg.norm(vector)
    return vector.astype(float).tolist()
```

- [ ] **Step 7: Run the tests to see them pass**

Run: `.venv/bin/pytest stock/tests/test_identify.py -p no:warnings -v`
Expected: 5 passed (the real-model test runs because Step 3 downloaded the file). If `test_the_real_model…` fails on `pooler_output` vs CLS, print the output names (Step 3) and adjust the branch — don't loosen the assertions.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt config/settings.py .gitignore stock/identify.py stock/tests/test_identify.py
git commit -m "Embed a photo with DINOv2 through onnxruntime"
```

---

### Task 2: Store vectors, and search them

**Files:**
- Modify: `mediahub/models.py`
- Create: `mediahub/migrations/00xx_media_embedding.py` (via `makemigrations`)
- Modify: `stock/identify.py`
- Modify: `stock/tests/test_identify.py`

**Interfaces:**
- Consumes: `identify.embed(data) -> list[float]`.
- Produces:
  - `MediaAsset.embedding: list[float] | None`.
  - `identify.searchable_photos()` → `QuerySet[MediaAsset]` — piece `PHOTO`, confirmed, not archived.
  - `identify.Match` — namedtuple `(piece_id: int, media_id: int, score: float)`.
  - `identify.search(user, query: list[float], k: int = 5) -> list[Match]`, best first, one per piece.
  - `identify.coverage(user) -> dict` with keys `searchable: int`, `total: int`.

- [ ] **Step 1: Add the field**

In `mediahub/models.py`, add the import at the top and the field after `confirmed_at`:

```python
from django.contrib.postgres.fields import ArrayField
```

```python
    # DINOv2 vector of this photo, unit length, for "which piece is this?".
    # Null until embedded — on upload, or by ``manage.py embed_media``.
    embedding = ArrayField(models.FloatField(), null=True, blank=True, editable=False)
```

Run: `.venv/bin/python manage.py makemigrations mediahub -n media_embedding`
Expected: one migration, one `AddField`.

- [ ] **Step 2: Write the failing tests**

Append to `stock/tests/test_identify.py`:

```python
from django.utils import timezone

from mediahub.models import MediaAsset
from stock.enums import MediaKind


def _unit(*values):
    vector = np.zeros(384, dtype=np.float32)
    vector[: len(values)] = values
    return (vector / np.linalg.norm(vector)).tolist()


def _photo(piece, vector, *, kind=MediaKind.PHOTO, archived=False, confirmed=True):
    return MediaAsset.objects.create(
        media_ref=f"M{MediaAsset.objects.count() + 1:06d}",
        piece=piece,
        kind=kind,
        storage_key=f"stock/piece/{piece.pk}/{MediaAsset.objects.count()}.webp",
        file_name="p.webp",
        mime_type="image/webp",
        confirmed_at=timezone.now() if confirmed else None,
        is_archived=archived,
        embedding=vector,
    )


def _another_piece(piece, code):
    from stock.models import Piece

    return Piece.objects.create(
        jewel_code=code, style=piece.style, metal_purity="18K", stock_state=piece.stock_state,
        location=piece.location, current_bom_version=1,
    )


@pytest.mark.django_db
def test_the_closest_piece_comes_first_with_one_card_per_piece(received_piece, admin_user_):
    other = _another_piece(received_piece, "ER00739")
    _photo(received_piece, _unit(1, 0.1))
    _photo(received_piece, _unit(1, 0.05))  # a second, even closer angle
    _photo(other, _unit(0.2, 1))

    matches = identify.search(admin_user_, _unit(1, 0))

    assert [m.piece_id for m in matches] == [received_piece.pk, other.pk]
    assert matches[0].score > 0.99
    assert matches[0].score > matches[1].score


@pytest.mark.django_db
def test_only_confirmed_live_piece_photos_are_candidates(received_piece, admin_user_):
    _photo(received_piece, _unit(1), kind=MediaKind.CAD)
    _photo(received_piece, _unit(1), archived=True)
    _photo(received_piece, _unit(1), confirmed=False)
    assert identify.search(admin_user_, _unit(1)) == []


@pytest.mark.django_db
def test_a_piece_the_user_cannot_see_is_never_returned(received_piece, sales_user, locations):
    """The piece sits in MUM; a HO-only login must not learn it exists."""
    _photo(received_piece, _unit(1))
    sales_user.home_location = locations["HO"]
    sales_user.save(update_fields=["home_location"])
    assert identify.search(sales_user, _unit(1)) == []


@pytest.mark.django_db
def test_coverage_counts_pieces_with_an_embedded_photo(received_piece, admin_user_):
    _another_piece(received_piece, "ER00739")
    _photo(received_piece, _unit(1))
    assert identify.coverage(admin_user_) == {"searchable": 1, "total": 2}
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `.venv/bin/pytest stock/tests/test_identify.py -p no:warnings`
Expected: the four new tests FAIL — `module 'stock.identify' has no attribute 'search'`.

- [ ] **Step 4: Implement search**

Add `from collections import namedtuple` to the import block at the top of `stock/identify.py`, then append:

```python
Match = namedtuple("Match", "piece_id media_id score")


def searchable_photos():
    """The reference set: a piece's own photographs, and nothing else.

    A CAD or render is a drawing, not what a phone sees; a style's media is
    the design, not this physical piece; CRM media belongs to customers.
    Scope is read from ``piece`` and ``kind`` — never from the key prefix.
    """
    from mediahub.models import MediaAsset

    from .enums import MediaKind

    return MediaAsset.objects.filter(
        piece__isnull=False, kind=MediaKind.PHOTO, is_archived=False, confirmed_at__isnull=False
    )


def search(user, query, k=5):
    """The ``k`` pieces whose best photo is closest to ``query``, best first.

    Location scoping happens in the query, before anything is ranked, so a
    piece on a shelf this login cannot see is never even scored.

    ponytail: brute force over every visible photo; pgvector when this
    passes ~50k photos.
    """
    from .models import Piece

    rows = list(
        searchable_photos()
        .filter(embedding__isnull=False, piece__in=Piece.objects.visible_to(user))
        .values_list("pk", "piece_id", "embedding")
    )
    if not rows:
        return []
    scores = np.asarray([row[2] for row in rows], dtype=np.float32) @ np.asarray(query, dtype=np.float32)
    best = {}
    for (media_id, piece_id, _), score in zip(rows, scores.tolist()):
        if piece_id not in best or score > best[piece_id].score:
            best[piece_id] = Match(piece_id, media_id, score)
    return sorted(best.values(), key=lambda match: match.score, reverse=True)[:k]


def coverage(user):
    """How many of the pieces this login can see a photo could find."""
    from .models import Piece

    visible = Piece.objects.visible_to(user)
    embedded = searchable_photos().filter(embedding__isnull=False).values("piece_id")
    return {"searchable": visible.filter(pk__in=embedded).count(), "total": visible.count()}
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `.venv/bin/pytest stock/tests/test_identify.py -p no:warnings -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add mediahub/models.py mediahub/migrations/ stock/identify.py stock/tests/test_identify.py
git commit -m "Keep a vector on each piece photo, and rank pieces against one"
```

---

### Task 3: Keep the vectors current

**Files:**
- Modify: `stock/identify.py`
- Modify: `mediahub/views.py` (`confirm` ~line 120, `proxy_upload` ~line 144)
- Create: `mediahub/management/commands/embed_media.py`
- Modify: `stock/tests/test_identify.py`

`mediahub.services.attach_uploads` only ever creates CRM (`scope`) media, so it needs no hook. The IVY importer and `import_device_backup` are bulk paths: the backfill command covers them (spec: "Run once after deploy, and after any bulk import").

**Interfaces:**
- Consumes: `identify.embed`, `identify.searchable_photos`, `storage.get_bytes(key) -> bytes`.
- Produces:
  - `identify.embed_asset(asset, data: bytes | None = None) -> bool` — sets and saves `asset.embedding`; returns `False` (does nothing) when the asset is not a searchable photo.
  - `mediahub.views._embed(asset, data=None)` — best-effort wrapper.
  - `manage.py embed_media [--dry-run] [--limit N]`.

- [ ] **Step 1: Write the failing tests**

Append to `stock/tests/test_identify.py`:

```python
import json

from django.core.management import call_command
from django.urls import reverse

from mediahub import storage
from mediahub import views as media_views


@pytest.fixture
def fake_embed(monkeypatch):
    """Every photo embeds to the same unit vector; what it was given is recorded."""
    seen = []

    def fake(data):
        seen.append(data)
        return _unit(1)

    monkeypatch.setattr(identify, "embed", fake)
    return seen


@pytest.mark.django_db
def test_embed_asset_skips_anything_that_is_not_a_piece_photo(received_piece, fake_embed):
    cad = _photo(received_piece, None, kind=MediaKind.CAD)
    assert identify.embed_asset(cad, b"bytes") is False
    assert fake_embed == []


@pytest.mark.django_db
def test_embed_asset_fetches_bytes_when_it_is_not_given_them(received_piece, fake_embed, monkeypatch):
    photo = _photo(received_piece, None)
    monkeypatch.setattr(storage, "get_bytes", lambda key: b"from-bucket:" + key.encode())
    assert identify.embed_asset(photo) is True
    photo.refresh_from_db()
    assert photo.embedding == pytest.approx(_unit(1))
    assert fake_embed == [b"from-bucket:" + photo.storage_key.encode()]


@pytest.mark.django_db
def test_confirming_a_piece_photo_embeds_it(client, admin_user_, received_piece, fake_embed, monkeypatch, settings):
    settings.MEDIA_WEBP_ON_UPLOAD = False
    photo = _photo(received_piece, None, confirmed=False)
    monkeypatch.setattr(storage, "head", lambda key: {"ContentLength": 10})
    monkeypatch.setattr(storage, "get_bytes", lambda key: b"jpeg")
    client.force_login(admin_user_)
    response = client.post(
        reverse("mediahub:confirm"), json.dumps({"media_id": photo.pk}), content_type="application/json"
    )
    assert response.status_code == 200
    photo.refresh_from_db()
    assert photo.embedding is not None


@pytest.mark.django_db
def test_an_embedding_failure_never_fails_the_upload(received_piece, monkeypatch):
    photo = _photo(received_piece, None)

    def boom(data):
        raise identify.ModelMissing("no model")

    monkeypatch.setattr(identify, "embed", boom)
    media_views._embed(photo, b"jpeg")  # must not raise
    photo.refresh_from_db()
    assert photo.embedding is None


@pytest.mark.django_db
def test_the_backfill_dry_run_writes_nothing(received_piece, fake_embed):
    photo = _photo(received_piece, None)
    call_command("embed_media", "--dry-run")
    photo.refresh_from_db()
    assert photo.embedding is None
    assert fake_embed == []


@pytest.mark.django_db
def test_the_backfill_fills_once_and_skips_on_the_second_pass(received_piece, fake_embed, monkeypatch):
    photo = _photo(received_piece, None)
    monkeypatch.setattr(storage, "get_bytes", lambda key: b"jpeg")
    call_command("embed_media")
    photo.refresh_from_db()
    assert photo.embedding is not None
    call_command("embed_media")
    assert len(fake_embed) == 1
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/bin/pytest stock/tests/test_identify.py -p no:warnings`
Expected: the six new tests FAIL — no `embed_asset`, no `_embed`, `Unknown command: 'embed_media'`.

- [ ] **Step 3: Implement `embed_asset`**

Append to `stock/identify.py`:

```python
def embed_asset(asset, data=None):
    """Embed one media row in place. ``False`` when it is not a searchable photo.

    ``data`` is the bytes when the caller already has them — the proxy upload
    does; confirm and the backfill do not, and fetch from the bucket.
    """
    if not searchable_photos().filter(pk=asset.pk).exists():
        return False
    if data is None:
        from mediahub import storage

        data = storage.get_bytes(asset.storage_key)
    asset.embedding = embed(data)
    asset.save(update_fields=["embedding"])
    return True
```

Note: `embed` is looked up on the module at call time, so the tests' `monkeypatch.setattr(identify, "embed", …)` reaches it.

- [ ] **Step 4: Hook the upload paths**

In `mediahub/views.py`, add below `_shrink`:

```python
def _embed(asset, data=None):
    """Make a new piece photo findable by "Identify piece".

    Best effort, like ``_shrink``: the upload is already safe in the bucket, and
    a photo that could not be embedded now is picked up by
    ``manage.py embed_media`` later.
    """
    from stock import identify

    try:
        identify.embed_asset(asset, data)
    except Exception:  # noqa: BLE001 — search is never worth losing an upload over
        logger.exception("embedding failed for media %s", asset.pk)
```

In `confirm`, change

```python
    _shrink(asset)
```

to

```python
    _shrink(asset)
    _embed(asset)
```

In `proxy_upload`, change

```python
    _shrink(asset, data)
```

to

```python
    _shrink(asset, data)
    _embed(asset, data)
```

(`_shrink` may repoint `storage_key` at a `.webp`; `_embed` reads the key afterwards, so the confirm path fetches the WebP — same picture.)

- [ ] **Step 5: Write the backfill command**

Create `mediahub/management/commands/embed_media.py`:

```python
"""Give every piece photo already in the bucket its "Identify piece" vector.

New uploads are embedded as they are confirmed. This is the other half: the
photos from before, and anything a bulk import brought in. It is safe to stop
and re-run — an embedded row is skipped next pass because its column is no
longer null.
"""
from django.core.management.base import BaseCommand

from mediahub import storage
from stock import identify


class Command(BaseCommand):
    help = "Embed piece photos that have no vector yet, for photo search."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count what would be embedded and stop.")
        parser.add_argument("--limit", type=int, default=0, help="Stop after this many.")

    def handle(self, *args, **options):
        pending = identify.searchable_photos().filter(embedding__isnull=True).order_by("media_id")
        total = pending.count()
        if options["limit"]:
            pending = pending[: options["limit"]]

        if options["dry_run"]:
            self.stdout.write(f"{total} piece photo(s) have no vector yet.")
            return
        if not total:
            self.stdout.write("Nothing to embed — every piece photo is searchable.")
            return

        embedded = failed = 0
        for asset in pending:
            try:
                identify.embed_asset(asset)
            except (storage.StorageNotConfigured, identify.ModelMissing) as error:
                raise SystemExit(f"Cannot embed on this server: {error}")
            except Exception as error:  # noqa: BLE001 — one bad object must not stop the run
                failed += 1
                self.stderr.write(f"{asset.media_ref or asset.pk}: {error}")
                continue
            embedded += 1

        self.stdout.write(f"embedded {embedded}, failed {failed}, of {total} waiting")
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `.venv/bin/pytest stock/tests/test_identify.py mediahub/tests -p no:warnings`
Expected: all pass (the existing mediahub tests prove `_shrink`'s paths are unchanged).

- [ ] **Step 7: Commit**

```bash
git add stock/identify.py mediahub/views.py mediahub/management/commands/embed_media.py stock/tests/test_identify.py
git commit -m "Embed piece photos on upload, and backfill the ones already there"
```

---

### Task 4: The screen

**Files:**
- Modify: `stock/views.py` (add `identify_view` after `piece_detail`, ~line 581)
- Modify: `stock/urls.py`
- Create: `stock/templates/stock/identify.html`
- Create: `stock/templates/stock/_identify_results.html`
- Modify: `stock/templates/stock/_nav.html`
- Modify: `stock/tests/test_masking.py`
- Modify: `stock/tests/test_identify.py`

**Interfaces:**
- Consumes: `identify.embed`, `identify.search`, `identify.coverage`, `identify.NotAnImage`, `identify.ModelMissing`, `settings.IDENTIFY_MIN_SCORE`, `settings.IDENTIFY_MAX_BYTES`, existing `_visible_pieces(request)`, `piece_row(user, piece)`, `media_services.urls_for(assets)`, `tab_required("stock")`.
- Produces: URL `stock:identify` (GET form, POST results).

- [ ] **Step 1: Write the failing tests**

Append to `stock/tests/test_identify.py`:

```python
from django.core.files.uploadedfile import SimpleUploadedFile


def _upload(data=b"jpeg", name="shot.jpg"):
    return SimpleUploadedFile(name, data, content_type="image/jpeg")


@pytest.mark.django_db
def test_the_screen_opens_the_rear_camera_and_says_what_is_searchable(client, sales_user, received_piece):
    _photo(received_piece, _unit(1))
    client.force_login(sales_user)
    body = client.get(reverse("stock:identify")).content.decode()
    assert 'capture="environment"' in body
    assert "1 of 1" in body


@pytest.mark.django_db
def test_a_photo_finds_the_piece_and_shows_no_cost_to_sales(client, sales_user, received_piece, fake_embed, monkeypatch):
    _photo(received_piece, _unit(1))
    monkeypatch.setattr(storage, "presign_get", lambda *args, **kwargs: "https://bucket.example/p.webp")
    client.force_login(sales_user)
    response = client.post(reverse("stock:identify"), {"photo": _upload()})
    body = response.content.decode()
    assert response.status_code == 200
    assert "ER00738" in body
    assert "No confident match" not in body
    cost = received_piece.current_bom().total_cost_price
    assert f"{cost:,.0f}" not in body and f"{cost:.0f}" not in body


@pytest.mark.django_db
def test_a_weak_best_match_is_shown_but_flagged(client, admin_user_, received_piece, monkeypatch, settings):
    settings.IDENTIFY_MIN_SCORE = 0.9
    _photo(received_piece, _unit(1, 1))  # cosine ~0.71 with the query
    monkeypatch.setattr(identify, "embed", lambda data: _unit(1))
    client.force_login(admin_user_)
    body = client.post(reverse("stock:identify"), {"photo": _upload()}).content.decode()
    assert "No confident match" in body
    assert "ER00738" in body


@pytest.mark.django_db
def test_a_file_that_is_not_a_photo_is_a_400(client, admin_user_):
    client.force_login(admin_user_)
    response = client.post(reverse("stock:identify"), {"photo": _upload(b"%PDF-1.7", "x.pdf")})
    assert response.status_code == 400


@pytest.mark.django_db
def test_no_photo_or_too_big_is_a_400(client, admin_user_, settings):
    client.force_login(admin_user_)
    assert client.post(reverse("stock:identify"), {}).status_code == 400
    settings.IDENTIFY_MAX_BYTES = 3
    assert client.post(reverse("stock:identify"), {"photo": _upload(b"four")}).status_code == 400


@pytest.mark.django_db
def test_a_server_without_the_model_says_so(client, admin_user_, monkeypatch):
    def missing(data):
        raise identify.ModelMissing("no model")

    monkeypatch.setattr(identify, "embed", missing)
    client.force_login(admin_user_)
    response = client.post(reverse("stock:identify"), {"photo": _upload()})
    assert response.status_code == 503
    assert "isn't set up on this server" in response.content.decode()


@pytest.mark.django_db
def test_htmx_gets_just_the_results(client, admin_user_, received_piece, fake_embed):
    _photo(received_piece, _unit(1))
    client.force_login(admin_user_)
    body = client.post(reverse("stock:identify"), {"photo": _upload()}, HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in body
    assert "ER00738" in body


@pytest.mark.django_db
def test_a_login_without_the_stock_tab_is_refused(client, graphic_user):
    client.force_login(graphic_user)
    assert client.get(reverse("stock:identify")).status_code == 403
```

(`test_the_screen_opens…` has no `fake_embed` because a GET never embeds. `test_a_file_that_is_not_a_photo…` uses the real `preprocess`, which raises `NotAnImage` before the model is touched — so it needs no model.)

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/bin/pytest stock/tests/test_identify.py -p no:warnings`
Expected: the eight new tests FAIL — `NoReverseMatch: 'identify' is not a valid view function or pattern name`.

- [ ] **Step 3: Write the view**

In `stock/views.py`, add `import logging` to the stdlib imports, `from django.conf import settings` to the Django imports, and `from . import identify` next to the other local imports. Below the imports, if there is no module logger yet:

```python
logger = logging.getLogger(__name__)
```

(check first: `grep -n "^logger\|^from django.conf import settings\|^from \. import" stock/views.py` — reuse what is there.)

Add after `piece_detail`:

```python
@login_required
@tab_required("stock")
def identify_view(request):
    """Point a phone at an untagged piece; see which of ours it is.

    The photo is embedded in memory and dropped — it is a question, not a
    record, and a shelf of test shots in the bucket is nobody's idea of media.
    """
    context = {"nav": "identify", **identify.coverage(request.user)}
    if request.method != "POST":
        return render(request, "stock/identify.html", context)

    status = 200
    photo = request.FILES.get("photo")
    if photo is None or photo.size > settings.IDENTIFY_MAX_BYTES:
        context["error"] = "Take a photo of the piece — up to 15 MB."
        status = 400
    else:
        try:
            matches = identify.search(request.user, identify.embed(photo.read()))
        except identify.NotAnImage:
            context["error"] = "That file isn't a photo this can read. Try the camera again, or a JPEG."
            status = 400
        except identify.ModelMissing:
            logger.exception("photo search asked for on a server without the model")
            context["error"] = "Photo search isn't set up on this server."
            status = 503
        else:
            context["results"] = _identify_results(request, matches)
            context["confident"] = bool(matches) and matches[0].score >= settings.IDENTIFY_MIN_SCORE

    template = "stock/_identify_results.html" if request.headers.get("HX-Request") else "stock/identify.html"
    return render(request, template, context, status=status)


def _identify_results(request, matches):
    """Cards in match order: the masked row, the photo that matched, a percent."""
    pieces = _visible_pieces(request).in_bulk([match.piece_id for match in matches])
    photos = MediaAsset.objects.in_bulk([match.media_id for match in matches])
    urls = media_services.urls_for(photos.values())
    return [
        {
            "piece": pieces[match.piece_id],
            "row": piece_row(request.user, pieces[match.piece_id]),
            "thumb": urls.get(match.media_id),
            "percent": round(max(match.score, 0) * 100),
        }
        for match in matches
        if match.piece_id in pieces
    ]
```

- [ ] **Step 4: Route it**

In `stock/urls.py`, under the `# ── stock ──` block, before `pieces/<str:jewel_code>/` (so `identify` is never read as a jewel code — it is a different prefix anyway, but keep stock routes together):

```python
    path("identify/", views.identify_view, name="identify"),
```

- [ ] **Step 5: Write the templates**

Create `stock/templates/stock/identify.html`:

```html
{% extends "base.html" %}
{% block title %}Identify piece · Nornament{% endblock %}
{% block content %}
{% comment %}One control: the rear camera. On a desktop the same input is a file
picker. The form works as a plain POST; htmx only saves the page reload. The
before-swap line is because htmx 2 will not swap a 4xx/5xx by default, and
the error message is exactly what the person needs to see.{% endcomment %}
<div class="card" style="max-width:560px;margin:0 auto">
  <h3>Identify piece</h3>
  <p class="hint">Photograph the piece on a plain surface, filling the frame.
    {{ searchable }} of {{ total }} pieces have a photo to match against.</p>
  <form method="post" enctype="multipart/form-data" action="{% url 'stock:identify' %}"
        hx-post="{% url 'stock:identify' %}" hx-encoding="multipart/form-data"
        hx-target="#identify-results" hx-trigger="change" hx-indicator="#identify-busy"
        hx-on::before-swap="if (event.detail.xhr.status >= 400) { event.detail.shouldSwap = true; event.detail.isError = false }">
    {% csrf_token %}
    <label class="btn" style="position:relative;display:block;text-align:center;padding:18px;font-size:16px;cursor:pointer">
      📷 Take a photo
      <input type="file" name="photo" accept="image/*" capture="environment" required
             style="position:absolute;width:1px;height:1px;opacity:0">
    </label>
    <noscript><button class="btn" style="margin-top:10px;width:100%">Search</button></noscript>
  </form>
  <p id="identify-busy" class="htmx-indicator hint" style="text-align:center">Matching…</p>
</div>
<div id="identify-results" style="max-width:960px;margin:16px auto 0">
  {% if request.method == "POST" %}{% include "stock/_identify_results.html" %}{% endif %}
</div>
{% endblock %}
```

Create `stock/templates/stock/_identify_results.html`:

```html
{% comment %}Same card as the Similar tab. The row is ``piece_row`` — already
masked, so a SALES login's cards have no cost to leak.{% endcomment %}
{% if error %}
  <div class="card"><p>{{ error }}</p></div>
{% elif not results %}
  <div class="card"><p>No piece photos to match against yet.</p></div>
{% else %}
    {% if not confident %}<div class="card"><p><strong>No confident match.</strong>
      These are the closest, but check the code on the piece.</p></div>{% endif %}
    <div class="simgrid">
      {% for entry in results %}
      <article class="dcard">
        <a href="{% url 'stock:piece_detail' entry.piece.jewel_code %}">
          {% if entry.thumb %}<img class="jart sq" src="{{ entry.thumb }}" alt="{{ entry.piece.jewel_code }}">{% endif %}</a>
        <div class="m">
          <div style="display:flex;justify-content:space-between;gap:6px">
            <a style="font-family:var(--mono);font-size:12.5px;font-weight:600"
               href="{% url 'stock:piece_detail' entry.piece.jewel_code %}">{{ entry.piece.jewel_code }}</a>
            <span class="chip c-neutral" style="font-size:10.5px">{{ entry.percent }}%</span>
          </div>
          <div style="font-size:12px;color:var(--muted)">{{ entry.row.design_name|default:entry.row.style_code }}</div>
          <div style="margin-top:7px;display:flex;justify-content:space-between;align-items:center;gap:6px">
            {% if caps.view_sale %}<span style="font-family:var(--mono);font-size:12.5px;font-weight:600">₹{{ entry.row.sale_price|default_if_none:0|floatformat:0 }}</span>{% else %}<span></span>{% endif %}
            <span class="chip c-neutral" style="font-size:10.5px">{{ entry.row.stock_state_display }} · {{ entry.row.location|default:"—" }}</span>
          </div>
        </div>
      </article>
      {% endfor %}
    </div>
{% endif %}
```

(The page only includes this partial on POST, so a GET shows no "no photos" message. `caps` comes from the existing context processor, as on the Similar tab.)

- [ ] **Step 6: Add the nav link**

In `stock/templates/stock/_nav.html`, after the Stock link (before Stock Count):

```html
{% url 'stock:identify' as u %}
{% if 'stock' in tabs %}<a href="{{ u }}" {% if nav == 'identify' %}aria-current="page"{% endif %}><span class="ico">⌕</span>Identify piece</a>
{% else %}<button disabled><span class="ico">⌕</span>Identify piece<span class="lockicon">🔒</span></button>{% endif %}
```

- [ ] **Step 7: Register it in the SALES walk**

In `stock/tests/test_masking.py`, add to `SALES_SCREENS` after `("stock:piece_list", {}),`:

```python
    ("stock:identify", {}),
```

- [ ] **Step 8: Run the tests to see them pass**

Run: `.venv/bin/pytest stock/tests/test_identify.py stock/tests/test_masking.py -p no:warnings -v`
Expected: all pass, including `test_every_stock_and_crm_screen_is_in_the_sales_walk`.

- [ ] **Step 9: Try it on a phone**

```bash
.venv/bin/python manage.py embed_media
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

Open `http://<laptop-lan-ip>:8000/stock/identify/` on a phone (add the IP to `ALLOWED_HOSTS` via env if needed). Photograph a piece that has a photo. Expected: the camera opens, "Matching…" shows, and the right jewel code is first. Note the top score of 3–5 real hits and 3–5 pieces that are *not* in the catalogue — these set `IDENTIFY_MIN_SCORE` in the rollout.

- [ ] **Step 10: Commit**

```bash
git add stock/views.py stock/urls.py stock/templates/stock/identify.html stock/templates/stock/_identify_results.html stock/templates/stock/_nav.html stock/tests/test_masking.py stock/tests/test_identify.py
git commit -m "Identify a piece from a phone photo"
```

---

### Task 5: Ship the model with the image

**Files:**
- Modify: `deploy/Dockerfile`
- Modify: `docs/RUNBOOK.md`
- Modify: `docs/superpowers/specs/2026-09-28-identify-piece-by-photo-design.md` (one line)

**Interfaces:**
- Consumes: `settings.IDENTIFY_MODEL_PATH` default `BASE_DIR / "models" / "dinov2-small.onnx"` → `/app/models/dinov2-small.onnx` in the image.

- [ ] **Step 1: Fetch the model at build time, checksummed**

At the very top of `deploy/Dockerfile` (line 1, before the comment):

```dockerfile
# syntax=docker/dockerfile:1
```

After `COPY . .`:

```dockerfile
# The photo-search model. Pinned revision and checksum: a missing or altered
# file fails the build rather than shipping a server whose search is off.
# Not under static/ — whitenoise would serve 88 MB to anyone who asked.
ADD --checksum=sha256:f22797eabf810a75e41de68d378541ebea372122b25c4ce3ef25ff618250c20a \
    https://huggingface.co/onnx-community/dinov2-small/resolve/8b1f705a3a7f6f062f6bdd21986c1583d3ef105d/onnx/model.onnx \
    /app/models/dinov2-small.onnx
```

(It sits after `COPY . .` so the later `chown -R app /app` covers it. `.dockerignore`: if it exists and lists `models/`, that only affects the local copy, not `ADD <url>` — check with `cat .dockerignore`.)

- [ ] **Step 2: Build it**

Run: `docker build -f deploy/Dockerfile -t nornament:identify .`
Expected: success. Then:

```bash
docker run --rm --entrypoint python nornament:identify -c "from django.conf import settings; import django; django.setup(); print(settings.IDENTIFY_MODEL_PATH.stat().st_size)"
```

Expected: `88532934`. If Docker is not available locally, say so in the hand-off and leave this step to the first Dokploy deploy — do not mark it done.

- [ ] **Step 3: Document it**

Add a section to `docs/RUNBOOK.md`:

```markdown
## Photo search ("Identify piece")

Stock → Identify piece takes a phone photo and ranks our pieces by their own
photos. Only pieces with a confirmed `PHOTO` can be found.

- **After deploying it the first time, and after any bulk import:**
  `python manage.py embed_media` (`--dry-run` counts, `--limit N` stops early).
  Re-runnable; it skips photos that already have a vector. New uploads are
  embedded when they are confirmed.
- **Tuning:** `IDENTIFY_MIN_SCORE` (default 0.5) is where the screen starts
  saying "No confident match". Set it between what real matches and
  non-catalogue pieces score.
- **Local dev:** the model is not in git.
  `mkdir -p models && curl -L -o models/dinov2-small.onnx https://huggingface.co/onnx-community/dinov2-small/resolve/8b1f705a3a7f6f062f6bdd21986c1583d3ef105d/onnx/model.onnx`
  Without it the screen answers "isn't set up on this server" and the tests
  that need it skip.
- **Memory:** each gunicorn worker loads the model (~200 MB) the first time
  it serves a search.
```

- [ ] **Step 4: Correct the spec**

In the spec's "Keeping embeddings current" section, replace the sentence naming `mediahub/services.attach_uploads` with: "`attach_uploads` only creates CRM media, so it needs no hook; bulk importers are covered by the backfill."

- [ ] **Step 5: Full suite, then commit**

Run: `.venv/bin/pytest -p no:warnings`
Expected: everything passes (the real-model test runs if `models/` has the file).

```bash
git add deploy/Dockerfile docs/RUNBOOK.md docs/superpowers/specs/2026-09-28-identify-piece-by-photo-design.md
git commit -m "Ship the photo-search model in the image, and say how to run it"
```

---

## Rollout (after merge, not a task)

1. Deploy — the migration adds a nullable column; the image carries the model.
2. `python manage.py embed_media` on the server.
3. Photograph a handful of pieces; set `IDENTIFY_MIN_SCORE` from the scores.
