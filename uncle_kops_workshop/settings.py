"""
Django settings for Uncle Kop's Workshop
"""
from pathlib import Path
import pymysql

pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent.parent
import os

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-CHANGE-THIS-IN-PRODUCTION-uncle-kops-2024')

DEBUG = True  # Set to False in production

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '192.168.14.85']

# Encryption key for AES-256-GCM (set from env in production). Base64-encoded 32 bytes.
# Keep this valid and URL-safe compatible; a Fernet key also works as a raw 32-byte AES key.
ENCRYPTION_KEY = os.environ.get(
    'ENCRYPTION_KEY',
    'tr4zq2/5QiLU3TEFoum7fXl7MmqhfluFxbLxRgoQZ2M='
)

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
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
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

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'uncle_kops_db',
        'USER': 'django_user',
        'PASSWORD': 'UncleKops2024!',
        'HOST': '192.168.14.85',
        'PORT': '3306',
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
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '30'))
SERVER_EMAIL = os.environ.get('SERVER_EMAIL', DEFAULT_FROM_EMAIL)

if os.environ.get('EMAIL_BACKEND'):
    EMAIL_BACKEND = os.environ['EMAIL_BACKEND']
elif EMAIL_HOST_USER and EMAIL_HOST_PASSWORD and not EMAIL_HOST_USER.startswith('your-'):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Security recommendations to enable in production
# SECURE_SSL_REDIRECT = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True
# SECURE_HSTS_SECONDS = 31536000
