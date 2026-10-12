"""Onde ficam as revisões do Placar.

As revisões (``chamber-vote-reviews-<data>.json``, ``chamber-vote-segment-reviews-<data>.json`` e
``chamber-vote-urgency-reviews-<data>.json``)
são decisões editoriais escritas à mão. Desde 11/10/2026 elas moram em ``reviews/``, na raiz do
repositório, versionadas no Git: quem revisa commita, e o deploy automático as leva ao servidor
junto com o código, sem comando à parte. ``data/reviews/`` continua sendo a pasta dos arquivos
gerados (inventário, rascunhos, fila) e também é lida como alternativa para revisões antigas que
ainda não foram movidas; em caso de nome igual, a cópia versionada prevalece.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_DIR_NAME = 'reviews'
LOCAL_DIR_NAME = 'data/reviews'
REVIEW_PATTERNS = ('chamber-vote-reviews-*.json', 'chamber-vote-segment-reviews-*.json',
                   'chamber-vote-urgency-reviews-*.json')


def review_dirs(root: Path = ROOT) -> tuple[Path, Path]:
    """(versionada, local), nesta ordem de precedência."""
    return root / REPO_DIR_NAME, root / LOCAL_DIR_NAME


def find_review(root: Path, name: str) -> Path:
    """Caminho da revisão ``name``: a versionada se existir, senão a local (mesmo que ausente)."""
    repo, local = review_dirs(root)
    return repo / name if (repo / name).exists() else local / name


def review_files(root: Path = ROOT, patterns: tuple[str, ...] = REVIEW_PATTERNS) -> dict[str, Path]:
    """Nome → caminho de todas as revisões, com a cópia versionada vencendo a local."""
    found: dict[str, Path] = {}
    repo, local = review_dirs(root)
    for directory in (local, repo):
        if directory.is_dir():
            for pattern in patterns:
                for path in directory.glob(pattern):
                    found[path.name] = path
    return found
