#!/usr/bin/env python3
"""Despesas identificadas do mandato no Senado, por senador(a) e mês, para a ficha.

Junta os agregados de remuneração e equipe de gabinete (``senate_office_pilot.py``, saída local) com o
histórico de exercício de cada senador(a) na API de dados abertos do Senado, e grava
``data/snapshots/senate-cost.json`` (publicado). A cota parlamentar vem do banco, na própria ficha.

Motivos de ausência, sem supor nada além da fonte:
- ``fora_do_exercicio``: o histórico de exercício confirma que a pessoa não estava em exercício no mês;
- ``nao_identificado``: a lotação não aparece no arquivo e o exercício no mês não foi confirmado como
  ausente (ou o histórico não pôde ser consultado);
- ``outra_lotacao``: o gabinete aparece, mas sem a linha do(a) senador(a) (pode estar na Mesa ou numa liderança);
- ``lotacao_compartilhada``: duas linhas de senador(a) na mesma lotação (titular licenciado(a) e suplente),
  sem identificador para separar;
- ``sem_lotacao_propria``: a pessoa não tem gabinete com o próprio nome na tabela conferida;
- ``menos_de_3``: equipe com menos de 3 pessoas; o total equivaleria a uma remuneração individual.

Remuneração no próprio gabinete num mês fora do exercício (licença, afastamento para ministério com opção
pelo subsídio) é mantida e marcada com ``paidOutsideExercise``.
"""
from __future__ import annotations

import argparse
import calendar
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ingest import senate_office_pilot as offices  # noqa: E402

PILOT_PATH = ROOT / 'data' / 'snapshots' / 'senate-office-pilot.json'
OUTPUT_PATH = ROOT / 'data' / 'snapshots' / 'senate-cost.json'
EXERCISE_DIR = ROOT / 'data' / 'raw' / 'senado-exercicios'
DB_PATH = ROOT / 'data' / 'na-lupa.sqlite3'
EXERCISE_URL = 'https://legis.senado.leg.br/dadosabertos/senador/{code}/mandatos.json'


def _as_list(value):
    return value if isinstance(value, list) else [value] if value else []


def exercise_intervals(payload) -> list[tuple[date, date | None]]:
    """Intervalos de exercício de todos os mandatos publicados (fim ausente: sem término informado)."""
    parliamentarian = ((payload or {}).get('MandatoParlamentar') or {}).get('Parlamentar') or {}
    intervals = []
    for mandate in _as_list((parliamentarian.get('Mandatos') or {}).get('Mandato')):
        for exercise in _as_list((mandate.get('Exercicios') or {}).get('Exercicio')):
            start = exercise.get('DataInicio')
            if not start:
                raise ValueError('Exercício sem data de início')
            end = exercise.get('DataFim')
            intervals.append((date.fromisoformat(start[:10]), date.fromisoformat(end[:10]) if end else None))
    return intervals


def month_exercise(intervals, period: str) -> str:
    """'em_exercicio' se algum dia do mês está num intervalo; 'fora' se nenhum; sem histórico, 'desconhecido'."""
    if intervals is None:
        return 'desconhecido'
    year, month = int(period[:4]), int(period[5:])
    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    inside = any(start <= last and (end is None or end >= first) for start, end in intervals)
    return 'em_exercicio' if inside else 'fora'


