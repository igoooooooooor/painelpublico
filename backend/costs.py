"""Custo médio mensal por parlamentar para a lista, com as mesmas regras das fichas.

Câmara: a média do custo do mandato (``mandate-cost.json``): salário bruto, auxílios, cota e verba de
gabinete, nos meses com as quatro partes. Senado: despesas identificadas (``senate-cost.json`` e a cota do
banco): remuneração, equipe do gabinete e cota, média de cada parte sobre os meses com as três, somadas,
como no cartão da ficha (``frontend/scripts/profile-senate-cost.js``).

As duas Casas não publicam as mesmas partes: os valores servem para ordenar e comparar dentro da mesma
Casa, nunca entre Câmara e Senado. Sem mês com todas as partes, não há custo (nunca estimado).
"""
from __future__ import annotations

import threading

from . import config, profiles

_lock = threading.Lock()
_cache: dict = {}


def _chamber(snapshot):
    out = {}
    for identifier, record in ((snapshot or {}).get('profiles') or {}).items():
        if (isinstance(record, dict) and record.get('house') == 'camara' and record.get('id') == identifier
                and isinstance(record.get('monthlyAverageCents'), int) and record.get('usedMonths')):
            out[identifier] = {'house': 'camara', 'cents': record['monthlyAverageCents'], 'months': len(record['usedMonths'])}
    return out


def _floor_average(values):
    return sum(values) // len(values)


def _senate(snapshot, quota_by_month):
    out = {}
    for identifier, record in ((snapshot or {}).get('profiles') or {}).items():
        if not isinstance(record, dict) or record.get('id') != identifier:
            continue
        complete = []
        for period, month in (record.get('months') or {}).items():
            quota = quota_by_month.get((identifier, period))
            if isinstance(month.get('remunerationCents'), int) and isinstance(month.get('officeCents'), int) and quota is not None:
                complete.append((month['remunerationCents'], month['officeCents'], quota))
        if complete:
            # Média de cada parte sobre os mesmos meses, arredondada para baixo, e a soma das três (como no cartão).
            cents = sum(_floor_average([values[i] for values in complete]) for i in range(3))
            out[identifier] = {'house': 'senado', 'cents': cents, 'months': len(complete)}
    return out


def _senate_quota(db):
    rows = db.execute('''SELECT authorityId,year,month,SUM(amountCents) FROM (
            SELECT authorityId,year,month,amountCents,kind FROM expenses WHERE authorityId LIKE 'senado:%'
            UNION ALL SELECT authorityId,year,month,amountCents,kind FROM quota_history WHERE authorityId LIKE 'senado:%')
        WHERE kind='reembolso' GROUP BY authorityId,year,month''')
    return {(identifier, f'{year:04d}-{month:02d}'): cents for identifier, year, month, cents in rows}


def monthly_costs(db, snapshots_path=None):
    """{id: {'house', 'cents', 'months'}}; recalculado quando um snapshot ou a fotografia do banco muda."""
    path = snapshots_path or config.SNAPSHOTS_PATH
    chamber = profiles._load(path / 'mandate-cost.json')
    senate = profiles._load(path / 'senate-cost.json')
    stamp = db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone()
    key = (id(chamber), id(senate), stamp[0] if stamp else None, str(path))
    with _lock:
        if _cache.get('key') == key:
            return _cache['value']
    value = {**_chamber(chamber), **(_senate(senate, _senate_quota(db)) if senate else {})}
    with _lock:
        _cache.update(key=key, value=value)
    return value
