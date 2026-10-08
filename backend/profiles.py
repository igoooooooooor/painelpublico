"""Fichas complementares (perfis.json) servidas uma a uma, em vez de embutidas na página.

O arquivo tem ~15 MB (projetos de 595 parlamentares). Ele é lido uma vez e relido só quando muda.
"""
from copy import deepcopy
import json
import re
import threading
import time
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
            stat = path.stat()
        except OSError:
            _cache.pop(path, None)
            return None
        mtime = (stat.st_mtime_ns, stat.st_size)
        # Relógios de arquivo podem ter resolução grossa: duas gravações no mesmo instante teriam a
        # mesma data. Um arquivo alterado há menos de 2 s é relido em vez de confiar no cache.
        settled = time.time_ns() - stat.st_mtime_ns > 2_000_000_000

        cached = _cache.get(path)
        if cached is not None and cached[0] == mtime and settled:
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


def senate_activity(path=None):
    """Snapshot de presença e votações do Senado, ou None se estiver ausente ou inválido."""
    return _load(Path(path) if path is not None else SNAPSHOTS_PATH / 'senado-atividade.json')


def _senate_projects(identifier, profile_path):
    if not _SENATE_ID.fullmatch(identifier):
        return None, None
    data = _load(profile_path.parent / 'senado-projetos.json')
    if data is None:
        return None, None
    profiles = data.get('profiles')
    if not isinstance(profiles, dict):
        return None, None
    profile = profiles.get(identifier)
    if not isinstance(profile, dict) or not isinstance(profile.get('projetos'), dict):
        return None, None
    return profile['projetos'], data.get('generatedAt')


def _attach_project_statuses(result, identifier, profile_path):
    """Anexa somente a situação dos projetos desta ficha, sem alterar o cache base."""
    chamber = identifier.split(':', 1)[0]
    projects = result.get('projetos')
    if chamber not in ('camara', 'senado') or not isinstance(projects, dict):
        return result
    items = projects.get('items')
    if not isinstance(items, list):
        return result
    snapshot = _load(profile_path.parent / 'projetos-situacao.json')
    statuses = snapshot.get('projects') if snapshot else None
    if not isinstance(statuses, dict):
        return result
    enriched = []
    for item in items:
        if not isinstance(item, dict):
            enriched.append(item)
            continue
        status = statuses.get(f"{chamber}:{item.get('id')}")
        enriched.append({**item, 'situacaoAtual': deepcopy(status)} if isinstance(status, dict) else item)
    return {**result, 'projetos': {**projects, 'items': enriched}}


def _election_result(identifier, profile_path):
    """Resultado de 2026 desta ficha (eleicoes-2026.json), com fonte e método; None se ausente."""
    data = _load(profile_path.parent / 'eleicoes-2026.json')
    profiles = data.get('profiles') if data is not None else None
    item = profiles.get(identifier) if isinstance(profiles, dict) else None
    if not isinstance(item, dict):
        return None
    return {**deepcopy(item), 'fonte': deepcopy(data.get('fonte')), 'metodo': data.get('metodo'),
            'segundoTurno': data.get('segundoTurno'), 'generatedAt': data.get('generatedAt')}


_MONTH_LISTS = ('exclusionReasons', 'sourceGaps')
_MONTH_FLAGS = ('eligible', 'housingDiscrepancy')
_MONTH_OPTIONAL = ('daysInOffice', 'knownSumCents', 'christmasBonusCents', 'payrollInventory', 'complementSignedCents',
                   'functionalPropertyDays', 'housingAllowanceForCheckCents')


def expand_mandate_cost(record, urls):
    """Reconstrói links e campos dos meses a partir do snapshot compacto (esquema 4)."""
    url = lambda index: urls[index] if isinstance(index, int) and 0 <= index < len(urls) else None
    for period, month in record.get('months', {}).items():
        month.setdefault('period', period)
        for key in _MONTH_LISTS:
            month.setdefault(key, [])
        for key in _MONTH_FLAGS:
            month.setdefault(key, False)
        if month.get('exercise') != 'outside_mandate':
            for key in _MONTH_OPTIONAL:
                month.setdefault(key, None)
        else:
            month.setdefault('daysInOffice', None)
        exercise = month.get('exerciseSource')
        month['exerciseSource'] = {'url': url(exercise)} if url(exercise) else None
        if isinstance(month.get('sources'), dict):
            month['sources'] = {part: {'url': url(index), 'period': period if url(index) else None}
                                for part, index in month['sources'].items()}
        else:
            month.setdefault('valuesCents', {})
    for collection in (*record.get('parts', {}).values(), record.get('christmasBonus') or {}):
        if isinstance(collection, dict) and isinstance(collection.get('sources'), list):
            collection['sources'] = [{'url': url(item[0]), 'period': item[1]}
                                     for item in collection['sources'] if isinstance(item, list) and len(item) == 2]
    return record


def _mandate_cost(identifier, profile_path):
    """Only the approved Câmara composition over the current mandate (Feb/2023–Jul/2026), per profile."""
    if not re.fullmatch(r'camara:\d+', identifier):
        return None
    snapshot = _load(profile_path.parent / 'mandate-cost.json')
    records = snapshot.get('profiles') if snapshot else None
    result = records.get(identifier) if isinstance(records, dict) else None
    if (not isinstance(result, dict) or result.get('id') != identifier
            or result.get('house') != 'camara' or result.get('periodStart') != '2023-02'
            or result.get('periodEnd') != '2026-07'):
        return None
    urls = snapshot.get('urls')
    return expand_mandate_cost(deepcopy(result), urls if isinstance(urls, list) else [])


def profile(identifier, path=None):
    """Perfil complementar de um parlamentar ou None se o arquivo ou o registro não existirem."""
    profile_path = Path(path) if path is not None else SNAPSHOTS_PATH / 'perfis.json'
    data = _load(profile_path)
    profiles = data.get('profiles') if data is not None else None
    profile = profiles.get(identifier) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        profile = None

    projects, projects_generated_at = _senate_projects(identifier, profile_path)
    election_result = _election_result(identifier, profile_path)
    mandate_cost = _mandate_cost(identifier, profile_path)
    if profile is None:
        if projects is None and election_result is None and mandate_cost is None:
            return None
        result = {'id': identifier, 'role': 'senador' if identifier.startswith('senado:') else 'deputado'}
        if projects is not None:
            result['projetos'] = projects
        generated_at = data.get('generatedAt') if data is not None else projects_generated_at
        if generated_at is not None:
            result['generatedAt'] = generated_at
    else:
        result = {**profile, 'generatedAt': data.get('generatedAt')}
        if projects is not None:
            result['projetos'] = projects
    if election_result is not None:
        result['eleicao2026'] = election_result
    if mandate_cost is not None:
        result['mandateCost'] = mandate_cost
    return _attach_project_statuses(result, identifier, profile_path)
