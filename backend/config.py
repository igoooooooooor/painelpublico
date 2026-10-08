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
# Snapshots editoriais (fora do Git). No servidor ficam junto do banco: PAINEL_SNAPSHOTS=/opt/painel/data/snapshots.
_snapshots_setting = os.environ.get("PAINEL_SNAPSHOTS")
SNAPSHOTS_PATH = Path(_snapshots_setting).expanduser() if _snapshots_setting else ROOT / "data" / "snapshots"
if not SNAPSHOTS_PATH.is_absolute():
    SNAPSHOTS_PATH = ROOT / SNAPSHOTS_PATH
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = 4
# Complemento do auxílio-moradia lançado na CEAP da Câmara: publicado com líquido negativo, fica
# à parte da cota (natureza própria) para não reduzir total, média, lista ou alertas. O sinal é preservado.
HOUSING_COMPLEMENT_CATEGORY = "COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA"
HOUSING_COMPLEMENT_KIND = "complemento_moradia"
HOUSING_COMPLEMENT_SOURCE = "camara_ceap"
# Listas oficiais completas (quem está em exercício). Só uma coleta bem-sucedida troca quem está nelas.
ROSTER_SOURCES = ("camara_deputies_current", "senado_senators_current")
