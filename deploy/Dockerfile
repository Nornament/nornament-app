# One image, one process. No build step for the front end beyond fetching htmx.
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

# htmx is fetched here rather than committed: no third-party blob in the repo,
# and still no build step. If the fetch fails the app degrades to page loads.
RUN python manage.py vendor_assets || echo "htmx not fetched — the app will use full page loads"

RUN chmod +x deploy/entrypoint.sh deploy/backup.sh
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000
ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
