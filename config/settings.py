"""Django settings for the Wood League Chess application.

Title: settings.py — Django configuration for Wood League Chess
Description:
    Configures database, installed apps, middleware, templates, static files,
    authentication, and third-party service keys (Anthropic, Chess.com).
    Implements production Django security best practices and Railway deployment support.

Changelog:
    2026-05-06: Added production security hardening, ALLOWED_HOSTS configuration
                for Railway health checks, logging, and database connection pooling
"""
import logging
import os
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

# Determine environment
IS_PRODUCTION = os.environ.get("RAILWAY_ENVIRONMENT_NAME") == "production"
IS_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT_NAME") is not None

# Security settings - defaults prioritize production safety
SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-dev-key-change-in-production"
)
if IS_PRODUCTION and SECRET_KEY == "django-insecure-dev-key-change-in-production":
    import warnings
    warnings.warn(
        "WARNING: Using insecure default SECRET_KEY in production. "
        "Set the SECRET_KEY environment variable.",
        RuntimeWarning,
    )

DEBUG = config("DEBUG", default=not IS_PRODUCTION, cast=bool)

# ALLOWED_HOSTS - Handle Railway health checks and multiple environments
_allowed_hosts = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())
ALLOWED_HOSTS = list(_allowed_hosts)

# Add Railway health check host
if IS_RAILWAY and "healthcheck.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("healthcheck.railway.app")

# Add localhost for development
if not IS_PRODUCTION:
    for host in ["localhost", "127.0.0.1"]:
        if host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(host)

AUTH_USER_MODEL = "accounts.User"

# Production security settings
# Reference: https://docs.djangoproject.com/en/stable/topics/security/
if IS_PRODUCTION:
    # HTTPS and security headers
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_SECURITY_POLICY = {
        "default-src": ("'self'",),
    }
    X_FRAME_OPTIONS = "DENY"
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # CSRF protection - Railway proxy settings
    CSRF_TRUSTED_ORIGINS = config(
        "CSRF_TRUSTED_ORIGINS",
        default="",
        cast=Csv,
    )

# Session settings
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_tailwind_cli",
    "django_htmx",
    "accounts",
    "players",
    "games",
    "analysis",
    "openings",
    "dashboard",
    "search",
    "ingest",
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
    "django_htmx.middleware.HtmxMiddleware",
    "accounts.middleware.LoginRequiredMiddleware",
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

_database_url = config("DATABASE_URL", default="")
if _database_url:
    try:
        import dj_database_url
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_URL is set, but dj-database-url is not installed."
        ) from exc
    DATABASES = {"default": dj_database_url.parse(_database_url, conn_max_age=600)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_NAME", default="wood_league"),
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
        }
    }

# Database connection pooling for production
if IS_PRODUCTION:
    # Configure connection pooling for better performance
    DATABASES["default"]["CONN_MAX_AGE"] = 600
    DATABASES["default"]["OPTIONS"] = {
        "connect_timeout": 10,
        "options": "-c default_transaction_isolation=read_committed",
    }

AUTHENTICATION_BACKENDS = [
    "accounts.backends.LegacyPbkdf2Backend",
    "django.contrib.auth.backends.ModelBackend",
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "accounts.backends.LegacyPbkdf2Hasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/auth/login/"

AUTH_ENABLED = config("AUTH_ENABLED", default=True, cast=bool)

TAILWIND_CLI_SRC_CSS = "static/css/main.css"
TAILWIND_CLI_OUTPUT_CSS = "css/tailwind.css"
TAILWIND_CLI_AUTOMATIC_DOWNLOAD = True

# Logging configuration - Production-grade logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "standard": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "filters": {
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "file": {
            "level": "ERROR",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "django.log",
            "maxBytes": 1024 * 1024 * 10,  # 10MB
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
}

# Ensure logs directory exists
_logs_dir = BASE_DIR / "logs"
_logs_dir.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default="")
ANTHROPIC_MODEL = config("ANTHROPIC_MODEL", default="claude-haiku-4-5-20251001")

CHESS_COM_USERNAMES = config("CHESS_COM_USERNAMES", default="")
CHESS_COM_USER_AGENT = config(
    "CHESS_COM_USER_AGENT", default="wood-league-chess/2.0 (+club analytics)"
)
INGEST_MONTH_LIMIT = config("INGEST_MONTH_LIMIT", default=24, cast=int)
DEFAULT_HISTORY_DAYS = config("DEFAULT_HISTORY_DAYS", default=90, cast=int)

# Engine analysis settings
ANALYSIS_DEPTH = config("ANALYSIS_DEPTH", default=20, cast=int)
LC0_NODES = config("LC0_NODES", default=25000, cast=int)
