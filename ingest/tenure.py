#!/usr/bin/env python3
"""Desde quando cada parlamentar está no cargo sem interrupção, para o rótulo da ficha.

Senado: mandatos com algum exercício, encadeados do atual para trás enquanto um termina na véspera do
início do seguinte; a data é o primeiro dia de exercício nessa sequência (suplente conta a partir de
quando assumiu). Fonte: histórico de mandatos da API do Senado, já em cache por ``ingest/senate_cost.py``.

Câmara: legislaturas com algum registro de exercício no histórico do(a) deputado(a) (antes de 2003, o
registro "no início da legislatura"), encadeadas da atual para trás enquanto forem seguidas; a data é o
primeiro exercício da mais antiga, ou o início dela quando a Câmara não publica a data.
Fonte: ``/deputados/{id}/historico`` da API da Câmara (cache em ``data/raw/camara-historico/``).

Mandato anterior separado por um intervalo não entra: "desde" é a sequência atual, não a carreira.
Sem histórico, a pessoa fica fora do arquivo (a ficha não mostra o rótulo).
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ingest import senate_cost  # noqa: E402
from ingest.senate_office_pilot import USER_AGENT, write_atomic  # noqa: E402

OUTPUT = ROOT / 'data' / 'snapshots' / 'tenure.json'
CHAMBER_DIR = ROOT / 'data' / 'raw' / 'camara-historico'
CHAMBER_URL = 'https://dadosabertos.camara.leg.br/api/v2/deputados/{code}/historico'
CURRENT_LEGISLATURE = 57


def _day(value):
    return date.fromisoformat(str(value)[:10]) if value else None


def senate_since(payload) -> str | None:
    parliamentarian = ((payload or {}).get('MandatoParlamentar') or {}).get('Parlamentar') or {}
    mandates = []
    for mandate in senate_cost._as_list((parliamentarian.get('Mandatos') or {}).get('Mandato')):
        exercises = [_day(e.get('DataInicio')) for e in senate_cost._as_list((mandate.get('Exercicios') or {}).get('Exercicio'))
                     if e.get('DataInicio')]
        first = mandate.get('PrimeiraLegislaturaDoMandato') or {}
        second = mandate.get('SegundaLegislaturaDoMandato') or {}
        start, end = _day(first.get('DataInicio')), _day(second.get('DataFim') or first.get('DataFim'))
        if exercises and start and end:
            mandates.append((start, end, min(exercises)))
    if not mandates:
        return None
    mandates.sort(reverse=True)
    chain = [mandates[0]]
    for previous in mandates[1:]:
        if previous[1] + timedelta(days=1) >= chain[-1][0]:
            chain.append(previous)
        else:
            break
    return min(first_exercise for _, _, first_exercise in chain).isoformat()


def legislature_start(legislature: int) -> date:
    """1º de fevereiro do ano de início da legislatura (57ª: 2023; a cada 4 anos)."""
    return date(2023 - 4 * (CURRENT_LEGISLATURE - legislature), 2, 1)


def chamber_since(entries) -> str | None:
    """Legislaturas com exercício registrado, ou, antes de 2003, com o registro "no início da legislatura"
    (a Câmara não publica a situação nessas legislaturas antigas e usa uma data genérica nesses registros)."""
    by_legislature = {}
    for entry in entries or []:
        if not entry.get('idLegislatura'):
            continue
        legislature = int(entry['idLegislatura'])
        if legislature > CURRENT_LEGISLATURE:
            continue
        if (entry.get('situacao') or '') == 'Exercício' and entry.get('dataHora'):
            by_legislature.setdefault(legislature, []).append(_day(entry['dataHora']))
        elif 'início da legislatura' in (entry.get('descricaoStatus') or ''):
            by_legislature.setdefault(legislature, []).append(legislature_start(legislature))
    if CURRENT_LEGISLATURE not in by_legislature:
        return None
    legislature = CURRENT_LEGISLATURE
    while legislature - 1 in by_legislature:
        legislature -= 1
    return max(min(by_legislature[legislature]), legislature_start(legislature)).isoformat()


def chamber_history(code: str, collect: bool):
    cache = CHAMBER_DIR / f'{code}.json'
    if collect and not cache.exists():
        request = Request(CHAMBER_URL.format(code=code), headers={'Accept': 'application/json', 'User-Agent': USER_AGENT})
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
        write_atomic(cache, {'fetchedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(), 'payload': payload})
    if not cache.exists():
        return None
    return json.loads(cache.read_text(encoding='utf-8'))['payload'].get('dados')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--collect', action='store_true', help='consulta o histórico da Câmara que ainda não está em cache')
    args = parser.parse_args(argv)
    db = sqlite3.connect(f'file:{senate_cost.DB_PATH}?mode=ro', uri=True)
    profiles, missing = {}, []
    for (identifier,) in db.execute("SELECT id FROM authorities WHERE id LIKE 'senado:%' AND role='senador'"):
        cache = senate_cost.EXERCISE_DIR / f'{identifier.split(":")[1]}.json'
        since = senate_since(json.loads(cache.read_text(encoding='utf-8'))['payload']) if cache.exists() else None
        if since:
            profiles[identifier] = {'house': 'senado', 'since': since}
        else:
            missing.append(identifier)
    for (identifier,) in db.execute("SELECT authorityId FROM roster WHERE authorityId LIKE 'camara:%'"):
        try:
            since = chamber_since(chamber_history(identifier.split(':')[1], args.collect))
        except OSError:
            since = None
        if since:
            profiles[identifier] = {'house': 'camara', 'since': since}
        else:
            missing.append(identifier)
    write_atomic(OUTPUT, {
        'schemaVersion': 1, 'generatedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'rule': 'Início da sequência ininterrupta de mandatos (Senado) ou legislaturas (Câmara) com exercício, até o atual.',
        'sources': {'senado': senate_cost.EXERCISE_URL, 'camara': CHAMBER_URL}, 'profiles': profiles})
    print(f'{len(profiles)} com data; sem histórico: {len(missing)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
