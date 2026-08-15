# Canteen IEM Debug Report

This copy was debugged against a clean SQLite database so the application logic
could be verified without depending on a local MySQL service. The normal runtime
still defaults to MySQL.

## Major fixes applied

- Added missing runtime dependencies: `django-jazzmin`, `django-htmx`, and `reportlab`.
- Re-saved `requirements.txt` as normal UTF-8/ASCII text so `pip install -r` works normally.
- Added an optional SQLite mode (`CANTEEN_USE_SQLITE=1`) for checks/tests while preserving MySQL as the default.
- Moved database settings, secret key, debug mode, allowed hosts, and secure-cookie mode behind environment-variable overrides.
- Fixed `STATIC_URL` and `MEDIA_URL` so nested pages resolve assets from `/static/` and `/media/` correctly.
- Added the missing migration for the `kitchen` role and migrations for the expanded ingredient units.
- Fixed role guards so admin/manager/cashier/kitchen permissions are consistent.
- Removed automatic insertion of demo procurement records from normal login/dashboard requests.
- Removed automatic creation of a default kitchen account with a known password.
- Protected remaining manual demo seed scripts behind `CANTEEN_ALLOW_DEMO_SEED=1` and removed default-password manager creation.
- Made checkout preserve decimal currency values instead of rounding prices to whole rupees.
- Added validation for payment type, order type, and insufficient cash.
- Made generated transaction and PO identifiers collision-resistant.
- Kept stock deduction inside an atomic transaction with row locks.
- Made transaction voiding POST-only and idempotent.
- Prevented imported historical sales from adding fake inventory when voided.
- Made PO receiving update `quantity_received`, receiver/date, inventory, and reject duplicate receipt.
- Added supplier email validation.
- Added URLs for the daily report view that previously existed but could not be opened directly.
- Fixed daily reports so they recalculate instead of returning stale saved values, and so gross/net revenue are not double-discounted.
- Reworked the recipe importer so ingredient rates are not incorrectly used as dish selling prices.
- Batched recipe-import database writes; the supplied 4,442 valid recipe rows now import in roughly 5 seconds in the clean SQLite validation environment instead of issuing thousands of per-row queries.
- Reworked the historical sales importer to read both side-by-side sales tables, use stable IDs, and batch database writes.
- Replaced duplicate root import scripts with wrappers around the canonical Django management commands.
- Replaced the dangerous `set_passwords.py` behavior that reset every user to `password123` with a one-user hidden password prompt.
- Added regression tests for permissions, checkout, stock, voiding, PO receipt, supplier validation, and reports.

## Clean setup

Create a new environment instead of using the bundled Windows `venv` directory:

```bash
python -m venv .venv
```

Activate it, then install dependencies:

```bash
pip install -r requirements.txt
```

Configure MySQL through environment variables when needed:

```text
CANTEEN_DB_NAME
CANTEEN_DB_USER
CANTEEN_DB_PASSWORD
CANTEEN_DB_HOST
CANTEEN_DB_PORT
CANTEEN_SECRET_KEY
CANTEEN_DEBUG
CANTEEN_ALLOWED_HOSTS
CANTEEN_SECURE_COOKIES
CANTEEN_SECURE_SSL_REDIRECT
CANTEEN_HSTS_SECONDS
CANTEEN_HSTS_INCLUDE_SUBDOMAINS
CANTEEN_HSTS_PRELOAD
```

`.env.example` contains the full list of configuration values. This project
does not load `.env` files automatically, so export the values through your
shell/IDE/process manager or add a dotenv loader deliberately if desired.

Run migrations:

```bash
python manage.py migrate
```

Optional source-data imports:

```bash
python manage.py import_recipes
python manage.py import_sales
```

Start the app:

```bash
python manage.py runserver
```

## Local validation mode

For a database-independent development check:

```bash
CANTEEN_USE_SQLITE=1 python manage.py check
CANTEEN_USE_SQLITE=1 python manage.py makemigrations --check --dry-run
CANTEEN_USE_SQLITE=1 python manage.py test
```

## Remaining design limitation

A normal sale stores price and cost snapshots, but it does not store a snapshot
of the exact ingredient recipe used at sale time. If a recipe is changed after
a sale and that old sale is later voided, inventory restoration uses the current
recipe. A fully auditable inventory system should snapshot ingredient usage per
sale (for example, a `SaleItemIngredient` table). This needs a deliberate schema
change rather than a small bug fix.

The historical sales workbook also contains fractional quantities, while
`SaleItem.quantity` is an integer field. The importer currently converts those
rows to integer quantities because the present schema cannot represent the
fractions exactly.

The recipe workbook also contains inconsistent units for some ingredient names
(for example the same material can appear as kg, packet, piece, or litre in
different rows). The importer preserves the row quantity and normalized row
unit rather than inventing conversions. Inventory arithmetic still assumes the
stored quantities are already comparable. If those workbook unit differences
are semantically real rather than data-entry labels, the next schema change
should add explicit unit conversion/base-unit handling.
