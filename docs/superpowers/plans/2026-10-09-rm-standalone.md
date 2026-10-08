# RM (Stones & Diamonds) Standalone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Stones & Diamonds module (`/inventory/`) out of nornament-app into a new standalone Django project, `nornament-rm`, keeping its behaviour, and remove it from nornament-app.

**Architecture:** Lift and shift. `nornament-rm` is a fresh Django 5.2 project whose `inventory` app is copied from nornament-app nearly verbatim. Everything it borrowed (stock, crm, mediahub, accounts) is replaced by small RM-owned apps: `accounts` (logins, two roles), `core` (rules helpers, activity log, import batches, masking, media storage under `rm/`), `parties` (customers, vendors). nornament-app then loses the module, its tables, rights and the Karigar desk role.

**Tech Stack:** Python 3.12 (Docker) / 3.14 (local venv), Django 5.2, Postgres 17, psycopg 3, gunicorn, whitenoise, openpyxl, Pillow, boto3, pytest + pytest-django; Dokploy compose.

**Spec:** `docs/superpowers/specs/2026-10-09-rm-standalone-design.md` (in nornament-app).

## Global Constraints

- RM is the Stones & Diamonds module only: everything under `/inventory/`. Stock, CRM, mediahub, the legacy folders and every non-`/inventory/` screen in nornament-app are untouched except the removal list in Part B.
- Fully separate: own repo `~/Desktop/Tech/nornament/nornament-rm`, own Postgres database, own logins. No import of, or runtime call to, nornament-app.
- Start fresh: no data is moved. Customers and vendors start blank.
- Two roles. Admin: every right. Staff: `inv_move`, `inv_assort`, `view_sale` only. Staff never sees cost, vendor/karigar names or margin.
- Rights keep today's codenames: `view_sale`, `view_cost`, `view_vendor`, `view_margin`, `inv_masters`, `inv_purchase`, `inv_job`, `inv_assort`, `inv_move`.
- Media: same bucket and keys as nornament-app; every RM object key starts `rm/`.
- The Django admin is superuser-only.
- The GitHub repo `Nornament/nornament-rm` is created only after the owner confirms in chat.
- nornament-app's removal ships in the same change; RM deploys first or alongside.
- Code style: match nornament-app (docstrings that say why, no new dependencies beyond the list above).

## Local environment (both repos)

- Postgres on `127.0.0.1`, user `$USER`. RM's dev database: `nornament_rm`.
- The fake S3 used for local testing: `.venv/bin/moto_server -H 127.0.0.1 -p 5005` (moto is a dev dependency in RM's `requirements-dev.txt`), bucket `nornamentbucket`, keys `test`/`test`, region `us-east-1`.
- nornament-app commands run from `~/Desktop/Tech/nornament/nornament-app` with `set -a; source .env; set +a` first.

---

# Part A — nornament-rm

## File structure

```
nornament-rm/
  manage.py  requirements.txt  requirements-dev.txt  pytest.ini  conftest.py
  .gitignore  .env.example  README.md
  config/   __init__.py settings.py urls.py wsgi.py views.py
  accounts/ __init__.py apps.py models.py capabilities.py roles.py backends.py
            context_processors.py middleware.py forms.py views.py urls.py admin.py
            migrations/ templates/accounts/{login,password_change,users,user_form}.html tests/
  core/     __init__.py apps.py enums.py services.py masking.py models.py storage.py
            media.py workbooks.py admin.py migrations/ tests/
  parties/  __init__.py apps.py models.py forms.py views.py urls.py admin.py
            migrations/ templates/parties/{customers,customer_form}.html tests/
  inventory/  (copied from nornament-app, see Task 5)
  templates/  inventory_base.html  _preloader.html
  static/     css/inventory.css  img/logo.png
  deploy/     Dockerfile entrypoint.sh docker-compose.yml backup.sh
  docs/DEPLOY.md
```

Responsibilities: `accounts` owns who you are and what you may do; `core` owns the cross-cutting helpers inventory calls; `parties` owns who RM trades with; `inventory` is the module; `config` wires them.

---

### Task 1: Scaffold the project

**Files:**
- Create: `nornament-rm/{manage.py,requirements.txt,requirements-dev.txt,pytest.ini,conftest.py,.gitignore,.env.example}`
- Create: `nornament-rm/config/{__init__.py,settings.py,urls.py,wsgi.py,views.py}`
- Test: `nornament-rm/config/tests/test_boot.py` (+ `config/tests/__init__.py`)

**Interfaces:**
- Produces: `config.views.healthz` (URL name `healthz`, path `/healthz`); settings module `config.settings` with `env()`, `env_bool()`, `env_list()`; `AUTH_USER_MODEL = "accounts.User"` (the app arrives in Task 2 — Task 1's settings list only Django's apps plus `core`-less config; add `accounts`, `core`, `parties`, `inventory` in the tasks that create them).

- [ ] **Step 1: Create the folder, git repo and venv**

```bash
mkdir -p ~/Desktop/Tech/nornament/nornament-rm && cd ~/Desktop/Tech/nornament/nornament-rm
git init -b main
python3 -m venv .venv
createdb nornament_rm
```

- [ ] **Step 2: Write requirements**

`requirements.txt`:
```
Django==5.2.*
psycopg[binary]==3.2.*
gunicorn==23.*
whitenoise==6.*
boto3==1.35.*
Pillow==11.*
openpyxl==3.1.*
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==8.*
pytest-django==4.*
moto[server]==5.*
```

Run: `.venv/bin/pip install -q -r requirements-dev.txt`

- [ ] **Step 3: Write `.gitignore` and `.env.example`**

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.env
staticfiles/
*.dump
.DS_Store
```

`.env.example`:
```
DJANGO_SECRET_KEY=dev-only
DJANGO_DEBUG=1
POSTGRES_DB=nornament_rm
POSTGRES_USER=postgres
POSTGRES_HOST=127.0.0.1
MEDIA_BUCKET=nornamentbucket
MEDIA_ENDPOINT_URL=http://127.0.0.1:5005
MEDIA_ACCESS_KEY=test
MEDIA_SECRET_KEY=test
MEDIA_REGION=us-east-1
```
Copy it: `cp .env.example .env` and set `POSTGRES_USER` to your local Postgres user.

- [ ] **Step 4: Write `manage.py`, `config/__init__.py` (empty), `config/wsgi.py`**

`manage.py`:
```python
#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

`config/wsgi.py`:
```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
```

- [ ] **Step 5: Write `config/settings.py`**

Start from nornament-app's `config/settings.py` (read it for the comments' wording) and keep only what RM needs:

```python
"""Django settings for Nornament RM — stones and diamonds, standalone.

Everything that differs between a laptop and the VPS is read from the
environment, as in nornament-app, so ``manage.py check`` runs on a bare checkout.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# A .env beside manage.py, for laptops. Real environment wins.
for _line in (BASE_DIR / ".env").read_text().splitlines() if (BASE_DIR / ".env").exists() else []:
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _key, _value = _line.split("=", 1)
        os.environ.setdefault(_key.strip(), _value.strip())


def env(key, default=None, required=False):
    value = os.environ.get(key, default)
    if required and not value:
        raise RuntimeError(f"{key} must be set")
    return value


def env_bool(key, default=False):
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key, default=""):
    return [item.strip() for item in os.environ.get(key, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-development-key-do-not-deploy")
DEBUG = env_bool("DJANGO_DEBUG", False)
# loopback stays allowed: the container healthcheck reaches gunicorn on 127.0.0.1
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
for loopback in ("localhost", "127.0.0.1"):
    if loopback not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(loopback)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "nornament_rm"),
        "USER": env("POSTGRES_USER", "nornament"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(env("POSTGRES_CONN_MAX_AGE", "60")),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-in"
TIME_ZONE = env("DJANGO_TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# A stock-take sheet renders two fields per pouch; a big box colour passes 1000.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", not DEBUG)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", not DEBUG)
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
if not DEBUG:
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", True)

# ── media: nornament-app's bucket and keys; every RM key starts rm/ ──────
MEDIA_BUCKET = env("MEDIA_BUCKET", "nornamentbucket")
MEDIA_ENDPOINT_URL = env("MEDIA_ENDPOINT_URL", "")
MEDIA_REGION = env("MEDIA_REGION", "auto")
MEDIA_ACCESS_KEY = env("MEDIA_ACCESS_KEY", "")
MEDIA_SECRET_KEY = env("MEDIA_SECRET_KEY", "")
MEDIA_ADDRESSING_STYLE = env("MEDIA_ADDRESSING_STYLE", "path")
MEDIA_PRESIGN_TTL = int(env("MEDIA_PRESIGN_TTL", "900"))
MEDIA_KEY_PREFIX = "rm"

# ── a lookbook's "Enquire" link ──────────────────────────────────────────
#: WhatsApp wins when both are set; empty hides the button.
LOOKBOOK_WHATSAPP = env("LOOKBOOK_WHATSAPP", "")
LOOKBOOK_EMAIL = env("LOOKBOOK_EMAIL", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}
```

- [ ] **Step 6: Write `config/views.py` and `config/urls.py`**

`config/views.py`:
```python
from django.db import connection
from django.http import HttpResponse


def healthz(request):
    """For the container healthcheck: up, and the database answers."""
    with connection.cursor() as cursor:
        cursor.execute("select 1")
    return HttpResponse("ok", content_type="text/plain")
```

`config/urls.py`:
```python
from django.contrib import admin
from django.urls import path

from .views import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
]

admin.site.site_header = "Nornament RM administration"
admin.site.site_title = "Nornament RM"
```

- [ ] **Step 7: Write `pytest.ini` and a root `conftest.py`**

`pytest.ini`:
```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings
python_files = test_*.py
addopts = -q --strict-markers
```

`conftest.py`:
```python
"""Settings and users every test can stand on."""
import pytest


@pytest.fixture(autouse=True)
def _deployment_settings_off(settings):
    """Pin the settings that describe a deployment, not the code: no https
    redirect for the test client, and no manifest static storage."""
    settings.SECURE_SSL_REDIRECT = False
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
```

- [ ] **Step 8: Write the failing boot test**

