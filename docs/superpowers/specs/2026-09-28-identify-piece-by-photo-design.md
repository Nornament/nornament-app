# Identify a piece by photo — design

**Date:** 2026-09-28
**Status:** approved, ready for planning
**Reference:** [tikendraw/reverse-image-search](https://github.com/tikendraw/reverse-image-search) —
same idea (embed every image, nearest-neighbour the query), different parts: no torch,
no ChromaDB, no Streamlit.

## Why

Staff pick up a physical piece whose tag is gone — at the counter, at an
exhibition — and need its jewel code, state and price. Today the only way is
to scroll the stock list by eye. They should be able to point a phone at it.

## Scope

**In:** identifying *our own* physical pieces (`stock.Piece`) from a phone
photo, against the piece's own `PHOTO` media.
**Out:** matching customer or outside photos to "closest designs", falling back
to CAD / pencil / render images for pieces with no photo, pgvector, a task
queue, and saving the query photo anywhere.

A piece with no `PHOTO` cannot be found. That is accepted: the screen says how
many pieces are searchable, and every photo uploaded from here on is
searchable the moment its upload is confirmed. (Locally, 183 photos cover
about 56 of 214 pieces.)

## Constraints that shaped it

- The VPS is 2 GB / 2 vCPU running Postgres, and gunicorn with 3 workers. torch is
  out.
- Postgres is `postgres:17-alpine` — no pgvector. At a few hundred to a few
  thousand photos, a brute-force cosine similarity in numpy takes under a millisecond, so we
  do not need it.
- No signals and no queue in this codebase: side effects are explicit calls
  from views and services. We follow that.

## The engine

**Model:** DINOv2-small, ONNX export, fp32 —
`onnx-community/dinov2-small` at revision
`8b1f705a3a7f6f062f6bdd21986c1583d3ef105d`, file `onnx/model.onnx`,
88,532,934 bytes, sha256
`f22797eabf810a75e41de68d378541ebea372122b25c4ce3ef25ff618250c20a`.
DINOv2 is trained for recognising the same object across photos, which is
this task; the reference repo's EfficientNet-B0 is a classifier backbone and
weaker at it. Runtime is `onnxruntime` (CPU) + `numpy`; both are new
requirements.

**`embed(image_bytes) -> list[float]`**, one function in a new
`stock/identify.py`:

1. Pillow open, `ImageOps.exif_transpose` (phone photos are stored sideways
   and rotated by EXIF), convert RGB.
2. Resize shortest edge to 256 (bicubic), centre-crop 224×224, scale to
   0–1, normalise with mean `(0.485, 0.456, 0.406)` / std
   `(0.229, 0.224, 0.225)`, NCHW float32 — exactly the model's
   `preprocessor_config.json`.
3. Run the session; take the CLS token — `pooler_output` if the export
   has it, else `last_hidden_state[:, 0]` (384 floats; confirm the output
   names from the session at implementation). L2-normalise so cosine
   similarity is a dot product.

The `InferenceSession` is built once per process on first use (module-level,
lazy). Workers that never embed never load it.
`# ponytail: one session per gunicorn worker (~200 MB each); a single
embedder sidecar if memory gets tight.`

**Where the model file comes from:** the Dockerfile fetches it at build time
with `ADD --checksum=sha256:… <pinned URL> /app/models/dinov2-small.onnx`.
A missing or altered file fails the build loudly — the same lesson that got
htmx committed instead of fetched. It is not in `static/` (whitenoise
would serve it) and not in git. `settings.IDENTIFY_MODEL_PATH` points at it;
local dev downloads it once with the same URL (documented in the RUNBOOK).

## Storage

`MediaAsset.embedding = ArrayField(FloatField(), null=True, blank=True)`,
one migration. `null` means "not embedded yet".

## Keeping embeddings current

- **On upload:** `mediahub/views.py` already calls `_shrink(asset, data)`
  after `confirm` and `proxy_upload`. `attach_uploads` is also how the IVY
  stock importer attaches piece photos; that path (and `import_device_backup`)
  is covered by the backfill rather than a hook, so a bulk import is never
  slowed by ~0.3 s of model time per image.
  Next to each, call `_embed(asset, data)` —
  only for `kind=PHOTO` with a `piece` — fetching bytes with
  `storage.get_bytes` when they are not already in hand. It runs after the
  WebP re-encode, and it is best-effort: an exception is logged and the upload
  still succeeds, like `_shrink`.
- **Backfill:** `manage.py embed_media [--dry-run] [--limit N]`, shaped
  like `media_to_webp`: selects piece `PHOTO` rows, not archived, confirmed,
  `embedding IS NULL`; per-row try/except; a summary line at the end.
  Idempotent: an embedded row is skipped next pass. Run once after deploy, and
  after any bulk import.

## Search

`search(user, query_vec, k=5)` in `stock/identify.py`:

1. Candidates: `MediaAsset` rows with `kind=PHOTO`, `is_archived=False`,
   `confirmed_at` set, `embedding` not null, whose `piece` is in
   `Piece.objects.visible_to(user)`. Location scoping is applied **before**
   ranking so a piece the user cannot see never appears.
2. Stack embeddings into a numpy matrix, dot with the query, and keep the best
   photo per piece.
3. Return the top `k` pieces with their score and the matching photo.

`# ponytail: brute force over all visible photos; pgvector when this passes
~50k photos.`

## The screen

- URL `stock/identify/` (`stock:identify`), nav entry "Identify piece" under
  Operations. It uses the existing `stock` tab (`tab_required("stock")`), so ADMIN,
  ACCOUNTS, SALES and PRODUCTION get it with no new tab in `ROLE_TABS`.
- GET: a single large button,
  `<input type="file" name="photo" accept="image/*" capture="environment">`
  — opens the rear camera on a phone and the file picker on a desktop. Beneath it:
  "N of M pieces searchable".
- POST (htmx, `hx-encoding="multipart/form-data"`; also works as a plain form
  POST without htmx): embed the upload in memory, search, render the results
  partial. The query photo is not stored.
- Results: up to 5 cards. Each card shows the matched photo (presigned URL,
  as the media panel does), jewel code, style, stock state, location, match %,
  and links to piece detail. Each card's data comes from `masking.piece_row(user, piece)` — SALES
  sees sale price, never cost / vendor / margin.
- If the top score is below `settings.IDENTIFY_MIN_SCORE` (default to be
  set from the first real photos; start at 0.5): show "No confident match"
  above the cards rather than hiding them.
- Errors: the file is not an image, or is bigger than 15 MB → a message in the
  results area, 400. Model file missing → "Photo search isn't set up on
  this server", 503, and logged.
- Layout reuses `base.html` and its phone drawer; no new CSS framework, no
  JS beyond htmx.

## Tests

- **Fake embedder** (monkeypatched `embed`), so CI never needs the 88 MB
  model:
  - ranking puts the right piece first and keeps one card per piece;
  - a piece at a location the user cannot see is never returned;
  - the screen renders for SALES and shows no gated field — `stock:identify`
    is added to `SALES_SCREENS` in `stock/tests/test_masking.py`, which
    the every-screen walk requires anyway;
  - bad upload → 400, missing model → 503;
  - `embed_media --dry-run` writes nothing; a real run fills `embedding`
    and a second run skips it;
  - upload path: confirming a piece PHOTO sets `embedding`; an embed failure
    does not fail the upload.
- **Real model**, one test, skipped when the model file is absent: the same
  image embeds to cosine ≥ 0.99 with itself, and a rotated/cropped copy
  ranks above an unrelated image.

## Rollout

1. Deploy (migration adds the nullable column; image carries the model).
2. `manage.py embed_media` on the server.
3. Photograph a handful of pieces on a phone, set `IDENTIFY_MIN_SCORE`
   from what real matches and real misses score.
