"""Import ``logins.csv`` — the GoTrue password hashes — onto existing users.

The file is ``id, lower(email), encrypted_password`` exported from
``auth.users``. It is a credential file: encrypt it at rest, move it over ssh,
shred it after this command has run.

Everyone keeps the password they have: the hash is written in Django's
``bcrypt$`` form so BCryptPasswordHasher verifies it, and Django re-hashes to
the modern default on that user's first successful login. A row whose hash is
not bcrypt is reported and its user is left needing a reset — never given a
password anybody could guess.
"""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Import Supabase GoTrue bcrypt hashes from logins.csv."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"{path} does not exist")

        imported = skipped = unmatched = 0
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                email = (row.get("email") or "").strip().lower()
                hashed = (row.get("encrypted_password") or "").strip()
                user = User.objects.filter(email__iexact=email).first()
                if user is None and row.get("id"):
                    user = User.objects.filter(legacy_auth_uid=row["id"]).first()
                if user is None:
                    self.stdout.write(self.style.WARNING(f"no user for {email or row.get('id')}"))
                    unmatched += 1
                    continue
                if not hashed.startswith("$2"):
                    self.stdout.write(
                        self.style.WARNING(f"{email}: hash is not bcrypt — left needing a password reset")
                    )
                    if not options["dry_run"]:
                        user.set_unusable_password()
                        user.must_change_password = True
                        user.save(update_fields=["password", "must_change_password"])
                    skipped += 1
                    continue
                if not options["dry_run"]:
                    User.objects.filter(pk=user.pk).update(password=f"bcrypt${hashed}", must_change_password=False)
                imported += 1

        self.stdout.write(f"imported {imported}, needing reset {skipped}, unmatched {unmatched}")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("dry run — nothing written"))