`config/tests/__init__.py`: empty. `config/tests/test_boot.py`:
```python
import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_healthz_answers(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_no_model_changes_without_migrations():
    call_command("makemigrations", "--check", "--dry-run")
```

- [ ] **Step 9: Run it**

Run: `.venv/bin/python -m pytest config -q`
Expected: 2 passed.

- [ ] **Step 10: Commit**

```bash
git add -A && git commit -m "Scaffold Nornament RM: settings, healthz, test harness"
```

---

### Task 2: accounts — logins, two roles, users screen

**Files:**
- Create: `accounts/{__init__,apps,models,capabilities,roles,backends,context_processors,middleware,forms,views,urls,admin}.py`
- Create: `accounts/migrations/__init__.py` (+ generated `0001_initial.py`)
- Create: `accounts/templates/accounts/{login,password_change,users,user_form}.html`
- Create: `templates/inventory_base.html` (temporary minimal shell; replaced by the real one in Task 5), `templates/_preloader.html` (copied in Task 5; a one-line placeholder file here)
- Modify: `config/settings.py` (apps, middleware, context processor, auth settings), `config/urls.py`, `conftest.py`
- Test: `accounts/tests/{__init__,test_roles,test_auth,test_users}.py`

**Interfaces:**
- Produces:
  - `accounts.capabilities`: constants `VIEW_SALE="accounts.view_sale"`, `VIEW_COST`, `VIEW_VENDOR`, `VIEW_MARGIN`, `INV_MASTERS`, `INV_PURCHASE`, `INV_JOB`, `INV_ASSORT`, `INV_MOVE`; `ALL` (tuple of those 9); `ROLE_GROUPS = {"ADMIN": {"name": "Admin", "caps": ALL}, "STAFF": {"name": "Staff", "caps": (INV_MOVE, INV_ASSORT, VIEW_SALE)}}`.
  - `accounts.models.User` (AbstractUser + `full_name`, `phone`, `must_change_password`), property `capabilities` → `{codename: bool}`, method `is_admin()`.
  - `accounts.models.sync_role_groups()` — idempotent; sets each role group's permissions exactly.
  - `accounts.context_processors._role_code(user)` → `"ADMIN"` | `"STAFF"`; `capabilities(request)` → `caps`, `is_admin`, `role_code`, `role_name`.
  - URL names: `accounts:login`, `accounts:logout`, `accounts:password_change`, `accounts:users`, `accounts:user_add`, `accounts:user_edit` (`<int:pk>`).
  - Test fixtures (root `conftest.py`): `admin_user_`, `staff_user`, `FIXTURE_PASSWORD`, `make_user(username, role, **extra)`.

- [ ] **Step 1: Write the failing role tests**

`accounts/tests/__init__.py`: empty. `accounts/tests/test_roles.py`:
```python
import pytest

from accounts.capabilities import ALL, INV_ASSORT, INV_MOVE, VIEW_SALE

pytestmark = pytest.mark.django_db


def test_admin_holds_every_right(admin_user_):
    assert all(admin_user_.has_perm(perm) for perm in ALL)


def test_staff_holds_only_movements_assorting_and_sale_prices(staff_user):
    held = {perm for perm in ALL if staff_user.has_perm(perm)}
    assert held == {INV_MOVE, INV_ASSORT, VIEW_SALE}


def test_sync_puts_back_exactly_the_role_rights(staff_user):
    from django.contrib.auth.models import Group, Permission

    from accounts.models import sync_role_groups

    staff = Group.objects.get(name="STAFF")
    staff.permissions.add(Permission.objects.get(codename="view_cost"))
    sync_role_groups()
    assert not staff.permissions.filter(codename="view_cost").exists()
```

- [ ] **Step 2: Write `accounts/capabilities.py`**

```python
"""RM's rights: today's inventory codenames, kept so every check reads the same.

Two fixed roles. Admin holds everything. Staff records movements, assorts and
sees sale prices — never cost, vendor or karigar names, or margin.
"""

VIEW_SALE = "accounts.view_sale"
VIEW_COST = "accounts.view_cost"
VIEW_VENDOR = "accounts.view_vendor"
VIEW_MARGIN = "accounts.view_margin"
INV_MASTERS = "accounts.inv_masters"
INV_PURCHASE = "accounts.inv_purchase"
INV_JOB = "accounts.inv_job"
INV_ASSORT = "accounts.inv_assort"
#: everything that moves stock that is not job work, a purchase or an assortment
INV_MOVE = "accounts.inv_move"

ALL = (VIEW_SALE, VIEW_COST, VIEW_VENDOR, VIEW_MARGIN, INV_MASTERS, INV_PURCHASE, INV_JOB, INV_ASSORT, INV_MOVE)

ROLE_GROUPS = {
    "ADMIN": {"name": "Admin", "caps": ALL},
    "STAFF": {"name": "Staff", "caps": (INV_MOVE, INV_ASSORT, VIEW_SALE)},
}
```

- [ ] **Step 3: Write `accounts/models.py`**

```python
from django.contrib.auth.models import AbstractUser, Group
from django.db import models

from .capabilities import ALL


class Capability(models.Model):
    """Permission holder only — it owns no rows and creates no table."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("view_sale", "Can see sale prices"),
            ("view_cost", "Can see cost prices"),
            ("view_vendor", "Can see vendors"),
            ("view_margin", "Can see margins"),
            ("inv_masters", "Can edit records, settings and import stock"),
            ("inv_purchase", "Can post purchases"),
            ("inv_job", "Can post job work"),
            ("inv_assort", "Can split, merge and assort"),
            ("inv_move", "Can record stock movements"),
        ]


class User(AbstractUser):
    full_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    must_change_password = models.BooleanField(
        default=True, help_text="Forces a password change on the next request."
    )

    def __str__(self):
        return self.full_name or self.username

    @property
    def capabilities(self):
        return {perm.split(".", 1)[1]: self.has_perm(perm) for perm in ALL}

    def is_admin(self):
        return self.is_superuser or self.groups.filter(name="ADMIN").exists()


def sync_role_groups():
    """Create both role groups and give each exactly its rights.

    The roles are fixed — there is no rights editor — so this sets rather than
    adds: a right granted by hand in the admin is taken back on the next
    migrate. Idempotent; runs after every migrate and in tests.
    """
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    from .capabilities import ROLE_GROUPS

    content_type, _ = ContentType.objects.get_or_create(app_label="accounts", model="capability")
    by_codename = {}
    for codename, label in Capability._meta.permissions:
        by_codename[codename], _ = Permission.objects.get_or_create(
            codename=codename, content_type=content_type, defaults={"name": label}
        )
    for code, spec in ROLE_GROUPS.items():
        group, _ = Group.objects.get_or_create(name=code)
        group.permissions.set([by_codename[cap.split(".", 1)[1]] for cap in spec["caps"]])
```

- [ ] **Step 4: Write `accounts/apps.py`**

```python
from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _sync(sender, **kwargs):
    from .models import sync_role_groups

    sync_role_groups()


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        post_migrate.connect(_sync, sender=self)
```

- [ ] **Step 5: Write `accounts/backends.py`, `context_processors.py`, `middleware.py`**

`backends.py` — copy nornament-app's `accounts/backends.py` verbatim (username or email, case-insensitive email, timing equalised).

`context_processors.py`:
```python
from .capabilities import ALL, ROLE_GROUPS


def _role_code(user):
    """The one role this user is in. A superuser is Admin; no role reads as Staff,
    the more restricted of the two, rather than crashing the shell."""
    if user.is_superuser:
        return "ADMIN"
    code = user.groups.values_list("name", flat=True).first()
    return code if code in ROLE_GROUPS else "STAFF"


def capabilities(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"caps": {perm.split(".", 1)[1]: False for perm in ALL}}
    code = _role_code(user)
    return {"caps": user.capabilities, "is_admin": user.is_admin(), "role_code": code, "role_name": ROLE_GROUPS[code]["name"]}
```

`middleware.py` — copy only `MustChangePasswordMiddleware` from nornament-app's `accounts/middleware.py` (drop `KarigarDeskMiddleware` and the `_role_code` import).

- [ ] **Step 6: Write `accounts/forms.py`**

Copy nornament-app's `accounts/forms.py` (`LoginForm`, `ChangePasswordForm`, `UserForm`) and change `UserForm`:
- `Meta.fields = ["username", "full_name", "email", "phone", "role", "is_active"]` (no locations);
- labels: `{"full_name": "Name", "is_active": "Can log in"}`;
- in `__init__`, delete the `Location` import and the four `home_location`/`locations` lines;
- keep: role choices from `ROLE_GROUPS`, blank "— choose a role —" first for a new user, `is_active` removed for a new user, password required for a new user, `clean_email` uniqueness, the superuser / self-lockout rules in `clean`, `save()` setting the password with `must_change_password = True` and `groups.set([...])`.

- [ ] **Step 7: Write `accounts/views.py`, `urls.py`, `admin.py`**

`views.py` — copy nornament-app's `LoginView` and `PasswordChangeView` (change `success_url` to `reverse_lazy("inventory:shelf")`) and add:
```python
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from core.services import log

from .forms import UserForm
from .models import User


def _admins_only(user):
    if not user.is_admin():
        raise PermissionDenied("Only an admin manages logins.")


@login_required
def users(request):
    _admins_only(request.user)
    return render(request, "accounts/users.html", {
        "users": User.objects.prefetch_related("groups").order_by("username"),
        "form": UserForm(actor=request.user),
    })


@login_required
def user_add(request):
    _admins_only(request.user)
    form = UserForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        log(request.user, "INSERT", "user", user.pk, f"added {user.username} as {form.cleaned_data['role']}")
        messages.success(request, f"{user} added. They set their own password on first login.")
        return redirect("accounts:users")
    return render(request, "accounts/user_form.html", {"form": form, "account": None})


@login_required
def user_edit(request, pk):
    _admins_only(request.user)
    account = get_object_or_404(User, pk=pk)
    form = UserForm(request.POST or None, instance=account, actor=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        log(request.user, "UPDATE", "user", account.pk, f"edited {account.username}")
        messages.success(request, f"{account} saved.")
        return redirect("accounts:users")
    return render(request, "accounts/user_form.html", {"form": form, "account": account})
```
(`core.services.log` arrives in Task 3; until then this import fails — Task 2 Step 11 runs after Task 3 Step 1 if executed strictly in order, so instead create `core/__init__.py` (empty) and `core/services.py` with `log` now as a stub that Task 3 replaces: write `def log(user, action, table, pk, detail=None, **extra): return None` and note it in the commit message.)

