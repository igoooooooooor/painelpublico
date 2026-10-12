"""Localiza o relatório nominal oficial (ideVotacao) de votações do inventário do Placar.

Ferramenta de revisão: não grava revisões nem altera o catálogo. Os números ``ideVotacao`` crescem com
o tempo; relatórios já baixados no cache do inventário dão pares (data, número) que delimitam a busca.
Para cada votação, procura na faixa um relatório da mesma data com o mesmo placar Sim e Não e encerrado
antes do registro da API (com a folga usual). Falha fechado: sem candidato ou com mais de um, a votação
fica sem relatório e a saída diz por quê.

    python3 -m ingest.chamber_vote_report_locator 2461217-7 2480642-7
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from ingest.chamber_vote_inventory import API_BASE, CollectionError, _load
from ingest.chamber_vote_report import parse_roll_call
from ingest.chamber_vote_rules import _recorded_partial_tally
from ingest.chamber_votes import ROOT, _registered_after_report, _source_bytes, request_bytes

REPORT_URL = 'https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?ideVotacao={}'
SEARCH_WIDTH = 80


def _number(url):
    match = re.search(r'[?&]ideVotacao=(\d+)', url or '')
    return int(match.group(1)) if match else None


def known_reports(root):
    """Pares (data, ideVotacao) dos relatórios nominais já guardados no cache do inventário."""
    pairs = []
    for meta in (root / 'data' / 'raw').glob('chamber-vote-*/**/reports/*.meta.json'):
        try:
            number = _number(json.loads(meta.read_text()).get('sourceUrl'))
            report = parse_roll_call(meta.with_name(meta.name.replace('.meta.json', '.html')).read_bytes())
        except (OSError, ValueError, CollectionError):
            continue
        if number is not None:
            pairs.append((report['date'], number))
    return sorted(set(pairs))


def locate(entry, record, pairs, *, cache, collect, request=request_bytes, width=SEARCH_WIDTH):
    """Relatório único da votação: {'number', 'url', 'report'} ou {'error'}."""
    day, tally = entry['date'], _recorded_partial_tally(record.get('descricao'))
    if tally.get('yes') is None or tally.get('no') is None:
        return {'error': 'a API não publica placar Sim e Não'}
    lower = max((number for when, number in pairs if when < day), default=None)
    upper = min((number for when, number in pairs if when > day), default=None)
    same_day = sorted(number for when, number in pairs if when == day)
    if same_day:
        start, stop = same_day[0] - width, same_day[-1] + width
    elif lower is not None and upper is not None:
        start, stop = lower + 1, min(upper - 1, lower + 4 * width)
    else:
        return {'error': 'sem relatórios conhecidos para delimitar a busca'}
    start, stop = max(start, (lower or 0) + 1), min(stop, (upper or stop + 1) - 1)
    matches = []
    for number in range(start, stop + 1):
        url = REPORT_URL.format(number)
        try:
            content, _ = _source_bytes(url, cache / f'{number}.html', collect=collect, refresh=False, request=request)
            report = parse_roll_call(content)
        except CollectionError:
            continue
        if (report['date'] == day and report['tally'].get('yes') == tally['yes']
                and report['tally'].get('no') == tally['no']
                and _registered_after_report(report['endedAt'], record.get('dataHoraRegistro'))):
            matches.append({'number': number, 'url': url, 'report': report})
    if len(matches) != 1:
        return {'error': f'{len(matches)} relatórios compatíveis entre {start} e {stop}'}
    return matches[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('ids', nargs='+', help='IDs de votação do inventário (ex.: 2461217-7)')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--collect', action='store_true', help='baixa relatórios que ainda não estão no cache')
    args = parser.parse_args(argv)
    entries, caches = {}, {}
    for path in sorted((args.root / 'data' / 'reviews').glob('chamber-vote-inventory-*.json')):
        inventory = json.loads(path.read_text())
        cache = (args.root / 'data' / 'raw' / 'chamber-vote-inventory'
                 / f"{inventory['period']['start']}_{inventory['period']['end']}")
        for entry in inventory['entries']:
            entries[entry['id']], caches[entry['id']] = entry, cache
    pairs = known_reports(args.root)
    result = {}
    for identifier in args.ids:
        entry = entries.get(identifier)
        if entry is None:
            result[identifier] = {'error': 'fora do inventário'}
            continue
        try:
            payload, _ = _load(f'{API_BASE}/votacoes/{identifier}', caches[identifier] / 'details' / f'{identifier}.json',
                               collect=args.collect, refresh=False, request=request_bytes, detail=True)
        except CollectionError as error:
            result[identifier] = {'error': str(error)}
            continue
        record = payload['dados']
        found = locate(entry, record, pairs, cache=args.root / 'data' / 'raw' / 'chamber-vote-reports',
                       collect=args.collect)
        if 'report' in found:
            report = found['report']
            found = {'ideVotacao': found['number'], 'rollCall': found['url'], 'date': report['date'],
                     'proposition': report['proposition'], 'object': report['object'],
                     'endedAt': report['endedAt'], 'tally': report['tally']}
        result[identifier] = found
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if all('error' not in value for value in result.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
