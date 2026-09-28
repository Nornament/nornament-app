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
