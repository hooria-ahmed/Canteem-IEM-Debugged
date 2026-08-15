"""Canteen project package initialization."""
import os

# PyMySQL is only needed for the normal MySQL configuration.  The SQLite
# switch exists so system checks/tests can run without a local MySQL server.
if os.environ.get("CANTEEN_USE_SQLITE", "0") != "1":
    import pymysql

    # Django's MySQL backend checks the mysqlclient-compatible version tuple.
    # PyMySQL provides the compatible DB-API implementation used by this app.
    pymysql.version_info = (2, 2, 1, "final", 0)
    pymysql.install_as_MySQLdb()
