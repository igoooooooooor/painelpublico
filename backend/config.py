"""Shared paths and settings for the local backend."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_database_setting = os.environ.get("PAINEL_DB")
if _database_setting:
    _database_path = Path(_database_setting).expanduser()
    DB_PATH = _database_path if _database_path.is_absolute() else ROOT / _database_path
else:
    DB_PATH = ROOT / "data" / "na-lupa.sqlite3"

BUILD_PATH = ROOT / "dist" / "index.html"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = 1
