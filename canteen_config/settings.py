"""Django settings for the canteen management project."""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

def _env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


# Keep the development fallback so the project starts after unzip, but use an
# environment variable for every deployed instance.
SECRET_KEY = os.environ.get(
    'CANTEEN_SECRET_KEY',
    'django-insecure-r%b%ujb3_3i)_e_@k=v0hz-p2a^#js3#x4*bv_=kpm)vusq4c-'
)

# SECURITY WARNING: don't run with debug turned on in production!
# Set to True for development, False for production
DEBUG = _env_bool('CANTEEN_DEBUG', True)

# Allow all hosts during development
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('CANTEEN_ALLOWED_HOSTS', '*').split(',')
    if host.strip()
]

# Application definition
INSTALLED_APPS = [
    'jazzmin',              # Must be BEFORE django.contrib.admin
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',   # For professional number formatting
    'django_htmx',          # django-htmx for dynamic POS interactions
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',   # Adds request.htmx
]

ROOT_URLCONF = 'canteen_config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],  # Django will look in each app's templates/ folder
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'canteen_config.wsgi.application'

# Database
# Normal application use remains MySQL. Set CANTEEN_USE_SQLITE=1 for local
# smoke tests/system checks that do not need the production database server.

if os.environ.get('CANTEEN_USE_SQLITE', '0') == '1':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('CANTEEN_DB_NAME', 'canteen_connection'),
            'USER': os.environ.get('CANTEEN_DB_USER', 'root'),
            'PASSWORD': os.environ.get('CANTEEN_DB_PASSWORD', 'misbahhooria'),
            'HOST': os.environ.get('CANTEEN_DB_HOST', 'localhost'),
            'PORT': os.environ.get('CANTEEN_DB_PORT', '3306'),
            'OPTIONS': {
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Karachi'  # Changed to Pakistan timezone

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (User uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Session settings
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 86400  # 24 hours
SESSION_SAVE_EVERY_REQUEST = False
SESSION_COOKIE_SECURE = _env_bool('CANTEEN_SECURE_COOKIES', False)

# CSRF settings
CSRF_COOKIE_SECURE = _env_bool('CANTEEN_SECURE_COOKIES', False)
CSRF_TRUSTED_ORIGINS = []  # Add your domain in production

# Optional HTTPS hardening. These stay disabled for local HTTP development and
# can be enabled explicitly in production after HTTPS is configured correctly.
SECURE_SSL_REDIRECT = _env_bool('CANTEEN_SECURE_SSL_REDIRECT', False)
SECURE_HSTS_SECONDS = int(os.environ.get('CANTEEN_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool('CANTEEN_HSTS_INCLUDE_SUBDOMAINS', False)
SECURE_HSTS_PRELOAD = _env_bool('CANTEEN_HSTS_PRELOAD', False)

# Custom Error Pages (MUST be at the bottom of the file)
# Handlers moved to urls.py where Django expects them.

# ── JAZZMIN SETTINGS (Admin Panel Theme) ─────────────────────────────────────
JAZZMIN_SETTINGS = {
    # Window title & branding
    'site_title': 'CanteenMS Admin',
    'site_header': 'CanteenMS',
    'site_brand': '🍽 CanteenMS',
    'welcome_sign': 'Welcome to CanteenMS Back Office',
    'copyright': 'CanteenMS © 2026',

    # Icons — uses Font Awesome 5 class names
    'icons': {
        'auth': 'fas fa-users-cog',
        'auth.user': 'fas fa-user',
        'auth.Group': 'fas fa-users',
        'core.dish': 'fas fa-utensils',
        'core.dishcategory': 'fas fa-tags',
        'core.salestransaction': 'fas fa-receipt',
        'core.saleitem': 'fas fa-shopping-cart',
        'core.expense': 'fas fa-money-bill-wave',
        'core.expensecategory': 'fas fa-folder-open',
        'core.rawmaterial': 'fas fa-boxes',
        'core.rawmaterialcategory': 'fas fa-layer-group',
        'core.stockadjustment': 'fas fa-sliders-h',
        'core.auditlog': 'fas fa-shield-alt',
        'core.user': 'fas fa-id-badge',
        'core.mealsession': 'fas fa-clock',
        'core.dailyreport': 'fas fa-chart-bar',
    },
    'default_icon_parents': 'fas fa-folder',
    'default_icon_children': 'fas fa-dot-circle',

    # Top navbar color — dark green matching our theme
    'topmenu_links': [
        {'name': 'Dashboard', 'url': '/manager/', 'new_window': True},
        {'name': 'POS Terminal', 'url': '/pos/', 'new_window': True},
        {'name': 'Finance', 'url': '/finance/', 'new_window': True},
    ],

    # Sidebar ordering
    'order_with_respect_to': [
        'core', 'core.dish', 'core.dishcategory',
        'core.salestransaction', 'core.saleitem',
        'core.expense', 'core.expensecategory',
        'core.rawmaterial', 'core.rawmaterialcategory',
        'core.stockadjustment', 'core.auditlog',
        'core.user', 'core.mealsession', 'core.dailyreport',
    ],

    # Show counts on menu items
    'show_sidebar': True,
    'navigation_expanded': True,
    'hide_apps': [],
    'hide_models': [],

    # Search bar
    'search_model': ['auth.user'],
    'user_avatar': None,

    # Change view UI
    'changeform_format': 'horizontal_tabs',
    'changeform_format_overrides': {},

    # Show/hide UI elements
    'show_ui_builder': False,
    'related_modal_active': True,
}

JAZZMIN_UI_TWEAKS = {
    'navbar_small_text': False,
    'footer_small_text': False,
    'body_small_text': False,
    'brand_small_text': False,
    'brand_colour': 'navbar-success',   # Green navbar brand
    'accent': 'accent-teal',
    'navbar': 'navbar-dark',
    'no_navbar_border': True,
    'navbar_fixed': True,
    'layout_boxed': False,
    'footer_fixed': False,
    'sidebar_fixed': True,
    'sidebar': 'sidebar-dark-teal',     # Dark teal sidebar
    'sidebar_nav_small_text': False,
    'sidebar_disable_expand': False,
    'sidebar_nav_child_indent': False,
    'sidebar_nav_compact_style': True,
    'sidebar_nav_legacy_style': False,
    'sidebar_nav_flat_style': True,
    'theme': 'darkly',                  # Dark Bootswatch theme
    'dark_mode_theme': 'darkly',
    'button_classes': {
        'primary': 'btn-primary',
        'secondary': 'btn-secondary',
        'info': 'btn-info',
        'warning': 'btn-warning',
        'danger': 'btn-danger',
        'success': 'btn-success',
    },
}