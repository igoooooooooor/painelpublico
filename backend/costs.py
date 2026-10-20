"""Custo mensal por parlamentar para a lista: o mês principal da ficha e a média do mandato, com as mesmas regras.

Câmara: a média do custo do mandato (``mandate-cost.json``): salário bruto, auxílios, cota e verba de
gabinete, nos meses com as quatro partes. Senado: despesas identificadas (``senate-cost.json`` e a cota do
banco): remuneração, equipe do gabinete e cota, média de cada parte sobre os meses com as três, somadas,
como no cartão da ficha (``frontend/scripts/profile-senate-cost.js``).

Nas duas Casas, só entram meses com as notas da cota já assentadas: 3 meses de folga até a fotografia do
banco (``snapshotAt``), como ``PROFILE_COST_SETTLE_MONTHS`` em ``frontend/scripts/profile-cost.js``. Sem
nenhum mês com a folga, valem todos (a ficha avisa). O snapshot da Câmara não muda: a média é refeita aqui
sobre os meses assentados, com a mesma conta de ``principal`` em ``ingest/mandate_cost_composition.py``.

As duas Casas não publicam as mesmas partes: os valores servem para ordenar e comparar dentro da mesma
Casa, nunca entre Câmara e Senado. Sem mês com todas as partes, não há custo (nunca estimado).
"""
from __future__ import annotations

import math
import threading
from fractions import Fraction

from . import config, profiles
from .settlement import SETTLE_MONTHS, settled_cutoff, settled_periods  # noqa: F401 - regra compartilhada com a média da cota

_PARTS = ('remuneration', 'allowances', 'quota', 'office')

_lock = threading.Lock()
_cache: dict = {}


def _cents(value):
    return isinstance(value, int) and not isinstance(value, bool)


def chamber_average(record, as_of):
    """(centavos, meses) da média do mandato na Câmara sobre os meses assentados, ou None.

    Soma das médias de cada parte, arredondada para baixo uma vez; numa lacuna confirmada, a parte é média só
    dos meses em que foi publicada. Sem mês fora, vale ``monthlyAverageCents`` do snapshot.
    """
    if not isinstance(record, dict) or not _cents(record.get('monthlyAverageCents')):
        return None
    used = settled_periods(record.get('usedMonths') or [], None)
    if not used:
        return None
    periods = settled_periods(used, as_of)
    months = record.get('months')
    if len(periods) == len(used) or not isinstance(months, dict):
        return record['monthlyAverageCents'], used
    total = Fraction(0)
    for part in _PARTS:
        values = [value for value in (((months.get(period) or {}).get('valuesCents') or {}).get(part) for period in periods)
                  if _cents(value)]
        if not values:
            return None
        total += Fraction(sum(values), len(values))
    return math.floor(total), periods


def latest_period(periods, as_of):
    """(mês, assentado) mostrado no "Quanto custa?" da ficha: o mais recente com a folga; sem nenhum, o mais recente.

    Mesma regra de ``profileCostPickMonth`` em ``frontend/scripts/profile-cost.js``.
    """
    ordered = sorted({period for period in periods if isinstance(period, str)})
    if not ordered:
        return None
    cutoff = settled_cutoff(as_of)
    settled = [period for period in ordered if cutoff is None or period <= cutoff]
    return (settled[-1], True) if settled else (ordered[-1], False)


def chamber_latest(record, as_of):
    """(centavos, mês, assentado) do mês principal da ficha na Câmara: as quatro partes publicadas no mês."""
    months = record.get('months') if isinstance(record, dict) else None
    if not isinstance(months, dict):
        return None
    complete = [period for period in record.get('usedMonths') or []
                if all(_cents(((months.get(period) or {}).get('valuesCents') or {}).get(part)) for part in _PARTS)]
    pick = latest_period(complete, as_of)
    if not pick:
        return None
    values = months[pick[0]]['valuesCents']
    return sum(values[part] for part in _PARTS), pick[0], pick[1]


def _chamber(snapshot, as_of=None):
    out = {}
    for identifier, record in ((snapshot or {}).get('profiles') or {}).items():
        if isinstance(record, dict) and record.get('house') == 'camara' and record.get('id') == identifier:
            average = chamber_average(record, as_of)
            if average:
                months = record.get('months') or {}
                # Verba de gabinete publicada como R$ 0,00 num mês da média (suplentes com equipe listada):
                # o custo fica sem a equipe e não serve de "menor" ou "maior" da home.
                zero_office = any(((months.get(period) or {}).get('valuesCents') or {}).get('office') == 0
                                  for period in average[1])
                out[identifier] = {'house': 'camara', 'cents': average[0], 'months': len(average[1]),
                                   'zeroOffice': zero_office}
                latest = chamber_latest(record, as_of)
                if latest:
                    out[identifier].update(latestCents=latest[0], latestPeriod=latest[1], latestSettled=latest[2])
    return out


def _floor_average(values):
    return sum(values) // len(values)


def _senate(snapshot, quota_by_month, as_of=None):
    out = {}
    for identifier, record in ((snapshot or {}).get('profiles') or {}).items():
        if not isinstance(record, dict) or record.get('id') != identifier:
            continue
        complete = {}
        for period, month in (record.get('months') or {}).items():
            quota = quota_by_month.get((identifier, period))
            # Bruto zero ou negativo (acerto ou abate-teto) não é a remuneração do mês, como no cartão.
            if (_cents(month.get('remunerationCents')) and month['remunerationCents'] > 0 and _cents(month.get('officeCents'))
                    and quota is not None):
                complete[period] = (month['remunerationCents'], month['officeCents'], quota)
        pick = latest_period(complete, as_of)
        by_period = complete
        complete = [complete[period] for period in settled_periods(complete, as_of)]
        if complete:
            # Média de cada parte sobre os mesmos meses, arredondada para baixo, e a soma das três (como no cartão).
            cents = sum(_floor_average([values[i] for values in complete]) for i in range(3))
            out[identifier] = {'house': 'senado', 'cents': cents, 'months': len(complete),
                               'latestCents': sum(by_period[pick[0]]), 'latestPeriod': pick[0], 'latestSettled': pick[1]}
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
    as_of = stamp[0] if stamp else None
    value = {**_chamber(chamber, as_of), **(_senate(senate, _senate_quota(db), as_of) if senate else {})}
    with _lock:
        _cache.update(key=key, value=value)
    return value