def load_exercises(code: str, collect: bool) -> tuple[list | None, str | None]:
    """Histórico do cache local; com ``collect``, consulta a API e atualiza o cache."""
    cache = EXERCISE_DIR / f'{code}.json'
    if collect:
        request = Request(EXERCISE_URL.format(code=code), headers={'Accept': 'application/json', 'User-Agent': offices.USER_AGENT})
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
        EXERCISE_DIR.mkdir(parents=True, exist_ok=True)
        offices.write_atomic(cache, {'fetchedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(), 'payload': payload})
    if not cache.exists():
        return None, None
    stored = json.loads(cache.read_text(encoding='utf-8'))
    try:
        return exercise_intervals(stored['payload']), stored.get('fetchedAt')
    except (ValueError, KeyError, TypeError):
        return None, stored.get('fetchedAt')


def _reason(month, exercise, part):
    """Motivo de ausência de uma parte (remuneração ou gabinete) num mês do arquivo."""
    if month['subsidyReason'] == 'lotacao_ausente':
        return 'fora_do_exercicio' if exercise == 'fora' else 'nao_identificado'
    if part == 'remuneration':
        return {'sem_linha_no_gabinete': 'outra_lotacao', 'mais_de_uma_linha': 'lotacao_compartilhada'}.get(month['subsidyReason'])
    return 'menos_de_3' if month['office']['suppressed'] else None


def build(pilot, people, exercises, fetched_at):
    """``people``: {id: nome}; ``exercises``: {id: intervalos ou None}."""
    periods = [source['competence'] for source in pilot['sources']]
    by_id = {s['id']: s for s in pilot['senators']}
    records = {}
    for identifier in sorted(people, key=lambda i: int(i.split(':')[1])):
        intervals = exercises.get(identifier)
        senator = by_id.get(identifier)
        months = {}
        for index, period in enumerate(periods):
            exercise = month_exercise(intervals, period)
            if senator is None:
                no_office = 'fora_do_exercicio' if exercise == 'fora' else 'sem_lotacao_propria'
                months[period] = {'exercise': exercise, 'remunerationCents': None, 'remunerationReason': no_office,
                                  'officeCents': None, 'officeReason': no_office, 'officePeople': None}
                continue
            month = senator['months'][index]
            months[period] = {
                'exercise': exercise,
                'remunerationCents': month['subsidyGrossCents'],
                'remunerationReason': None if month['subsidyGrossCents'] is not None else _reason(month, exercise, 'remuneration'),
                'officeCents': month['office']['grossCents'],
                'officeReason': None if month['office']['grossCents'] is not None else _reason(month, exercise, 'office'),
                'officePeople': month['office']['people'] or None,
            }
            # Pagamento no próprio gabinete com o histórico dizendo fora do exercício: licença ou afastamento
            # (por exemplo, ministro(a) que optou pelo subsídio). O valor fica; o mês é marcado.
            if exercise == 'fora' and month['subsidyGrossCents'] is not None:
                months[period]['paidOutsideExercise'] = True
        records[identifier] = {'id': identifier, 'office': senator['office'] if senator else None,
                               'exerciseHistory': intervals is not None, 'exerciseFetchedAt': fetched_at.get(identifier),
                               'months': months}
    return {
        'schemaVersion': 1,
        'generatedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'periodStart': periods[0], 'periodEnd': periods[-1],
        'sources': [{'competence': s['competence'], 'url': s['url'], 'sourceUpdatedAt': s['sourceUpdatedAt']} for s in pilot['sources']],
        'exerciseSource': EXERCISE_URL.format(code='{codigo}'),
        'rules': {**pilot['rules'], 'exercise': 'Mês em exercício quando algum dia do mês está num intervalo de exercício publicado pelo Senado.'},
        'profiles': records,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--collect', action='store_true', help='consulta o histórico de exercício na API do Senado')
    parser.add_argument('--output', type=Path, default=OUTPUT_PATH)
    args = parser.parse_args(argv)
    pilot = json.loads(PILOT_PATH.read_text(encoding='utf-8'))
    db = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    people = dict(db.execute("SELECT id,name FROM authorities WHERE id LIKE 'senado:%' AND role='senador'"))
    exercises, fetched_at, failures = {}, {}, []
    for identifier in people:
        try:
            exercises[identifier], fetched_at[identifier] = load_exercises(identifier.split(':')[1], args.collect)
        except OSError as error:
            failures.append(identifier)
            exercises[identifier], fetched_at[identifier] = load_exercises(identifier.split(':')[1], False)
            print(f'{identifier}: histórico de exercício indisponível ({type(error).__name__}); usa o cache, se houver')
    payload = build(pilot, people, exercises, fetched_at)
    offices.write_atomic(args.output, payload)
    without = sum(1 for v in exercises.values() if v is None)
    print(f'{len(payload["profiles"])} senadores(as), {len(pilot["sources"])} meses; sem histórico de exercício: {without}')
    return 1 if failures and args.collect and without else 0


if __name__ == '__main__':
    raise SystemExit(main())
