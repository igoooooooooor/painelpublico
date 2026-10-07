"""Fichas complementares (perfis.json) servidas uma a uma, em vez de embutidas na página.

O arquivo tem ~15 MB (projetos de 595 parlamentares). Ele é lido uma vez e relido só quando muda.
"""
import json
import re
import threading
from pathlib import Path

from . import config

SNAPSHOTS_PATH = config.SNAPSHOTS_PATH

_lock = threading.Lock()
_cache = {}
_SENATE_ID = re.compile(r'^senado:\d+$')


def _reject_json_constant(value):
    raise ValueError(f'Constante JSON inválida: {value}')


def _load(path):
    path = path.expanduser().resolve()
    with _lock:
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            _cache.pop(path, None)
            return None

        cached = _cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        try:
            raw = json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_json_constant)
        except (OSError, UnicodeError, ValueError):
            _cache.pop(path, None)
            return None
        if not isinstance(raw, dict):
            _cache.pop(path, None)
            return None
        _cache[path] = (mtime, raw)
        return raw


def atividade_senado(path=None):
    """Snapshot de presença e votações do Senado, ou None se estiver ausente ou inválido."""
    return _load(Path(path) if path is not None else SNAPSHOTS_PATH / 'senado-atividade.json')


def _senado_projetos(identifier, perfil_path):
    if not _SENATE_ID.fullmatch(identifier):
        return None, None
    data = _load(perfil_path.parent / 'senado-projetos.json')
    if data is None:
        return None, None
    profiles = data.get('profiles')
    if not isinstance(profiles, dict):
        return None, None
    profile = profiles.get(identifier)
    if not isinstance(profile, dict) or not isinstance(profile.get('projetos'), dict):
        return None, None
    return profile['projetos'], data.get('generatedAt')


def perfil(identifier, path=None):
    """Perfil complementar de um parlamentar ou None se o arquivo ou o registro não existirem."""
    profile_path = Path(path) if path is not None else SNAPSHOTS_PATH / 'perfis.json'
    data = _load(profile_path)
    profiles = data.get('profiles') if data is not None else None
    profile = profiles.get(identifier) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        profile = None

    projects, projects_generated_at = _senado_projetos(identifier, profile_path)
    if profile is None:
        if projects is None:
            return None
        result = {'id': identifier, 'role': 'senador', 'projetos': projects}
        generated_at = data.get('generatedAt') if data is not None else projects_generated_at
        if generated_at is not None:
            result['generatedAt'] = generated_at
        return result

    result = {**profile, 'generatedAt': data.get('generatedAt')}
    if projects is not None:
        result['projetos'] = projects
    return result