`urls.py`:
```python
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/", views.PasswordChangeView.as_view(), name="password_change"),
    path("users/", views.users, name="users"),
    path("users/new/", views.user_add, name="user_add"),
    path("users/<int:pk>/", views.user_edit, name="user_edit"),
]
```

`admin.py` — register `User` with Django's `UserAdmin` plus a "Nornament RM" fieldset (`full_name`, `phone`, `must_change_password`).

- [ ] **Step 8: Templates**

`templates/inventory_base.html` (temporary, Task 5 overwrites it):
```html
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{% block title %}RM{% endblock %} · Nornament</title></head>
<body>{% if messages %}{% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}{% endif %}{% block content %}{% endblock %}</body></html>
```
`templates/_preloader.html`: an empty file.

`accounts/templates/accounts/login.html` and `password_change.html` — copy nornament-app's `accounts/templates/accounts/login.html` / `password_change.html` (find them with `ls ~/Desktop/Tech/nornament/nornament-app/accounts/templates/accounts ~/Desktop/Tech/nornament/nornament-app/templates/accounts 2>/dev/null`), change `{% extends %}` to `"inventory_base.html"` and every "Nornament" product title to "Nornament RM".

`users.html` — a table (User, Email, Role, Status) with each name linking to `accounts:user_edit`, a superuser chip, and an "+ Add user" `<dialog>` posting to `accounts:user_add` that renders `form` fields except `is_active`. Copy the markup from nornament-app's `stock/templates/stock/settings.html` `{% elif tab == 'users' %}` block and its `userdlg` dialog, dropping the Home location column.

`user_form.html` — copy nornament-app's `stock/templates/stock/user_form.html`, extend `inventory_base.html`, change `{% url 'stock:user_add' %}`/`'stock:user_edit'` to `'accounts:user_add'`/`'accounts:user_edit'` and the Cancel link to `{% url 'accounts:users' %}`.

- [ ] **Step 9: Wire settings, URLs and fixtures**

`config/settings.py`: append `"accounts"` to `INSTALLED_APPS`; append `"accounts.middleware.MustChangePasswordMiddleware"` to `MIDDLEWARE`; append `"accounts.context_processors.capabilities"` to the context processors; add:
```python
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.UsernameOrEmailBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "accounts:login"
# The Django admin is for superusers only.
```
`config/urls.py`: add `path("accounts/", include("accounts.urls")),` and, after `urlpatterns`:
```python
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser
```

`conftest.py` — append:
```python
#: shared by every fixture login; deliberately not a plausible password
FIXTURE_PASSWORD = "fixture-value-not-a-credential"


def make_user(username, role, **extra):
    from django.contrib.auth.models import Group

    from accounts.models import User

    user = User.objects.create_user(username=username, password=FIXTURE_PASSWORD, **extra)
    user.must_change_password = False
    user.save(update_fields=["must_change_password"])
    if role:
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def admin_user_(db):
    return make_user("owner", "ADMIN", full_name="Owner")


@pytest.fixture
def staff_user(db):
    return make_user("showroom", "STAFF", full_name="Showroom")
```

- [ ] **Step 10: Generate the migration**

Run: `.venv/bin/python manage.py makemigrations accounts && .venv/bin/python manage.py migrate`
Expected: `accounts/migrations/0001_initial.py` created; migrate OK.

- [ ] **Step 11: Write the auth and users tests**

`accounts/tests/test_auth.py`:
```python
import pytest
from django.urls import reverse

from conftest import FIXTURE_PASSWORD

pytestmark = pytest.mark.django_db


def test_email_works_as_a_username(client, staff_user):
    staff_user.email = "showroom@example.invalid"
    staff_user.save(update_fields=["email"])
    assert client.login(username="SHOWROOM@example.invalid", password=FIXTURE_PASSWORD)


def test_must_change_password_blocks_every_other_screen(client, staff_user):
    staff_user.must_change_password = True
    staff_user.save(update_fields=["must_change_password"])
    client.force_login(staff_user)
    response = client.get(reverse("accounts:users"))
    assert response.status_code == 302 and response["Location"] == reverse("accounts:password_change")


def test_the_django_admin_turns_away_everyone_but_a_superuser(client, admin_user_):
    admin_user_.is_staff = True
    admin_user_.save(update_fields=["is_staff"])
    client.force_login(admin_user_)
    assert client.get("/admin/").status_code == 302
```

`accounts/tests/test_users.py` — port nornament-app's `accounts/tests/test_user_management.py` with: `reverse("stock:user_add")` → `reverse("accounts:user_add")`, `stock:user_edit` → `accounts:user_edit`; role values `SALES` → `STAFF`, `ACCOUNTS` → `ADMIN`; fixture `sales_user` → `staff_user`; delete `test_the_django_admin_turns_away_everyone_but_a_superuser` (covered above); in `test_a_role_without_the_settings_screen_cannot_manage_users` use `staff_user` and expect 403 for both.

- [ ] **Step 12: Run the tests**

Run: `.venv/bin/python -m pytest accounts config -q`
Expected: all pass.

- [ ] **Step 13: Commit**

```bash
git add -A && git commit -m "accounts: logins, Admin and Staff roles, the users screen, superuser-only admin"
```

---

### Task 3: core — what inventory borrowed from stock and mediahub

**Files:**
- Create: `core/{__init__,apps,enums,services,masking,models,storage,media,workbooks,admin}.py`, `core/migrations/__init__.py` (+ generated `0001_initial.py`)
- Modify: `config/settings.py` (`INSTALLED_APPS` += `"core"`)
- Test: `core/tests/{__init__,test_services,test_masking,test_media,test_workbooks}.py`

