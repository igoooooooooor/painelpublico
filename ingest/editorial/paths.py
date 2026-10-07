"""Caminhos dos coletores da amostra editorial original."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = ROOT / "data" / "snapshots"
RAW = ROOT / "data" / "raw" / "editorial"
CACHE = ROOT / "data" / "raw" / "editorial-extra"
