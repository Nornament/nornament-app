"""Fetch the front-end assets this app uses, so there is no build step.

Nothing here is committed: the repo carries no third-party minified blob. Run
before ``collectstatic``; ``deploy/Dockerfile`` does at image build time.

Every screen works without any of them. HTMX only saves a page reload. pdf.js
only powers the "read this invoice" shortcut — the purchase form it fills in is
the same form you can always type into by hand.
"""
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

ASSETS = {
    "vendor/htmx.min.js": "https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js",
    "vendor/pdf.min.js": "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js",
    "vendor/pdf.worker.min.js": "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js",
}


class Command(BaseCommand):
    help = "Download the vendored front-end assets into static/. Run before collectstatic."

    def add_arguments(self, parser):
        parser.add_argument("--only", help="Fetch just this one target path, e.g. vendor/pdf.min.js")

    def handle(self, *args, **options):
        targets = ASSETS
        if options["only"]:
            targets = {options["only"]: ASSETS[options["only"]]}
        for path, url in targets.items():
            target = Path(settings.BASE_DIR) / "static" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    target.write_bytes(response.read())
            except Exception as error:  # noqa: BLE001 — one asset failing must not stop the rest
                self.stderr.write(self.style.WARNING(f"{path}: {error}"))
                continue
            self.stdout.write(self.style.SUCCESS(f"wrote {target} ({target.stat().st_size} bytes)"))
