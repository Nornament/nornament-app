"""Fetch the one front-end asset this app uses, so there is no build step."""
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

HTMX_URL = "https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"


class Command(BaseCommand):
    help = "Download htmx into static/vendor/. Run before collectstatic."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=HTMX_URL)

    def handle(self, *args, **options):
        target = Path(settings.BASE_DIR) / "static" / "vendor" / "htmx.min.js"
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(options["url"], timeout=30) as response:
            target.write_bytes(response.read())
        self.stdout.write(self.style.SUCCESS(f"wrote {target} ({target.stat().st_size} bytes)"))
