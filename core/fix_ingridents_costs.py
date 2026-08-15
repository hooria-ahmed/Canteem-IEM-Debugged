"""Legacy compatibility wrapper for ingredient-cost synchronization.

The canonical recipe importer now performs this synchronization safely and in
batches. Prefer: python manage.py import_recipes
"""

import os

import django
from django.core.management import call_command

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen_config.settings')
django.setup()


if __name__ == '__main__':
    call_command('import_recipes')
