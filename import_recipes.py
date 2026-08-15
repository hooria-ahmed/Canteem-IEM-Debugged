"""Compatibility wrapper for the Django recipe import command."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen_config.settings')
django.setup()

from django.core.management import call_command

if __name__ == '__main__':
    call_command('import_recipes')
