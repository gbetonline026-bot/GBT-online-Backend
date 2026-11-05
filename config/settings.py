import os
from pathlib import Path
from urllib.parse import urlparse

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
TRUTHY = {"1", "true", "yes", "on"}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(BASE_DIR / ".env")


def env(*names, default=""):
    """First non-empty value among several variable names (e.g. DJANGO_SECRET_KEY or SECRET_KEY)."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def env_list(*names, default=""):
    return [item.strip() for item in env(*names, default=default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "SECRET_KEY", default="dev-only-change-me")
DEBUG = env("DJANGO_DEBUG", "DEBUG", default="True").lower() in TRUTHY
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "ALLOWED_HOSTS", default="127.0.0.1,localhost")
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

if not DEBUG and (SECRET_KEY.startswith("dev-only") or len(SECRET_KEY) < 40):
    raise ImproperlyConfigured("Set a long, random DJANGO_SECRET_KEY (or SECRET_KEY) when DEBUG is False.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "leads.apps.LeadsConfig",
    "accounts.apps.AccountsConfig",
    "academics.apps.AcademicsConfig",
    "finance.apps.FinanceConfig",
    "cms.apps.CmsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Local development uses SQLite. In production set DATABASE_URL to the Neon PostgreSQL connection string,
# e.g. postgresql://user:password@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
DATABASE_URL = env("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL, conn_max_age=int(env("DB_CONN_MAX_AGE", default="60")), conn_health_checks=True
        )
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
if DATABASE_URL.startswith(("postgres://", "postgresql://")):
    DATABASES["default"].setdefault("OPTIONS", {}).setdefault("sslmode", "require")
    if "-pooler." in (urlparse(DATABASE_URL).hostname or ""):
        # Neon's pooled endpoint uses PgBouncer in transaction mode.
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
elif not DEBUG:
    raise ImproperlyConfigured("Set DATABASE_URL to the Neon PostgreSQL connection string when DEBUG is False.")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.PortalTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAdminUser",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "enquiry": "30/min",
        "portal_auth": os.environ.get("PORTAL_AUTH_RATE", "10/min"),
    },
}

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")
PORTAL_TOKEN_TTL_HOURS = int(os.environ.get("PORTAL_TOKEN_TTL_HOURS", "12"))
PASSWORD_RESET_TIMEOUT = int(os.environ.get("PASSWORD_RESET_TIMEOUT_SECONDS", str(60 * 60 * 24)))

# Lesson videos and study materials are private: they are never served from MEDIA_URL,
# only through signed, time-limited links checked against the student's enrolment.
MEDIA_ROOT = Path(os.environ.get("PRIVATE_MEDIA_ROOT", BASE_DIR / "private_media"))
MEDIA_URL = "/private-media/"

# Uploads go to Cloudinary when CLOUDINARY_URL (cloudinary://API_KEY:API_SECRET@CLOUD_NAME) is set,
# otherwise to MEDIA_ROOT on disk (development only – Render's disk is wiped on every deploy).
CLOUDINARY_URL = env("CLOUDINARY_URL")
CLOUDINARY_FOLDER = env("CLOUDINARY_FOLDER", default="gbet-online")
if not CLOUDINARY_URL and not DEBUG:
    raise ImproperlyConfigured("Set CLOUDINARY_URL for file uploads when DEBUG is False.")
STORAGES = {
    "default": {
        "BACKEND": "academics.cloud_storage.CloudinaryPrivateStorage"
        if CLOUDINARY_URL
        else "django.core.files.storage.FileSystemStorage"
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
PUBLIC_API_URL = os.environ.get("PUBLIC_API_URL", "http://127.0.0.1:8000").rstrip("/")
LMS_MEDIA_LINK_TTL_SECONDS = int(os.environ.get("LMS_MEDIA_LINK_TTL_SECONDS", str(60 * 60 * 3)))
LMS_MAX_VIDEO_MB = int(os.environ.get("LMS_MAX_VIDEO_MB", "1024"))
LMS_MAX_MATERIAL_MB = int(os.environ.get("LMS_MAX_MATERIAL_MB", "25"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Online fee payments (Razorpay). Leave the keys empty to keep online payment switched off.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
RECEIPT_PREFIX = os.environ.get("RECEIPT_PREFIX", "GBET-R-")
RECEIPT_ORG_NAME = os.environ.get("RECEIPT_ORG_NAME", "Gautam Buddha Educational Trust – GBET Online")
RECEIPT_ORG_ADDRESS = os.environ.get("RECEIPT_ORG_ADDRESS", "C-77, Sector 63A, Noida, Uttar Pradesh")
RECEIPT_CONTACT = os.environ.get("RECEIPT_CONTACT", "Queries: +91 9355470710 · admission@gbedutrust.com")

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() in {"1", "true", "yes"}
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "GBET Online <admission@gbedutrust.com>")

if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS = sorted(set(env_list("CORS_ALLOWED_ORIGINS")) | {FRONTEND_URL})
    CSRF_TRUSTED_ORIGINS = sorted(
        set(env_list("CSRF_TRUSTED_ORIGINS"))
        | {PUBLIC_API_URL}
        | ({f"https://{RENDER_EXTERNAL_HOSTNAME}"} if RENDER_EXTERNAL_HOSTNAME else set())
    )
    # Render terminates HTTPS at its proxy.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", default="True").lower() in TRUTHY
    SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", default=str(60 * 60 * 24 * 30)))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {"django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}
