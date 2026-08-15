"""Safely reset one application user's password.

Usage:
    python set_passwords.py

The old version reset every user to the public password ``password123``.
This replacement intentionally requires an explicit username and a hidden
password prompt.
"""

import getpass
import os

import bcrypt
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen_config.settings')
django.setup()

from core.models import User  # noqa: E402


def run():
    username = input('Username to reset: ').strip()
    if not username:
        raise SystemExit('Username is required.')

    try:
        user = User.objects.get(user_name=username)
    except User.DoesNotExist as exc:
        raise SystemExit(f'User not found: {username}') from exc

    password = getpass.getpass('New password: ')
    confirmation = getpass.getpass('Confirm password: ')
    if password != confirmation:
        raise SystemExit('Passwords do not match.')
    if len(password) < 8:
        raise SystemExit('Password must be at least 8 characters long.')

    user.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user.save(update_fields=['password_hash'])
    print(f'Password updated for {user.user_name}.')


if __name__ == '__main__':
    run()
