"""Fichas complementares (perfis.json) servidas uma a uma, em vez de embutidas na página.

O arquivo tem ~15 MB (projetos de 595 parlamentares). Ele é lido uma vez e relido só quando muda.
"""
import json
import threading

from . import config

SNAPSHOTS_PATH = config.SNAPSHOTS_PATH

_lock = threading.Lock()
_state = {'mtime': None, 'data': None, 'path': None}


def _load(path):
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    with _lock:
        if _state['path'] != path or _state['mtime'] != mtime:
            raw = json.loads(path.read_text(encoding='utf-8'))
            _state.update(path=path, mtime=mtime, data=raw)
        return _state['data']


def perfil(identifier, path=None):
    """Perfil complementar de um parlamentar ou None se o arquivo ou o registro não existirem."""
    data = _load(path or SNAPSHOTS_PATH / 'perfis.json')
    if not data:
        return None
    profile = (data.get('profiles') or {}).get(identifier)
    if profile is None:
        return None
    return {**profile, 'generatedAt': data.get('generatedAt')}