**Interfaces:**
- Consumes: `accounts.capabilities` (Task 2).
- Produces (inventory's imports are repointed to exactly these names in Task 5):
  - `core.services`: `ServiceError(ValidationError)`, `require(user, permission, message)`, `log(user, action, table, pk, detail=None, **extra)` → `ActivityLog`.
  - `core.enums.MediaKind` — same values as `stock.enums.MediaKind`.
  - `core.models`: `ActivityLog` (same fields as `stock.models.ActivityLog`), `MediaAsset` (fields below), `ImportBatch` (same fields and `Status` as `stock.models.ImportBatch`, FK `media` → `core.MediaAsset`).
  - `core.masking`: `GATED_FIELDS`, `allowed(user, field_name)`, `mask(user, row)`, `mask_rows(user, rows)`, `visible_fields(user, fields)`.
  - `core.storage`: copied from `mediahub/storage.py`; `build_key(scope, entity_id, file_name)` → `"rm/<scope>/<entity_id>/<uuid><.ext>"`.
  - `core.media`: `attach_uploads(files, scope, entity_id, user, kind=None)` → `(saved, refused)`, `kind_for(mime)`, `next_media_ref()`.
  - `core.workbooks`: `store_workbook(upload, user)` → `MediaAsset`; `workbook_file(batch)` → open binary file; `IMPORT_CACHE` (Path).

- [ ] **Step 1: Write the failing tests**

`core/tests/test_services.py`:
```python
import pytest
from django.core.exceptions import PermissionDenied

from accounts.capabilities import VIEW_COST
from core.models import ActivityLog
from core.services import ServiceError, log, require

pytestmark = pytest.mark.django_db


def test_require_refuses_a_right_the_user_lacks(staff_user):
    with pytest.raises(PermissionDenied, match="no cost"):
        require(staff_user, VIEW_COST, "no cost")


def test_log_writes_one_row(admin_user_):
    log(admin_user_, "UPDATE", "inv_pouch", 7, "edited")
    row = ActivityLog.objects.get()
    assert (row.table_name, row.record_pk, row.user, row.detail) == ("inv_pouch", "7", admin_user_, "edited")


def test_service_error_is_a_validation_error():
    from django.core.exceptions import ValidationError

    assert issubclass(ServiceError, ValidationError)
```

`core/tests/test_masking.py`:
```python
import pytest

from core.masking import mask

pytestmark = pytest.mark.django_db


def test_staff_sees_sale_but_never_cost_vendor_karigar_or_margin(staff_user):
    row = mask(staff_user, {"list_rate": 9, "valuation_rate": 7, "supplier_name": "X",
                            "karigar_name": "K", "margin": 2, "customer_name": "C"})
    assert row["list_rate"] == 9 and row["customer_name"] == "C"
    assert row["valuation_rate"] is None and row["supplier_name"] is None
    assert row["karigar_name"] is None and row["margin"] is None


def test_admin_sees_everything(admin_user_):
    row = mask(admin_user_, {"valuation_rate": 7, "supplier_name": "X"})
    assert row == {"valuation_rate": 7, "supplier_name": "X"}
```

`core/tests/test_media.py`:
```python
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core import media, storage

pytestmark = pytest.mark.django_db


def test_every_key_starts_rm():
    assert storage.build_key("pouch", 12, "front.JPG").startswith("rm/pouch/12/")
    assert storage.build_key("pouch", 12, "front.JPG").endswith(".jpg")


def test_an_upload_is_stored_under_rm_and_rowed(admin_user_, monkeypatch):
    put = {}
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, mime: put.update(key=key))
    saved, refused = media.attach_uploads(
        [SimpleUploadedFile("a.jpg", b"\xff\xd8jpeg", content_type="image/jpeg")], "pouch", 5, admin_user_)
    assert refused == [] and put["key"].startswith("rm/pouch/5/")
    asset = saved[0]
    assert (asset.scope, asset.scope_id, asset.kind, asset.media_ref) == ("pouch", "5", "PHOTO", "M000001")
```

`core/tests/test_workbooks.py`:
```python
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core import storage, workbooks
from core.models import ImportBatch

pytestmark = pytest.mark.django_db


def test_a_workbook_is_cached_then_sent_and_read_back_from_disk(admin_user_, monkeypatch, tmp_path):
    monkeypatch.setattr(workbooks, "IMPORT_CACHE", tmp_path)

    def upload_from(key, fileobj, mime):  # boto3 closes the file it uploads
        fileobj.read()
        fileobj.close()

    monkeypatch.setattr(storage, "upload_from", upload_from)
    asset = workbooks.store_workbook(SimpleUploadedFile("s.xlsx", b"PK-book", content_type="application/vnd.ms-excel"), admin_user_)
    assert asset.storage_key.startswith("rm/import/workbook/") and asset.bytes == 7
    batch = ImportBatch.objects.create(media=asset, source="STONES", created_by=admin_user_)
    with workbooks.workbook_file(batch) as workbook:
        assert workbook.read() == b"PK-book"
```

Run: `.venv/bin/python -m pytest core -q` → Expected: FAIL (`ModuleNotFoundError: core`).

- [ ] **Step 2: Write `core/apps.py`, `core/enums.py`, `core/services.py`**

`core/apps.py`:
```python
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
```

`core/enums.py` — copy `class MediaKind(models.TextChoices)` from nornament-app `stock/enums.py` (lines `class MediaKind` through `SELL_VIDEO`), with `from django.db import models` at the top.

`core/services.py` (replaces the Task 2 stub):
```python
"""The rule helpers every inventory service calls, as nornament-app's stock had them."""
from django.core.exceptions import PermissionDenied, ValidationError


class ServiceError(ValidationError):
    """A rule said no."""


def log(user, action, table, pk, detail=None, **extra):
    from .models import ActivityLog

    return ActivityLog.objects.create(
        table_name=table,
        record_pk=str(pk),
        action=action,
        user=user if getattr(user, "is_authenticated", False) else None,
        detail=detail,
        **extra,
    )


def require(user, permission, message):
    if not (user and user.is_authenticated and user.has_perm(permission)):
        raise PermissionDenied(message)
```

- [ ] **Step 3: Write `core/models.py`**

```python
from django.conf import settings
from django.db import models
from django.utils import timezone

from .enums import MediaKind


class ActivityLog(models.Model):
    """Who changed what. Inventory writes it through ``core.services.log``."""

    ACTIONS = [(a, a.title()) for a in ["INSERT", "UPDATE", "DELETE", "EXPORT", "LOGIN", "IMPORT", "SALE", "REVERSAL"]]

    log_id = models.BigAutoField(primary_key=True)
    table_name = models.CharField(max_length=64)
    record_pk = models.CharField(max_length=120)
    action = models.CharField(max_length=16, choices=ACTIONS)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(default=timezone.now)
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    row_count = models.IntegerField(null=True, blank=True)
    detail = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "activity_log"
        ordering = ["-changed_at"]
        indexes = [models.Index(fields=["table_name", "record_pk", "-changed_at"], name="idx_log_rec")]


class MediaAsset(models.Model):
    """A file in the bucket. RM's files hang off a scope: ``pouch`` photos,
    ``import`` workbooks."""

    media_id = models.BigAutoField(primary_key=True)
    media_ref = models.CharField(max_length=32, unique=True, null=True, blank=True)
    scope = models.CharField(max_length=32)
    scope_id = models.CharField(max_length=64)
    kind = models.CharField(max_length=24, choices=MediaKind.choices, default=MediaKind.PHOTO)
    storage_key = models.CharField(max_length=500, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    mime_type = models.CharField(max_length=120, blank=True, null=True)
    sha256 = models.CharField(max_length=64, blank=True, null=True)
    bytes = models.BigIntegerField(null=True, blank=True)
    file_size_kb = models.IntegerField(null=True, blank=True)
    caption = models.TextField(blank=True, null=True)
    rank_order = models.IntegerField(default=100)
    is_archived = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "media_asset"
        ordering = ["rank_order", "media_id"]
        indexes = [models.Index(fields=["scope", "scope_id"], name="idx_media_scope")]


class ImportBatch(models.Model):
    """One run of a spreadsheet importer, from upload to done."""

    class Status(models.TextChoices):
        UPLOADED = "UPLOADED", "Uploaded"
        REVIEWING = "REVIEWING", "Reviewing"
        COMMITTING = "COMMITTING", "Committing"
        DONE = "DONE", "Done"
        FAILED = "FAILED", "Failed"

    batch_id = models.AutoField(primary_key=True)
    media = models.ForeignKey(MediaAsset, on_delete=models.PROTECT, related_name="import_batches")
    source = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADED)
    decisions = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "import_batch"
        ordering = ["-created_at"]
```

- [ ] **Step 4: Write `core/masking.py`**

Copy nornament-app `stock/masking.py` whole, then:
- change the import to `from accounts.capabilities import INV_JOB, VIEW_COST, VIEW_MARGIN, VIEW_SALE, VIEW_VENDOR`;
- delete the `"material_breakup": MANAGE_MATERIALS,` entry;
- delete the comment line `# (the Karigar desk has no view_vendor), a customer by those who see sales` and replace it with `# a customer by those who see sales`;
- delete `piece_row` and anything that imports from `stock` (if present) — keep `GATED_FIELDS`, `visible_fields`, `allowed`, `mask`, `mask_rows`.

Verify: `grep -n "stock\|MANAGE_MATERIALS" core/masking.py` → no output.

- [ ] **Step 5: Write `core/storage.py` and `core/media.py`**

`core/storage.py` — copy nornament-app `mediahub/storage.py` whole, then replace `build_key` with:
```python
def build_key(scope, entity_id, file_name):
    """``rm/<scope>/<entity>/<uuid>.<ext>`` — RM's corner of the shared bucket.

    A uuid rather than the file name: two phones both send IMG_0001.HEIC.
    """
    suffix = ""
    if "." in (file_name or ""):
        suffix = "." + file_name.rsplit(".", 1)[1].lower()
    return f"{settings.MEDIA_KEY_PREFIX}/{scope}/{entity_id}/{uuid.uuid4().hex}{suffix}"
```
and delete `remote_client`, `exists`, `copy_into_bucket` (bucket moves are nornament-app's tooling). Verify: `grep -n "mediahub\|stock" core/storage.py` → no output.

`core/media.py`:
```python
"""Files off a form POST, into the bucket, onto a row."""
from django.utils import timezone

from . import storage
from .enums import MediaKind
from .models import MediaAsset


def kind_for(mime):
    mime = (mime or "").lower()
    if mime.startswith("video/"):
        return MediaKind.VIDEO
    if mime.startswith("image/"):
        return MediaKind.PHOTO
    return MediaKind.DOCUMENT


def next_media_ref():
    last = MediaAsset.objects.exclude(media_ref=None).order_by("-media_id").values_list("media_ref", flat=True).first()
    number = int(last[1:]) + 1 if last and last[1:].isdigit() else 1
    return f"M{number:06d}"


def attach_uploads(files, scope, entity_id, user, kind=None):
    """Returns ``(saved, refused)``. A file the bucket refuses is reported, never dropped."""
    saved, refused = [], []
    for upload in files or []:
        mime = upload.content_type or storage.guess_mime(upload.name)
        if not storage.is_serveable(mime):
            refused.append(f"{upload.name} ({mime})")
            continue
        data = upload.read()
        key = storage.build_key(scope, entity_id, upload.name)
        try:
            storage.put_bytes(key, data, mime)
        except storage.StorageNotConfigured as error:
            refused.append(f"{upload.name} ({error})")
            continue
        saved.append(MediaAsset.objects.create(
            media_ref=next_media_ref(), kind=kind or kind_for(mime), storage_key=key,
            file_name=upload.name, mime_type=mime, bytes=len(data),
            file_size_kb=int(len(data) / 1024) or None, sha256=storage.sha256_of(data),
            confirmed_at=timezone.now(), uploaded_by=user, scope=scope, scope_id=str(entity_id),
        ))
    return saved, refused
```

- [ ] **Step 6: Write `core/workbooks.py`**

```python
"""An uploaded workbook: kept in the bucket, read back from local disk.

Copied from nornament-app's IVY importer (stock/views._store_workbook and
stock/importers/commit.workbook_file). boto3 closes whatever file it uploads,
so the upload is cached to disk first and the bucket is sent that copy.
"""
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from django.utils import timezone

from . import storage
from .enums import MediaKind
from .media import next_media_ref
from .models import MediaAsset

#: ponytail: per-container and only emptied by a redeploy; a volume with a sweep if uploads pile up
IMPORT_CACHE = Path(tempfile.gettempdir()) / "nornament-rm-imports"


def _cache_path(storage_key):
    return IMPORT_CACHE / storage_key.replace("/", "_")


def store_workbook(upload, user):
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    mime = upload.content_type or storage.guess_mime(upload.name)
    key = storage.build_key("import", "workbook", upload.name)
    IMPORT_CACHE.mkdir(parents=True, exist_ok=True)
    path = _cache_path(key)
    with open(path, "wb") as cached:
        shutil.copyfileobj(upload, cached)
    with open(path, "rb") as workbook:
        storage.upload_from(key, workbook, mime)
    return MediaAsset.objects.create(
        media_ref=next_media_ref(), kind=MediaKind.DOCUMENT, storage_key=key, file_name=upload.name,
        mime_type=mime, bytes=upload.size, file_size_kb=int(upload.size / 1024) or None,
        sha256=digest.hexdigest(), confirmed_at=timezone.now(), uploaded_by=user,
        scope="import", scope_id="workbook",
    )


def workbook_file(batch):
    """The batch's workbook, off local disk; fetched once from the bucket if missing."""
    path = _cache_path(batch.media.storage_key)
    if not path.exists():
        IMPORT_CACHE.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f"{path.name}.{os.getpid()}.part")
        with open(partial, "wb") as workbook:
            storage.download_to(batch.media.storage_key, workbook)
        partial.replace(path)
    return open(path, "rb")
```

- [ ] **Step 7: Register, migrate, and add the root-conftest cache fixture**

`core/admin.py`: `admin.site.register(ActivityLog)`, `admin.site.register(MediaAsset)`, `admin.site.register(ImportBatch)`.
Settings: append `"core"` to `INSTALLED_APPS` (before `accounts` is fine; order does not matter).
Root `conftest.py` — append:
```python
@pytest.fixture(autouse=True)
def _import_cache(monkeypatch, tmp_path):
    """Tests reuse storage keys; a shared cache would serve stale workbooks."""
    monkeypatch.setattr("core.workbooks.IMPORT_CACHE", tmp_path / "imports")
```
Run: `.venv/bin/python manage.py makemigrations core && .venv/bin/python manage.py migrate`

- [ ] **Step 8: Run the tests**

Run: `.venv/bin/python -m pytest core accounts config -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "core: rules helpers, activity log, import batches, masking, media under rm/"
```

---

### Task 4: parties — customers and vendors

**Files:**
- Create: `parties/{__init__,apps,models,forms,views,urls,admin}.py`, `parties/migrations/__init__.py` (+ generated `0001_initial.py`)
- Create: `parties/templates/parties/{customers,customer_form}.html`
- Modify: `config/settings.py`, `config/urls.py`
- Test: `parties/tests/{__init__,test_customers}.py`

**Interfaces:**
- Consumes: `core.services.log`, `require`; `accounts.capabilities.INV_MOVE`.
- Produces:
  - `parties.models.Vendor`: `vendor_id` (AutoField pk), `code` (CharField 32, unique), `name` (120), `contact` (120, blank, null), `city` (80, blank, null), `terms` (60, blank), `avg_tat_days` (Decimal 6,2, null), `is_active` (default True); `db_table = "vendor"`; `__str__` → name.
  - `parties.models.Customer`: `customer_id` (AutoField pk), `customer_code` (CharField 16, unique, generated `C00001`…), `name` (200), `phone` (40, blank), `city` (80, blank), `is_active` (default True); `db_table = "customer"`; `__str__` → name; `Customer.next_code()` classmethod.
  - URL names: `parties:customers`, `parties:customer_add`, `parties:customer_edit` (`<int:pk>`). `customer_add` honours a safe `?next=` and appends `customer=<code>` to it.

- [ ] **Step 1: Write the failing tests**

`parties/tests/test_customers.py`:
```python
import pytest
from django.urls import reverse

from parties.models import Customer

pytestmark = pytest.mark.django_db


def test_codes_count_up():
    Customer.objects.create(customer_code=Customer.next_code(), name="Meera")
    assert Customer.next_code() == "C00002"


def test_staff_adds_a_customer_and_returns_to_the_movement(client, staff_user):
    client.force_login(staff_user)
    back = "/inventory/pouches/NRN-000001/movements/?record=SALE"
    response = client.post(reverse("parties:customer_add") + f"?next={back}", {"name": "Meera", "phone": "98"})
    customer = Customer.objects.get(name="Meera")
    assert customer.customer_code == "C00001"
    assert response["Location"] == back + "&customer=C00001"


def test_an_off_site_next_is_ignored(client, staff_user):
    client.force_login(staff_user)
    response = client.post(reverse("parties:customer_add") + "?next=https://evil.example/", {"name": "X"})
    assert response["Location"] == reverse("parties:customers")


def test_only_admin_edits_and_deactivates(client, staff_user, admin_user_):
    customer = Customer.objects.create(customer_code="C00001", name="Meera")
    client.force_login(staff_user)
    assert client.get(reverse("parties:customer_edit", args=[customer.pk])).status_code == 403
    client.force_login(admin_user_)
    client.post(reverse("parties:customer_edit", args=[customer.pk]), {"name": "Meera S", "phone": "", "city": ""})
    customer.refresh_from_db()
    assert customer.name == "Meera S" and customer.is_active is False  # unticked box
```

Run: `.venv/bin/python -m pytest parties -q` → FAIL (no module).

- [ ] **Step 2: Write `parties/models.py`**

```python
"""Who RM trades with. Its own lists, starting empty — nothing synced from
nornament-app."""
from django.db import models


class Vendor(models.Model):
    """Suppliers and karigars share one list, as in nornament-app. Edited on
    the diamonds Settings → Suppliers tab (``inventory.dia_services.save_supplier``)."""

    vendor_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    contact = models.CharField(max_length=120, blank=True, null=True)
    city = models.CharField(max_length=80, blank=True, null=True)
    terms = models.CharField(max_length=60, blank=True, help_text="Payment terms, e.g. 30 days, Advance.")
    avg_tat_days = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "vendor"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Customer(models.Model):
    customer_id = models.AutoField(primary_key=True)
    customer_code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=40, blank=True)
    city = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "customer"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def next_code(cls):
        last = cls.objects.order_by("-customer_id").values_list("customer_code", flat=True).first()
        number = int(last[1:]) + 1 if last and last[1:].isdigit() else 1
        return f"C{number:05d}"
```

- [ ] **Step 3: Write `parties/forms.py`, `views.py`, `urls.py`, `apps.py`, `admin.py`**

`forms.py`:
```python
from django import forms

from .models import Customer


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "city", "is_active"]
        labels = {"is_active": "Active"}
```

`views.py`:
```python
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from accounts.capabilities import INV_MOVE
from core.services import log, require

from .forms import CustomerForm
from .models import Customer


def _safe_next(request):
    target = request.GET.get("next") or ""
    return target if url_has_allowed_host_and_scheme(target, {request.get_host()}) else ""


@login_required
def customers(request):
    require(request.user, INV_MOVE, "Your role does not handle customers.")
    query = (request.GET.get("q") or "").strip()
    rows = Customer.objects.all()
    if query:
        rows = rows.filter(Q(name__icontains=query) | Q(customer_code__icontains=query) | Q(phone__icontains=query))
    return render(request, "parties/customers.html", {"rows": rows[:500], "q": query})


@login_required
def customer_add(request):
    """Staff may add; a movement form sends them here and gets the code back."""
    require(request.user, INV_MOVE, "Your role does not handle customers.")
    form = CustomerForm(request.POST or None, initial={"is_active": True})
    form.fields.pop("is_active")
    if request.method == "POST" and form.is_valid():
        customer = form.save(commit=False)
        customer.customer_code = Customer.next_code()
        customer.save()
        log(request.user, "INSERT", "customer", customer.pk, customer.customer_code)
        messages.success(request, f"{customer} added as {customer.customer_code}.")
        back = _safe_next(request)
        if back:
            return redirect(back + ("&" if "?" in back else "?") + urlencode({"customer": customer.customer_code}))
        return redirect("parties:customers")
    return render(request, "parties/customer_form.html", {"form": form, "customer": None})


@login_required
def customer_edit(request, pk):
    if not request.user.is_admin():
        raise PermissionDenied("Only an admin edits customers.")
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        form.save()
        log(request.user, "UPDATE", "customer", customer.pk, customer.customer_code)
        messages.success(request, f"{customer} saved.")
        return redirect("parties:customers")
    return render(request, "parties/customer_form.html", {"form": form, "customer": customer})
```

`urls.py`:
```python
from django.urls import path

from . import views

app_name = "parties"

urlpatterns = [
    path("customers/", views.customers, name="customers"),
    path("customers/new/", views.customer_add, name="customer_add"),
    path("customers/<int:pk>/", views.customer_edit, name="customer_edit"),
]
```
`apps.py`: `class PartiesConfig(AppConfig): name = "parties"`. `admin.py`: register `Vendor`, `Customer`.

Templates: `customers.html` extends `inventory_base.html` — search box (`q`), "+ New customer" link to `parties:customer_add`, table Code · Name · Phone · City · Status, name linking to `parties:customer_edit` when `is_admin`. `customer_form.html` extends `inventory_base.html` — renders `form` fields and Save/Cancel (Cancel → `parties:customers`), posting to the current URL including its query string (`action=""`).

- [ ] **Step 4: Wire, migrate, run**

Settings: append `"parties"` to `INSTALLED_APPS`. URLs: `path("parties/", include("parties.urls")),`.
Run: `.venv/bin/python manage.py makemigrations parties && .venv/bin/python manage.py migrate && .venv/bin/python -m pytest parties -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "parties: RM's own customers and vendors, starting empty"
```

---

### Task 5: Move the inventory app across and make it boot

**Files:**
- Create (copied): `inventory/` (code, `templates/inventory/`, `templatetags/`, `importers/`, without `migrations/` and `tests/`), `templates/inventory_base.html`, `templates/_preloader.html`, `static/css/inventory.css`, `static/img/logo.png`
- Create: `inventory/migrations/__init__.py` (+ generated `0001_initial.py`)
- Modify: every copied file that imports `stock`, `crm`, `mediahub`, or `accounts.capabilities` names that no longer exist
- Modify: `config/settings.py`, `config/urls.py`
- Test: `inventory/tests/test_boot.py` (new, kept in Task 6 alongside the ported suite)

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: URL namespace `inventory` (same names as nornament-app); root `/` redirects to `inventory:shelf`; `/lookbook/<token>/` and `/lookbook/<token>/photo/<int:media_id>/` (names `lookbook_public`, `lookbook_photo`).

- [ ] **Step 1: Copy the module**

```bash
SRC=~/Desktop/Tech/nornament/nornament-app; DST=~/Desktop/Tech/nornament/nornament-rm
rsync -a --exclude migrations --exclude tests --exclude __pycache__ $SRC/inventory/ $DST/inventory/
mkdir -p $DST/inventory/migrations && touch $DST/inventory/migrations/__init__.py
cp $SRC/templates/inventory_base.html $SRC/templates/_preloader.html $DST/templates/
mkdir -p $DST/static/css $DST/static/img
cp $SRC/static/css/inventory.css $DST/static/css/ && cp $SRC/static/img/logo.png $DST/static/img/
```

- [ ] **Step 2: Repoint the imports**

Run from `nornament-rm`:
```bash
grep -rl --include='*.py' -E "from (stock|crm|mediahub)|import (stock|crm|mediahub)" inventory | xargs sed -i '' \
  -e 's/from stock\.services import/from core.services import/' \
  -e 's/from stock\.masking import/from core.masking import/' \
  -e 's/from stock\.enums import MediaKind/from core.enums import MediaKind/' \
  -e 's/from stock\.models import ImportBatch, Vendor/from core.models import ImportBatch\nfrom parties.models import Vendor/' \
  -e 's/from stock\.models import ImportBatch/from core.models import ImportBatch/' \
  -e 's/from stock\.models import ActivityLog/from core.models import ActivityLog/' \
  -e 's/from stock\.models import Vendor/from parties.models import Vendor/' \
  -e 's/from crm\.models import Customer/from parties.models import Customer/' \
  -e 's/from mediahub\.models import MediaAsset/from core.models import MediaAsset/' \
  -e 's/from mediahub import storage/from core import storage/' \
  -e 's/from mediahub\.services import attach_uploads/from core.media import attach_uploads/' \
  -e 's/from stock\.views import _batch_workbook, _store_workbook/from core.workbooks import store_workbook as _store_workbook, workbook_file as _batch_workbook/'
sed -i '' -e 's/"stock\.ImportBatch"/"core.ImportBatch"/' -e 's/"stock\.Vendor"/"parties.Vendor"/' -e 's/"crm\.Customer"/"parties.Customer"/' inventory/models.py
grep -rnE "stock|crm|mediahub" --include='*.py' inventory | grep -vE "stock_take|stocked|in_stock|instock|restock|_stock|stock_|\bstock\b[^.]" 
```
Expected: the final grep prints only lines that are not imports (review each by eye; any remaining `import stock.`/`stock.` module reference must be repointed by hand to `core`/`parties`).

Also check for any `from accounts.capabilities import ... MANAGE_MATERIALS|EDIT_BOM|ADJUST_STOCK|MELT|ROLE_TABS` in non-test code:
```bash
grep -rnE "MANAGE_MATERIALS|EDIT_BOM|ADJUST_STOCK|MELT\b|ROLE_TABS" --include='*.py' inventory
```
Expected: no output (if any, delete that name from the import; none of them gate an inventory screen).

- [ ] **Step 3: Replace the CRM `inr` helper**

In `inventory/templatetags/inventory_extras.py` replace `from crm.templatetags import crm_extras` with a local function and use it:
```python
def _inr(value):
    """₹ in the Indian grouping, whole rupees — what crm_extras.inr printed."""
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        return value
    sign, digits = ("-" if number < 0 else ""), str(abs(number))
    head, tail = digits[:-3], digits[-3:]
    while len(head) > 2:
        tail = head[-2:] + "," + tail
        head = head[:-2]
    grouped = (head + "," + tail) if head else tail
    return f"{sign}₹{grouped}"
```
and change both `crm_extras.inr(value)` calls to `_inr(value)`. Then compare with nornament-app's `crm/templatetags/crm_extras.py` `inr` (open it) and copy its exact body instead if it differs (decimals, negative style) — the output must be identical.

- [ ] **Step 4: Fixed roles: the role preview and the rights editor**

- `inventory/dia_services.py`: `ROLE_ORDER = ["ADMIN", "STAFF"]`; delete `set_right` and its `Group`/`Permission` imports if now unused.
- `inventory/views_dia_settings.py`: delete `_rights_matrix`, `right_toggle`, and the `rights`/`matrix`/`me` context entries; `inventory/urls.py`: delete the `dia_right_toggle` path; in the diamonds settings template (`grep -rln "dia_right_toggle\|matrix" inventory/templates`), delete the rights tab and its section.
- Anything reading `ROLE_GROUPS[...]["name"]` keeps working (`ADMIN` → "Admin", `STAFF` → "Staff").

- [ ] **Step 5: Shell and pouch page**

- `templates/inventory_base.html`: delete the line `{% if role_code != "KARIGAR" %}<a href="{% url 'stock:dashboard' %}">Stock</a> · <a href="{% url 'crm:dashboard' %}">CRM</a> ·{% endif %}` and in its place add, for admins: `{% if is_admin %}<a href="{% url 'accounts:users' %}">Users</a> · {% endif %}{% if caps.inv_move %}<a href="{% url 'parties:customers' %}">Customers</a> · {% endif %}`. Change the brand sub-title "Inventory" to "RM".
- `inventory/templates/inventory/pouch.html`: delete the `✉ Enquire` anchor (`crm:pipeline_new`).
- `inventory/templates/inventory/movements.html`: after the customer `<datalist>`, add `{% if caps.inv_move %}<a class="lnk" href="{% url 'parties:customer_add' %}?next={{ request.get_full_path|urlencode }}">+ New customer</a>{% endif %}` and make the customer input's value fall back to the returned code: `value="{{ form.customer|default:request.GET.customer|default:'' }}"`.
- Verify no foreign URL names remain: `grep -rhoE "\{% url '[a-z_]+:" templates inventory/templates | sort -u` → only `accounts:`, `inventory:`, `parties:`.

- [ ] **Step 6: Wire settings and URLs**

Settings: append `"inventory"` to `INSTALLED_APPS`; `LOGIN_REDIRECT_URL = "inventory:shelf"`; add a context processor `config.context_processors.asset_version` (copy nornament-app `stock/context_processors.asset_version` into `config/context_processors.py`, with the sheet list `("inventory.css",)`), and append it to the context processors.

`config/urls.py`:
```python
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from inventory import views_lookbooks

from .views import healthz

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="inventory:shelf"), name="home"),
    path("lookbook/<str:token>/", views_lookbooks.lookbook_public, name="lookbook_public"),
    path("lookbook/<str:token>/photo/<int:media_id>/", views_lookbooks.lookbook_photo, name="lookbook_photo"),
    path("inventory/", include("inventory.urls")),
    path("parties/", include("parties.urls")),
    path("accounts/", include("accounts.urls")),
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
]

# The Django admin is for superusers only.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser
admin.site.site_header = "Nornament RM administration"
admin.site.site_title = "Nornament RM"
```

- [ ] **Step 7: Fresh migration**

Run: `.venv/bin/python manage.py makemigrations inventory && .venv/bin/python manage.py migrate && .venv/bin/python manage.py check`
Expected: `inventory/migrations/0001_initial.py` with the 16 `inv_*` tables; migrate and check clean. If inventory's original migrations contained data seeding (`grep -ln "RunPython" ~/Desktop/Tech/nornament/nornament-app/inventory/migrations/*.py`), copy each `RunPython` function into a new `inventory/migrations/0002_seed.py` depending on `0001_initial` — open each, keep only seeding (not renames/backfills of old data).

- [ ] **Step 8: Write a boot smoke test**

`inventory/tests/__init__.py`: empty. `inventory/tests/test_boot.py`:
```python
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("name", ["inventory:shelf", "inventory:diamonds", "inventory:search"])
def test_the_main_screens_render_for_admin_and_staff(client, admin_user_, staff_user, name):
    for user in (admin_user_, staff_user):
        client.force_login(user)
        assert client.get(reverse(name)).status_code == 200


def test_home_goes_to_the_shelf(client, staff_user):
    client.force_login(staff_user)
    assert client.get("/")["Location"] == reverse("inventory:shelf")
```

Run: `.venv/bin/python -m pytest inventory/tests/test_boot.py -q` → Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "Move the Stones & Diamonds module across, repointed at RM's own accounts, core and parties"
```

---

### Task 6: Port the inventory test suite

**Files:**
- Create (copied): `inventory/tests/*` from nornament-app (62 files)
- Modify: root `conftest.py` (legacy-role test users), test imports
- Test: the whole suite

**Interfaces:**
- Consumes: everything above.
- Produces: fixtures `accounts_user`, `sales_user`, `production_user`, `karigar_user`, `graphic_user` — test-only users holding exactly nornament-app's role rights, so the ported permission tests check the same rules.

- [ ] **Step 1: Copy the tests and repoint imports**

```bash
SRC=~/Desktop/Tech/nornament/nornament-app
rsync -a --exclude __pycache__ $SRC/inventory/tests/ inventory/tests/
grep -rl -E "from (stock|crm|mediahub)" inventory/tests | xargs sed -i '' \
  -e 's/from stock\.services import/from core.services import/' \
  -e 's/from stock\.masking import/from core.masking import/' \
  -e 's/from stock\.models import Vendor/from parties.models import Vendor/' \
  -e 's/from stock\.models import ActivityLog/from core.models import ActivityLog/' \
  -e 's/from stock\.models import ImportBatch/from core.models import ImportBatch/' \
  -e 's/from crm\.models import Customer/from parties.models import Customer/' \
  -e 's/from mediahub\.models import MediaAsset/from core.models import MediaAsset/' \
  -e 's/from mediahub import storage/from core import storage/'
grep -rnE "from (stock|crm|mediahub)|import (stock|crm|mediahub)" inventory/tests
```
Expected: no output.

- [ ] **Step 2: Add the legacy-role fixtures to the root `conftest.py`**

```python
#: nornament-app's roles, as test-only groups holding exactly the rights they
#: held there. RM has two roles; these let the ported tests keep checking the
#: same permission rules ("a login with view_sale but no view_cost sees …").
LEGACY_ROLES = {
    "T_ACCOUNTS": ("view_cost", "view_sale", "view_vendor", "view_margin",
                   "inv_masters", "inv_purchase", "inv_job", "inv_assort", "inv_move"),
    "T_SALES": ("view_sale",),
    "T_PRODUCTION": ("view_vendor", "inv_job"),
    "T_KARIGAR": ("inv_job",),
    "T_GRAPHIC": (),
}


def _legacy(username, group_name):
    from django.contrib.auth.models import Group, Permission

    group, created = Group.objects.get_or_create(name=group_name)
    if created:
        group.permissions.set(Permission.objects.filter(
            content_type__app_label="accounts", codename__in=LEGACY_ROLES[group_name]))
    user = make_user(username, None)
    user.groups.add(group)
    return user.__class__.objects.get(pk=user.pk)


@pytest.fixture
def accounts_user(db):
    return _legacy("accounts", "T_ACCOUNTS")


@pytest.fixture
def sales_user(db):
    return _legacy("sales", "T_SALES")


@pytest.fixture
def production_user(db):
    return _legacy("production", "T_PRODUCTION")


@pytest.fixture
def karigar_user(db):
    return _legacy("karigar", "T_KARIGAR")


@pytest.fixture
def graphic_user(db):
    return _legacy("graphic", "T_GRAPHIC")
```
Also copy any other root fixture the inventory tests request that is not yet defined (check with `.venv/bin/python -m pytest inventory --co -q 2>&1 | grep "fixture '"`): `locations` is not used by inventory; `request`/`monkeypatch`/`settings`/`client` are pytest's.

- [ ] **Step 3: Run the suite and classify failures**

Run: `.venv/bin/python -m pytest inventory -q -p no:randomly 2>&1 | tail -40`

Fix each failure by the first rule that applies:
1. **Role labels and preview:** an assertion on a role name ("Sales / Showroom", "Accounts", "Karigar desk", "Production") or `?as=SALES` etc. — change to RM's: `?as=STAFF` / "Staff", `?as=ADMIN` / "Admin". A legacy-role user's label is "Staff" (`_role_code` falls back to STAFF).
2. **Rights editor:** a test of `set_right`, `right_toggle`, `dia_right_toggle` or the rights matrix — delete the test (the editor is removed by the spec).
3. **CRM Enquire:** a test expecting `crm:pipeline_new` / "Enquire" on the pouch page — delete the assertion (lookbook Enquire tests stay).
4. **Karigar desk redirect / CRM refusal:** a test about the Karigar desk being kept out of the CRM or landing on the shelf from the stock dashboard — delete it (no CRM, no stock).
5. **Customer model fields:** a test building `Customer(...)` with CRM fields — keep only `customer_code`, `name`, `phone`, `city`.
6. **Vendor model fields:** a test building `Vendor(...)` — fields are identical; if one passes a stock-only field, drop that field.
7. **Media fields:** a test building `MediaAsset(...)` with `piece=`/`style=`/`storage_provider=`/`thumb_url=`… — drop those kwargs; `scope`/`scope_id` stay.
8. **Import batch fields:** `images_done`/`images_total` — drop them.
9. Anything else: stop and report it with the failure text (do not weaken an assertion about cost/vendor/margin masking).

Re-run until green.

- [ ] **Step 4: Run everything**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. Record the count in the commit message.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "Port the inventory test suite: legacy-role test users keep the permission rules checked"
```

---

### Task 7: Admin and Staff, end to end in tests

**Files:**
- Test: `inventory/tests/test_rm_roles.py`

**Interfaces:**
- Consumes: fixtures `shelf`, `diamonds` (from `inventory/tests/conftest.py`), `admin_user_`, `staff_user`; the values `RATE`, `VALUE`, `SUPPLIER`, `DIA_COST`, `DIA_COST_VALUE`, `DIA_SUPPLIER` defined there.

- [ ] **Step 1: Write the tests**

```python
"""RM's two real roles: what Staff sees and may do, against what Admin may."""
import pytest
from django.urls import reverse

from inventory.tests.conftest import DIA_COST, DIA_COST_VALUE, DIA_SUPPLIER, SUPPLIER, VALUE

pytestmark = pytest.mark.django_db

#: screens a showroom login works in
STAFF_SCREENS = ["inventory:shelf", "inventory:diamonds", "inventory:search", "inventory:dia_movements"]


def test_staff_never_sees_cost_or_vendor_on_any_screen(client, staff_user, shelf, diamonds):
    client.force_login(staff_user)
    pages = [client.get(reverse(name)).content.decode() for name in STAFF_SCREENS]
    pages.append(client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode())
    pages.append(client.get(reverse("inventory:dia_line", args=[diamonds["round"].ref])).content.decode())
    for page in pages:
        for secret in ("7,919", VALUE, SUPPLIER, DIA_COST, DIA_COST_VALUE, DIA_SUPPLIER):
            assert secret not in page


def test_admin_sees_cost(client, admin_user_, shelf):
    client.force_login(admin_user_)
    page = client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    assert "7,919" in page


@pytest.mark.parametrize("name", ["inventory:import_home", "inventory:dia_purchase"])
def test_staff_is_refused_imports_and_purchases(client, staff_user, name):
    client.force_login(staff_user)
    assert client.get(reverse(name)).status_code in (302, 403)
```
Before running, confirm each URL name exists: `grep -nE "name=\"(shelf|diamonds|search|dia_movements|pouch|dia_line|import_home|dia_purchase)\"" inventory/urls.py`; adjust the list to the names present (the URL file is the source of truth).

- [ ] **Step 2: Run, fix, commit**

Run: `.venv/bin/python -m pytest inventory/tests/test_rm_roles.py -q` → Expected: pass. A failure that shows a secret on a Staff page is a real masking bug: fix it in the view by routing the value through `core.masking.mask`, never by editing the test.
```bash
git add -A && git commit -m "Tests: Staff never sees cost or vendor; is refused imports and purchases"
```

---

### Task 8: Deployment files and docs

**Files:**
- Create: `deploy/{Dockerfile,entrypoint.sh,docker-compose.yml,backup.sh}`, `docs/DEPLOY.md`, `README.md`

- [ ] **Step 1: Copy and trim from nornament-app**

```bash
SRC=~/Desktop/Tech/nornament/nornament-app
cp $SRC/deploy/backup.sh deploy/
cp $SRC/deploy/Dockerfile deploy/ && cp $SRC/deploy/entrypoint.sh deploy/ && cp $SRC/deploy/docker-compose.yml deploy/
```
Then edit:
- `Dockerfile`: delete the `ADD --checksum=… dinov2-small.onnx` step and its comment, and the `vendor_assets` `RUN` line; keep the rest (Python 3.12-slim, postgresql-client, requirements, user `app`, entrypoint, gunicorn `--workers 3 --timeout 60`).
- `entrypoint.sh`: keep only `set -e`, `python manage.py migrate --noinput`, `python manage.py collectstatic --noinput`, `exec "$@"` (drop the legacy-import block and `s3get`).
- `docker-compose.yml`: keep `db`, `web`, `backup`; delete `worker` and every `LEGACY_*`, `LOGINS_KEY`, `MEDIA_DIRECT_UPLOAD`, `MEDIA_WEBP_*` variable; set the default database name and user to `nornament_rm`; volume `nornament-rm-db`; keep `MEDIA_BUCKET`, `MEDIA_ENDPOINT_URL`, `MEDIA_ACCESS_KEY`, `MEDIA_SECRET_KEY`, add `LOOKBOOK_WHATSAPP`, `LOOKBOOK_EMAIL`; backup prefix: set `BACKUP_PREFIX: rm-db` if `backup.sh` reads a prefix (open it; if it hard-codes a key prefix, change it to `rm-db/`).
- `docs/DEPLOY.md`: Dokploy steps — new Compose app from `Nornament/nornament-rm`, compose path `deploy/docker-compose.yml`, Environment tab variables (list them), Domains tab (`rm.<domain>` → service `web`, port 8000, HTTPS), first deploy, then `python manage.py createsuperuser` in the web container's terminal, then log in and add users under Users.
- `README.md`: what RM is (one paragraph), local setup (`venv`, `createdb nornament_rm`, `.env`, `migrate`, `createsuperuser`, `runserver`), the fake S3 command, `pytest`.

- [ ] **Step 2: Validate**

Run: `docker compose -f deploy/docker-compose.yml config > /dev/null && echo compose-ok`
Expected: `compose-ok` (needs only the docker CLI, not the daemon).

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "Deploy: Dockerfile, entrypoint, compose (web, db, backup) and the Dokploy guide"
```

---

### Task 9: End-to-end run, locally

**Files:** none (verification). Record results in the final report.

- [ ] **Step 1: Start the services**

```bash
cd ~/Desktop/Tech/nornament/nornament-rm
.venv/bin/moto_server -H 127.0.0.1 -p 5005 &   # if not already running for nornament-app
.venv/bin/python -c "import boto3;boto3.client('s3',endpoint_url='http://127.0.0.1:5005',aws_access_key_id='test',aws_secret_access_key='test',region_name='us-east-1').create_bucket(Bucket='nornamentbucket')" || true
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser   # e.g. rm-admin; then set must_change_password=False in the shell
.venv/bin/python manage.py runserver 127.0.0.1:8020
```

- [ ] **Step 2: Walk it as Admin**

In the browser at `http://127.0.0.1:8020/`:
1. Users → add `rm-staff` (Staff) and `rm-admin2` (Admin).
2. Stones → Import: upload `~/Desktop/Tech/nornament/Nornament_Stones_Stock_Chetna_2026-27.xlsx`; review; commit. Expect pouches on the shelf.
3. Diamonds → Import: upload `~/Desktop/Tech/nornament/Dia_Stock_Nitesh.xlsx`; review; commit.
4. Diamonds Settings → Suppliers: add a supplier. Post a stones purchase from it.
5. A pouch → add a photo; confirm the stored key starts `rm/` (`.venv/bin/python manage.py shell -c "from core.models import MediaAsset;print(MediaAsset.objects.filter(scope='pouch').values_list('storage_key',flat=True)[:3])"`).
6. Build a lookbook with two pouches; open its private link in a private window.

- [ ] **Step 3: Walk it as Staff**

Log in as `rm-staff`: record a sale on a pouch, using "+ New customer" to add one and coming back to the form with the code filled; confirm no cost, valuation, supplier or margin figure appears on the shelf, pouch, diamond line and search; confirm Users, Import and Purchase are refused or hidden.

- [ ] **Step 4: Report** what passed, with any defect fixed under its own commit (test first).

---

### Task 10: Publish the repo

- [ ] **Step 1: Ask the owner in chat** to confirm creating the private GitHub repo `Nornament/nornament-rm`. Do not proceed without a yes.
- [ ] **Step 2: Create and push**

```bash
gh repo create Nornament/nornament-rm --private --source . --remote origin --push
```

---

# Part B — remove RM from nornament-app

Work on a branch in nornament-app: `git checkout -b feat/rm-standalone-removal`.

### Task 11: Remove the module's code, links, rights and the Karigar desk role

**Files:**
- Delete: `inventory/` (whole app), `templates/inventory_base.html`, `static/css/inventory.css`
- Modify: `config/settings.py` (`INSTALLED_APPS`, `MIDDLEWARE`), `config/urls.py`, `stock/templates/stock/_nav.html`, `templates/crm_base.html`, `stock/context_processors.py`, `accounts/capabilities.py`, `accounts/models.py` (`Capability.permissions`), `accounts/middleware.py`, `stock/views.py` (dashboard redirect, `CAPABILITY_MATRIX` row), tests that reference removed names
- Test: `stock/tests/test_rm_removed.py`

**Interfaces:**
- Produces: nornament-app with no `inventory` app; `accounts.capabilities.ALL` without the five `inv_*`; `ROLE_TABS`/`ROLE_GROUPS` without `KARIGAR`.

- [ ] **Step 1: Write the failing test**

`stock/tests/test_rm_removed.py`:
```python
"""Stones & Diamonds moved to its own app (nornament-rm); nothing of it stays here."""
import pytest
from django.apps import apps
from django.urls import NoReverseMatch, reverse

from accounts import capabilities

pytestmark = pytest.mark.django_db


def test_the_inventory_app_and_its_urls_are_gone():
    assert not apps.is_installed("inventory")
    with pytest.raises(NoReverseMatch):
        reverse("inventory:shelf")
    with pytest.raises(NoReverseMatch):
        reverse("lookbook_public", args=["x"])


def test_no_inventory_rights_and_no_karigar_role():
    assert not any(cap.split(".")[1].startswith("inv_") for cap in capabilities.ALL)
    assert "KARIGAR" not in capabilities.ROLE_GROUPS and "KARIGAR" not in capabilities.ROLE_TABS


def test_no_stones_link_in_either_shell(client, admin_user_):
    client.force_login(admin_user_)
    assert b"Stones" not in client.get(reverse("stock:dashboard")).content
    assert b"Stones" not in client.get(reverse("crm:dashboard")).content
```
Run: `.venv/bin/python -m pytest stock/tests/test_rm_removed.py -q` → FAIL.

- [ ] **Step 2: Remove**

```bash
git rm -r -q inventory templates/inventory_base.html static/css/inventory.css
```
Then edit:
- `config/settings.py`: remove `"inventory"` from `INSTALLED_APPS`; remove `"accounts.middleware.KarigarDeskMiddleware"` from `MIDDLEWARE`.
- `config/urls.py`: remove `from inventory import views_lookbooks`, the two `lookbook/...` paths and `path("inventory/", include("inventory.urls"))`.
- `stock/templates/stock/_nav.html`: delete the line `<a href="{% url 'inventory:shelf' %}"><span class="ico">◆</span>Stones</a>`.
- `templates/crm_base.html`: delete `<a class="ni" href="{% url 'inventory:shelf' %}"><span class="ni-i">◆</span><span>Stones</span></a>`.
- `stock/context_processors.py`: sheet list becomes `("app.css", "crm.css")`.
- `accounts/capabilities.py`: delete `INV_MASTERS`, `INV_PURCHASE`, `INV_JOB`, `INV_ASSORT`, `INV_MOVE` and their comments; remove them from `ALL` and every role's `caps`; delete the `"KARIGAR"` entries from `ROLE_TABS` and `ROLE_GROUPS`.
- `accounts/models.py`: remove the five `inv_*` tuples from `Capability.Meta.permissions`.
- `accounts/middleware.py`: delete `KarigarDeskMiddleware` (and its `PermissionDenied` import if unused).
- `stock/views.py`: in `dashboard`, delete the two lines `if _role_code(request.user) == "KARIGAR": return redirect("inventory:shelf")`; in `CAPABILITY_MATRIX`, delete the `("inv_masters", ...)` row and any other `inv_*` row.
- Find any other reference: `grep -rnE "inventory:|INV_(MASTERS|PURCHASE|JOB|ASSORT|MOVE)|KARIGAR|karigar_user|KarigarDesk" --include='*.py' --include='*.html' . | grep -v "^./\.venv\|/migrations/\|^./legacy/\|^./docs/"` — fix each (tests that exercised the Karigar desk or inventory rights are deleted; `conftest.py`'s `karigar_user` fixture is deleted).
- `accounts/migrations`: leave the historical migrations as they are.

- [ ] **Step 3: Run**

Run: `set -a; source .env; set +a; .venv/bin/python manage.py makemigrations --check --dry-run; .venv/bin/python -m pytest stock/tests/test_rm_removed.py accounts stock/tests/test_masking.py -q`
Expected: `makemigrations --check` reports the `accounts` Capability permission change (that migration is written in Task 12); the tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "Remove Stones & Diamonds from nornament-app: the app, its links, rights and the Karigar desk role"
```

### Task 12: Migrations — drop the tables, rights and the Karigar desk

**Files:**
- Create: `accounts/migrations/0006_remove_rm.py`
- Test: `accounts/tests/test_rm_removal_migration.py`

**Interfaces:**
- Consumes: Task 11.

- [ ] **Step 1: Write the migration**

```python
"""Stones & Diamonds moved to nornament-rm (2026-10-09). Remove what it left here.

In order: its 16 tables first (they reference the import batches, so those
cannot go while the tables stand); then its import batches and photo rows
(bucket files are left — harmless and recoverable); the five inv_* rights;
Karigar desk logins (deactivated — the role was only for stones) and the
group; and what Django kept about the app: its migration rows and content types.
"""
from django.db import migrations

INV_TABLES = [
    "inv_lookbook_stone", "inv_lookbook", "inv_stock_take_count", "inv_stock_take",
    "inv_dia_line_cost", "inv_dia_rate", "inv_dia_line", "inv_dia_code", "inv_dia_term",
    "inv_price", "inv_movement", "inv_document", "inv_pouch", "inv_batch",
    "inv_code_part", "inv_box_colour",
]
RIGHTS = ["inv_masters", "inv_purchase", "inv_job", "inv_assort", "inv_move"]


def forwards(apps, schema_editor):
    MediaAsset = apps.get_model("mediahub", "MediaAsset")
    ImportBatch = apps.get_model("stock", "ImportBatch")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("accounts", "User")

    # inv_* rows point at these, so the tables go first
    with schema_editor.connection.cursor() as cursor:
        for table in INV_TABLES:
            cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
        cursor.execute("DELETE FROM django_migrations WHERE app = 'inventory'")
    batches = ImportBatch.objects.filter(source__in=["STONES", "DIAMONDS"])
    workbooks = list(batches.values_list("media_id", flat=True))
    batches.delete()
    MediaAsset.objects.filter(pk__in=workbooks).delete()
    MediaAsset.objects.filter(scope="pouch").delete()

    Permission.objects.filter(content_type__app_label="accounts", codename__in=RIGHTS).delete()
    karigar = Group.objects.filter(name="KARIGAR").first()
    if karigar:
        for user in User.objects.filter(groups=karigar):
            if user.groups.count() == 1:
                user.is_active = False
                user.save(update_fields=["is_active"])
        karigar.delete()

    ContentType = apps.get_model("contenttypes", "ContentType")
    stale = ContentType.objects.filter(app_label="inventory")
    Permission.objects.filter(content_type__in=stale).delete()
    stale.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_inv_move"),
        ("mediahub", "0008_piece_photos_onto_their_piece"),
        ("stock", "0011_restore_reference"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="capability",
            options={"default_permissions": (), "managed": False, "permissions": [
                ("view_sale", "Can see sale prices"), ("view_cost", "Can see cost prices"),
                ("view_vendor", "Can see vendors"), ("manage_materials", "Can see the material breakup"),
                ("view_margin", "Can see margins"), ("adjust_stock", "Can adjust stock"),
                ("melt", "Can melt a piece"), ("edit_bom", "Can edit a bill of materials"),
            ]},
        ),
    ]
```
Run `.venv/bin/python manage.py makemigrations --check --dry-run` — Expected: "No changes detected" (the `AlterModelOptions` must match `Capability.Meta` exactly; if it does not, copy the permissions list from `accounts/models.py`). Confirm the latest `mediahub` and `stock` migration names with `ls mediahub/migrations stock/migrations | tail` and update the dependencies if they differ.

- [ ] **Step 2: Write the test**

`accounts/tests/test_rm_removal_migration.py`:
```python
"""The removal migration, run against the state just before it."""
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("accounts", "0005_inv_move")]
AFTER = [("accounts", "0006_remove_rm")]


def test_karigar_only_logins_are_deactivated_and_the_rights_are_gone():
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    old = executor.loader.project_state(BEFORE).apps
    Group, User = old.get_model("auth", "Group"), old.get_model("accounts", "User")
    karigar, _ = Group.objects.get_or_create(name="KARIGAR")
    sales, _ = Group.objects.get_or_create(name="SALES")
    desk = User.objects.create(username="desk", is_active=True)
    desk.groups.add(karigar)
    both = User.objects.create(username="both", is_active=True)
    both.groups.add(karigar, sales)

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(AFTER)
    new = executor.loader.project_state(AFTER).apps
    User, Group, Permission = new.get_model("accounts", "User"), new.get_model("auth", "Group"), new.get_model("auth", "Permission")
    assert User.objects.get(username="desk").is_active is False
    assert User.objects.get(username="both").is_active is True
    assert not Group.objects.filter(name="KARIGAR").exists()
    assert not Permission.objects.filter(codename__startswith="inv_").exists()
    with connection.cursor() as cursor:
        cursor.execute("select count(*) from information_schema.tables where table_name like 'inv\\_%'")
        assert cursor.fetchone()[0] == 0
```

- [ ] **Step 3: Run**

Run: `.venv/bin/python -m pytest accounts/tests/test_rm_removal_migration.py -q` then the full suite against the fake S3:
```bash
export MEDIA_ENDPOINT_URL=http://127.0.0.1:5005 MEDIA_ACCESS_KEY=test MEDIA_SECRET_KEY=test MEDIA_REGION=us-east-1
.venv/bin/python -m pytest -p no:warnings -q
```
Expected: all pass. Then migrate the local database: `.venv/bin/python manage.py migrate` and confirm `qa_karigar` is inactive.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "Migrate: drop the inv_* tables, the inventory rights and the Karigar desk role"
```

### Task 13: Ship

- [ ] **Step 1:** Report to the owner: RM's test count and end-to-end results, nornament-app's suite result, and the Dokploy steps in `nornament-rm/docs/DEPLOY.md`.
- [ ] **Step 2:** On the owner's go-ahead, merge `feat/rm-standalone-removal` into nornament-app `main` and push — only once RM is deployed or deploying, since this push removes Stones from nornament-app.
