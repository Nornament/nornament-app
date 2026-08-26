"""Django settings for the Nornament application.

Everything that differs between a laptop, staging and the VPS is read from the
environment. Nothing here reaches for a secret at import time except through
``env()``, so ``manage.py check`` runs on a bare checkout.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


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
# The public hostname(s), plus loopback — the container healthcheck reaches
# gunicorn directly on 127.0.0.1 and Django would otherwise reject it as a
# DisallowedHost, leaving the container permanently unhealthy and unrouted.
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
    "accounts",
    "stock",
    "crm",
    "mediahub",
    "etl",
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
    "accounts.middleware.MustChangePasswordMiddleware",
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
                "accounts.context_processors.capabilities",
                "crm.context_processors.nav_counts",
                "stock.context_processors.ticker",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "nornament"),
        "USER": env("POSTGRES_USER", "nornament"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(env("POSTGRES_CONN_MAX_AGE", "60")),
    }
}

# The Supabase dump is restored into its own database on the same cluster and
# read through this alias by ``load_legacy``/``golden_export``. It is absent on
# a normal deployment; the ETL commands say so rather than exploding.
if env("LEGACY_DB_NAME"):
    DATABASES["legacy"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("LEGACY_DB_NAME"),
        "USER": env("LEGACY_DB_USER", DATABASES["default"]["USER"]),
        "PASSWORD": env("LEGACY_DB_PASSWORD", DATABASES["default"]["PASSWORD"]),
        "HOST": env("LEGACY_DB_HOST", DATABASES["default"]["HOST"]),
        "PORT": env("LEGACY_DB_PORT", DATABASES["default"]["PORT"]),
        "TEST": {"MIRROR": None},
    }

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
AUTH_USER_MODEL = "accounts.User"

# The modern default hashes first, so every password Django writes from now on
# is PBKDF2. BCryptPasswordHasher stays *after* it to read the GoTrue
# ``$2a$10$`` hashes imported from Supabase — Django upgrades each one to the
# default on that user's first successful login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.BCryptPasswordHasher",
]

AUTHENTICATION_BACKENDS = ["accounts.backends.UsernameOrEmailBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "accounts.validators.BcryptLengthValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "stock:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

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

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", not DEBUG)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
# Traefik terminates TLS and forwards X-Forwarded-Proto; this makes the app
# insist on it rather than trusting that nothing ever reaches it over http.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", not DEBUG)
# ...except the health endpoint, which is hit over plain HTTP from inside the
# container. Redirecting it to https makes every healthcheck fail.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
if not DEBUG:
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", True)

# ── media (Contabo S3, keys unchanged from R2) ───────────────────────────
MEDIA_BUCKET = env("MEDIA_BUCKET", "nornamentbucket")
MEDIA_ENDPOINT_URL = env("MEDIA_ENDPOINT_URL", "")
MEDIA_REGION = env("MEDIA_REGION", "auto")
MEDIA_ACCESS_KEY = env("MEDIA_ACCESS_KEY", "")
MEDIA_SECRET_KEY = env("MEDIA_SECRET_KEY", "")
MEDIA_ADDRESSING_STYLE = env("MEDIA_ADDRESSING_STYLE", "path")
MEDIA_PRESIGN_TTL = int(env("MEDIA_PRESIGN_TTL", "900"))
# Phase 0 smoke test decides this: if a browser PUT to Contabo fails CORS the
# upload proxies through Django instead. One flag, no redesign.
MEDIA_DIRECT_UPLOAD = env_bool("MEDIA_DIRECT_UPLOAD", True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}
