"""
Django settings for Uncle Kop's Workshop
"""
import os
from pathlib import Path
from urllib.parse import urlsplit
from django.core.exceptions import ImproperlyConfigured

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in normal dev/prod envs
    def load_dotenv(*args, **kwargs):
        return False

import pymysql

pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(BASE_DIR / '.env')


# Load local development settings consistently across terminals without committing secrets.
ENV_FILE = BASE_DIR / '.env'
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))

DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() in ('1', 'true', 'yes', 'on')

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-local-development-only'
    else:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is disabled.')

if DEBUG:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '192.168.14.182']
else:
    ALLOWED_HOSTS = [
        host.strip()
        for host in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')
        if host.strip()
    ]
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured('DJANGO_ALLOWED_HOSTS must list the production hostnames.')

PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
if not DEBUG and not PUBLIC_BASE_URL:
    raise ImproperlyConfigured('PUBLIC_BASE_URL must be set to the public application origin in production.')
if PUBLIC_BASE_URL:
    parsed_public_url = urlsplit(PUBLIC_BASE_URL)
    if (
        parsed_public_url.scheme not in {'http', 'https'}
        or not parsed_public_url.netloc
        or parsed_public_url.username
        or parsed_public_url.password
        or parsed_public_url.query
        or parsed_public_url.fragment
    ):
        raise ImproperlyConfigured('PUBLIC_BASE_URL must be an absolute HTTP(S) URL without credentials, query, or fragment.')
    if not DEBUG and parsed_public_url.scheme != 'https':
        raise ImproperlyConfigured('PUBLIC_BASE_URL must use HTTPS when DJANGO_DEBUG is disabled.')

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

# Encryption key for AES-256-GCM (set from env in production). Base64-encoded 32 bytes.
import base64
import binascii
import secrets

# ENCRYPTION_KEY should be a base64-encoded 32-byte key (AES-256). In production
# set the `ENCRYPTION_KEY` environment variable. For local development when
# `DEBUG=True`, persist a generated key to `.dev_encryption_key` so encrypted
# data remains readable across server restarts.
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    if DEBUG:
        key_file = BASE_DIR / '.dev_encryption_key'
        try:
            if key_file.exists():
                ENCRYPTION_KEY = key_file.read_text().strip()
            else:
                k = base64.b64encode(secrets.token_bytes(32)).decode('utf-8')
                key_file.write_text(k)
                ENCRYPTION_KEY = k
        except Exception:
            # Fallback to empty string if filesystem not writable; models will raise clearly.
            ENCRYPTION_KEY = ''
    else:
        raise ImproperlyConfigured('ENCRYPTION_KEY must be set when DJANGO_DEBUG is disabled.')

try:
    decoded_encryption_key = base64.b64decode(ENCRYPTION_KEY, validate=True)
except (binascii.Error, ValueError) as exc:
    raise ImproperlyConfigured('ENCRYPTION_KEY must be valid base64.') from exc
if len(decoded_encryption_key) != 32:
    raise ImproperlyConfigured('ENCRYPTION_KEY must decode to exactly 32 bytes.')

# Use Argon2id for password hashing when available
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'workshop',  # ← Our app
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'workshop.middleware.CsrfTokenCacheControlMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'workshop.middleware.CustomerProfileCompletionMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'uncle_kops_workshop.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'uncle_kops_workshop.wsgi.application'

try:
    DB_CONN_MAX_AGE = int(os.environ.get('DB_CONN_MAX_AGE', '0' if DEBUG else '60'))
except ValueError as exc:
    raise ImproperlyConfigured('DB_CONN_MAX_AGE must be a non-negative integer.') from exc
if DB_CONN_MAX_AGE < 0:
    raise ImproperlyConfigured('DB_CONN_MAX_AGE must be a non-negative integer.')

if DEBUG:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('DB_NAME', 'uncle_kops_db'),
            'USER': os.environ.get('DB_USER', 'django_user'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', '10.30.6.173'),
            'PORT': os.environ.get('DB_PORT', '3306'),
            'CONN_MAX_AGE': DB_CONN_MAX_AGE,
            'CONN_HEALTH_CHECKS': True,
        }
    }
else:
    database_variables = ('DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST')
    missing_database_variables = [name for name in database_variables if not os.environ.get(name)]
    if missing_database_variables:
        raise ImproperlyConfigured(
            'Set the production database variables: ' + ', '.join(missing_database_variables)
        )
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ['DB_NAME'],
            'USER': os.environ['DB_USER'],
            'PASSWORD': os.environ['DB_PASSWORD'],
            'HOST': os.environ['DB_HOST'],
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': {'charset': 'utf8mb4'},
            'CONN_MAX_AGE': DB_CONN_MAX_AGE,
            'CONN_HEALTH_CHECKS': True,
        }
    }
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Africa/Johannesburg'
USE_I18N      = True
USE_TZ        = True

STATIC_URL      = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT     = BASE_DIR / 'staticfiles'

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL          = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# Email settings
# Use real SMTP values only when they are actually configured. If no valid credentials are present,
# Django will fall back to the console backend so emails are still visible in development without
# causing false "email could not be sent" warnings.
# Example Gmail values:
#   EMAIL_HOST=smtp.gmail.com
#   EMAIL_PORT=587
#   EMAIL_USE_TLS=True
#   EMAIL_HOST_USER=your-email@gmail.com
#   EMAIL_HOST_PASSWORD=your-app-password
#   DEFAULT_FROM_EMAIL=your-email@gmail.com
# Example Outlook values:
#   EMAIL_HOST=smtp.office365.com
#   EMAIL_PORT=587
#   EMAIL_USE_TLS=True
#   EMAIL_HOST_USER=your-email@outlook.com
#   EMAIL_HOST_PASSWORD=your-password-or-app-password
#   DEFAULT_FROM_EMAIL=your-email@outlook.com
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'noreply@localhost')

EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('1', 'true', 'yes', 'on')
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False').lower() in ('1', 'true', 'yes', 'on')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '20'))
SERVER_EMAIL = os.environ.get('SERVER_EMAIL', DEFAULT_FROM_EMAIL)

if os.environ.get('EMAIL_BACKEND'):
    EMAIL_BACKEND = os.environ['EMAIL_BACKEND']
elif EMAIL_HOST_USER and EMAIL_HOST_PASSWORD and not EMAIL_HOST_USER.startswith('your-'):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

DJANGO_LOG_LEVEL = os.environ.get('DJANGO_LOG_LEVEL', 'WARNING' if DEBUG else 'INFO').upper()
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {'format': '%(asctime)s %(levelname)s %(name)s %(message)s'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        'django': {'handlers': ['console'], 'level': DJANGO_LOG_LEVEL, 'propagate': False},
        'workshop': {'handlers': ['console'], 'level': DJANGO_LOG_LEVEL, 'propagate': False},
    },
}

# Security recommendations to enable in production
# SECURE_SSL_REDIRECT = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True
# SECURE_HSTS_SECONDS = 31536000
