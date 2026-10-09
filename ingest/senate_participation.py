#!/usr/bin/env python3
"""Participação dos senadores nas votações nominais do mandato e licenças, para a ficha.

Não é a lista de presença do Diário do Senado (``senate_attendance.py``, só 2026). Pelo Regimento (art. 13,
§ 2º), o(a) senador(a) presente deve participar das votações nominais da sessão; as votações nominais
publicadas pelo Senado trazem, para cada senador(a), o voto ou o motivo de não votar. Por sessão com
votação nominal em que a pessoa estava em exercício (histórico de exercício do Senado), conta:

- ``participou``: votou (Sim, Não, Abstenção) ou presidiu a sessão em alguma votação nominal;
- ``presente_sem_voto``: "Presente – Não registrou voto" e nenhum voto na sessão;
- ``ausencia_com_motivo``: rótulo de licença, missão ou atividade parlamentar, com o motivo do Senado;
- ``nao_compareceu``: "Não Compareceu";
- ``sem_registro``: a pessoa não aparece nas votações da sessão (não vira falta).

Licenças: ``/senador/{codigo}/licencas`` desde fev/2023, com data e tipo, publicadas pelo Senado.
Entradas: ``data/snapshots/senado-atividade.json`` (votações) e o cache de exercício de ``senate_cost.py``.
Saída: ``data/snapshots/senate-participation.json``.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
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

ACTIVITY_PATH = ROOT / 'data' / 'snapshots' / 'senado-atividade.json'
OUTPUT = ROOT / 'data' / 'snapshots' / 'senate-participation.json'
LEAVES_DIR = ROOT / 'data' / 'raw' / 'senado-licencas'
LEAVES_URL = 'https://legis.senado.leg.br/dadosabertos/senador/{code}/licencas.json?dataInicio=20230201'
VOTED = {'Sim', 'Não', 'Abstenção', 'Presidente (art. 51 RISF)'}
PRESENT_NO_VOTE = 'Presente – Não registrou voto'
NOT_PRESENT = 'Não Compareceu'
WITH_REASON = {'Atividade parlamentar', 'Licença saúde', 'Missão da Casa no País/exterior', 'Licença Particular',
               'Licença paternidade ou ao adotante'}
STATUSES = ('participou', 'presente_sem_voto', 'ausencia_com_motivo', 'nao_compareceu', 'sem_registro', 'outro')


def session_status(labels):
    """Situação de uma pessoa numa sessão, a partir dos rótulos dela nas votações nominais da sessão."""
    if not labels:
        return 'sem_registro', None
    if labels & VOTED:
        return 'participou', None
    if PRESENT_NO_VOTE in labels:
        return 'presente_sem_voto', None
    reasons = sorted(labels & WITH_REASON)
    if reasons:
        return 'ausencia_com_motivo', reasons[0]
    if NOT_PRESENT in labels:
        return 'nao_compareceu', None
    return 'outro', sorted(labels)[0]


def in_office(intervals, day: date) -> bool | None:
    if intervals is None:
        return None
    return any(start <= day and (end is None or end >= day) for start, end in intervals)


def leaves(code: str, collect: bool):
    cache = LEAVES_DIR / f'{code}.json'
    if collect:
        request = Request(LEAVES_URL.format(code=code), headers={'Accept': 'application/json', 'User-Agent': USER_AGENT})
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
        write_atomic(cache, {'fetchedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(), 'payload': payload})
    if not cache.exists():
        return None
    payload = json.loads(cache.read_text(encoding='utf-8'))['payload']
    parliamentarian = ((payload or {}).get('LicencaParlamentar') or {}).get('Parlamentar') or {}
    items = senate_cost._as_list((parliamentarian.get('Licencas') or {}).get('Licenca'))
    out = []
    for item in items:
        if item.get('DataInicio') and item['DataInicio'] >= '2023-02-01':
            out.append({'start': item['DataInicio'][:10], 'end': (item.get('DataFim') or item.get('DataFimPrevista') or '')[:10] or None,
                        'type': item.get('DescricaoTipoAfastamento') or item.get('SiglaTipoAfastamento')})
    return sorted(out, key=lambda leave: leave['start'], reverse=True)


def build(votes, people, exercises, leave_lists):
    """``votes``: itens de votação (id 'senado:<sessão>:<votação>', data, rows); ``people``: ids do Senado."""
    sessions = {}
    for vote in votes:
        session = vote['id'].split(':')[1]
        entry = sessions.setdefault(session, {'date': vote['data'][:10], 'labels': {}, 'url': vote.get('sourceUrl')})
        for row in vote.get('rows') or []:
            entry['labels'].setdefault(row[0], set()).add(row[4])
    profiles = {}
    for identifier in sorted(people, key=lambda i: int(i.split(':')[1])):
        intervals = exercises.get(identifier)
        counts, reasons, rows = Counter(), Counter(), []
        for session_id, session in sorted(sessions.items(), key=lambda kv: kv[1]['date']):
            if in_office(intervals, date.fromisoformat(session['date'])) is False:
                continue
            status, reason = session_status(session['labels'].get(identifier, set()))
            counts[status] += 1
            if reason and status == 'ausencia_com_motivo':
                reasons[reason] += 1
            if status != 'participou':
                rows.append({'session': session_id, 'date': session['date'], 'status': status, 'reason': reason})
        if counts or leave_lists.get(identifier):
            profiles[identifier] = {'sessions': sum(counts.values()), 'counts': {k: counts.get(k, 0) for k in STATUSES},
                                    'reasons': dict(reasons.most_common()), 'notParticipated': rows,
                                    'exerciseHistory': intervals is not None, 'leaves': leave_lists.get(identifier) or []}
    return profiles


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--collect', action='store_true', help='consulta as licenças na API do Senado')
    args = parser.parse_args(argv)
    activity = json.loads(ACTIVITY_PATH.read_text(encoding='utf-8'))['votacoes']
    db = sqlite3.connect(f'file:{senate_cost.DB_PATH}?mode=ro', uri=True)
    people = [row[0] for row in db.execute("SELECT id FROM authorities WHERE id LIKE 'senado:%' AND role='senador'")]
    exercises, leave_lists, failures = {}, {}, 0
    for identifier in people:
        code = identifier.split(':')[1]
        exercises[identifier], _ = senate_cost.load_exercises(code, False)
        try:
            leave_lists[identifier] = leaves(code, args.collect)
        except OSError:
            failures += 1
            leave_lists[identifier] = leaves(code, False)
    profiles = build(activity['items'], people, exercises, leave_lists)
    write_atomic(OUTPUT, {
        'schemaVersion': 1, 'generatedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'period': {'start': activity.get('startDate'), 'end': activity.get('endDate')},
        'votesSource': activity.get('sourceUrl'), 'leavesSource': LEAVES_URL.format(code='{codigo}'),
        'sessionCount': len({vote['id'].split(':')[1] for vote in activity['items']}),
        'rule': 'Por sessão com votação nominal pública em que a pessoa estava em exercício: votou ou presidiu; presente sem votar; '
                'ausência com motivo registrado pelo Senado; não compareceu; sem registro (não vira falta).',
        'profiles': profiles})
    print(f'{len(profiles)} senadores(as); falhas ao consultar licenças: {failures}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
