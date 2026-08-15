"""Legacy wrapper. Prefer: python manage.py import_recipes"""
from django.core.management import call_command


def import_recipes():
    call_command('import_recipes')


if __name__ == '__main__':
    import_recipes()
