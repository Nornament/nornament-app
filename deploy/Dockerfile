# syntax=docker/dockerfile:1
# One image, one process. No build step for the front end beyond fetching htmx and pdf.js.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# The photo-search model. Pinned revision and checksum: a missing or altered
# file fails the build rather than shipping a server whose search is off.
# Not under static/ — whitenoise would serve 88 MB to anyone who asked.
ADD --checksum=sha256:f22797eabf810a75e41de68d378541ebea372122b25c4ce3ef25ff618250c20a \
    https://huggingface.co/onnx-community/dinov2-small/resolve/8b1f705a3a7f6f062f6bdd21986c1583d3ef105d/onnx/model.onnx \
    /app/models/dinov2-small.onnx

# htmx is committed, so a build with no route to unpkg still ships a working UI.
# pdf.js is still fetched; losing it costs the invoice reader and nothing else.
RUN python manage.py vendor_assets || echo "pdf.js not fetched — no invoice reader, everything else unaffected"

RUN chmod +x deploy/entrypoint.sh deploy/backup.sh
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000
ENTRYPOINT ["deploy/entrypoint.sh"]
# threads: most requests wait on Postgres or the bucket, and with 3 plain
# workers one slow request held a third of the site for everyone else
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--worker-class", "gthread", "--threads", "4", "--timeout", "60", "--access-logfile", "-"]
