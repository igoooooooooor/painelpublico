"""Inventário auditável do Placar; não altera snapshots ou telas em uso.

Execução offline por padrão. A lista completa vem do órgão Plenário (180);
detalhes e votos individuais são uma amostra explícita para validar as regras.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.chamber_vote_rules import RULE_VERSION, classify_vote
from ingest.project_status import _atomic_bytes, _json_bytes, cached_json, request_bytes, utc_now

API_BASE = 'https://dadosabertos.camara.leg.br/api/v2'
LIST_ENDPOINT = f'{API_BASE}/orgaos/180/votacoes'
GUIDE_URL = 'https://dadosabertos.camara.leg.br/howtouse/2020-02-07-dados-votacoes.html'


class CollectionError(ValueError):
    """A fonte não permite afirmar que o inventário está completo."""


def _official_url(url, path):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname != 'dadosabertos.camara.leg.br'
            or parts.username or parts.password or parts.port not in (None, 443)
            or parts.path != path or parts.fragment):
        raise CollectionError('Link de paginação fora do endpoint oficial esperado.')
    return url


def _load(url, path, *, collect, refresh, request, detail=False):
    def validate(payload):
        return (isinstance(payload, dict)
                and isinstance(payload.get('dados'), dict if detail else list)
                and isinstance(payload.get('links'), list))

    payload, metadata, error = cached_json(
        url, path, collect=collect, refresh=refresh, request=request, validate=validate)
    if payload is None or error:
        raise CollectionError(f'{url}: {error or "Cache ausente."}')
    return payload, metadata


def _page_number(url):
    try:
        page = int(parse_qs(urlsplit(url).query).get('pagina', ['1'])[0])
        if page < 1:
            raise ValueError
        return page
    except (ValueError, TypeError):
        raise CollectionError('Número de página inválido na fonte.') from None


def _paged(url, cache, *, collect, refresh, request):
    endpoint_path = urlsplit(url).path
    seen_urls, rows, sources = set(), [], []
    expected_last = 1
    while url:
        _official_url(url, endpoint_path)
        if url in seen_urls:
            raise CollectionError('A paginação repetiu uma página.')
        seen_urls.add(url)
        payload, metadata = _load(url, cache / f'page-{len(seen_urls)}.json',
                                  collect=collect, refresh=refresh, request=request)
        if any(not isinstance(row, dict) for row in payload['dados']):
            raise CollectionError('A lista contém um registro inválido.')
        rows.extend(payload['dados'])
        sources.append(metadata)
        links = payload['links']
        next_links = [link.get('href') for link in links
                      if isinstance(link, dict) and link.get('rel') == 'next']
        last_links = [link.get('href') for link in links
                      if isinstance(link, dict) and link.get('rel') == 'last']
        if len(next_links) > 1 or len(last_links) > 1:
            raise CollectionError('A fonte retornou links de paginação conflitantes.')
        if last_links:
            if not isinstance(last_links[0], str) or not last_links[0]:
                raise CollectionError('Link da última página inválido.')
            last_url = _official_url(urljoin(url, last_links[0]), endpoint_path)
            expected_last = max(expected_last, _page_number(last_url))
        if not next_links and _page_number(url) < expected_last:
            raise CollectionError('Falta a próxima página antes da última página anunciada.')
        if next_links:
            if not isinstance(next_links[0], str) or not next_links[0]:
                raise CollectionError('Link da próxima página inválido.')
            next_url = _official_url(urljoin(url, next_links[0]), endpoint_path)
            if _page_number(next_url) != _page_number(url) + 1:
                raise CollectionError('A paginação pulou ou repetiu um número de página.')
            url = next_url
        else:
            url = None
    return rows, sources


def _unique_votes(rows, start, through):
    unique, duplicates = {}, 0
    for row in rows:
        identifier = str(row.get('id', ''))
        if not re.fullmatch(r'[0-9]+-[0-9]+', identifier):
            raise CollectionError('Votação sem identificador oficial válido.')
        try:
            occurred = date.fromisoformat(row.get('data', ''))
        except (ValueError, TypeError):
            raise CollectionError(f'{identifier}: data de ocorrência ausente ou inválida.') from None
        if not start <= occurred <= through or row.get('siglaOrgao') != 'PLEN':
            raise CollectionError(f'{identifier}: registro fora do período ou do Plenário solicitado.')
        if identifier in unique:
            if unique[identifier] != row:
                raise CollectionError(f'{identifier}: registros duplicados conflitantes.')
            duplicates += 1
        unique[identifier] = row
    return sorted(unique.values(), key=lambda row: (row['data'], row.get('dataHoraRegistro', ''), row['id']),
                  reverse=True), duplicates


def _participant_audit(rows, tally):
    people, invalid, duplicates = {}, 0, 0
    for row in rows:
        person = row.get('deputado_')
        identifier = str(person.get('id', '')) if isinstance(person, dict) else ''
        choice = row.get('tipoVoto')
        if not identifier.isdigit() or not isinstance(choice, str) or not choice:
            invalid += 1
            continue
        if identifier in people:
            if people[identifier] != choice:
                raise CollectionError('A fonte contém votos conflitantes para a mesma pessoa.')
            duplicates += 1
        people[identifier] = choice
    counts = Counter(people.values())
    checks = {key: counts[label] == tally[key] if tally and tally.get(key) is not None else None
              for key, label in [('yes', 'Sim'), ('no', 'Não'), ('abstention', 'Abstenção')]}
    observed_checks = [value for value in checks.values() if value is not None]
    return {'recordCount': len(rows), 'personCount': len(people), 'duplicateCount': duplicates,
            'invalidCount': invalid, 'choices': dict(sorted(counts.items())), 'tallyChecks': checks,
            'consistent': not invalid and bool(observed_checks) and all(observed_checks),
            'methodWarning': 'Linhas individuais e placar não comprovam sozinhos o método nominal; conferir a fonte.'}


def collect_inventory(*, root=ROOT, start=date(2026, 1, 1), through=None, collect=False,
                      refresh=False, detail_limit=40, participant_limit=10, request=request_bytes):
    through = through or date.today()
    if (start.year != through.year or start > through or detail_limit < 0 or participant_limit < 0):
        raise ValueError('Período ou limites inválidos para o inventário anual.')
    cache = Path(root) / 'data' / 'raw' / 'chamber-vote-inventory' / f'{start}_{through}'
    query = urlencode({'dataInicio': start.isoformat(), 'dataFim': through.isoformat(),
                       'itens': 100, 'ordem': 'ASC', 'ordenarPor': 'dataHoraRegistro'})
    source_url = f'{LIST_ENDPOINT}?{query}'
    rows, list_sources = _paged(source_url, cache / 'list', collect=collect, refresh=refresh, request=request)
    rows, duplicate_count = _unique_votes(rows, start, through)
    # Placar explícito primeiro; dentro de cada grupo, data mais recente primeiro.
    # Isto escolhe a amostra de conferência, nunca o catálogo a publicar.
    rows.sort(key=lambda row: classify_vote(row)['recordedTally'] is None)
    entries, detail_count, participant_count = [], 0, 0
    for row in rows:
        classification = classify_vote(row)
        identifier = row['id']
        detail, detail_source, participant_source, audit = None, None, None, None
        errors = []
        inspect = classification['candidate'] or (classification['category'] == 'unknown'
                                                  and classification['recordedTally'] is not None)
        if inspect and detail_count < detail_limit:
            detail_count += 1
            detail_url = f'{API_BASE}/votacoes/{identifier}'
            try:
                payload, detail_source = _load(detail_url, cache / 'details' / f'{identifier}.json',
                                              collect=collect, refresh=refresh, request=request, detail=True)
                detail = payload['dados']
                if (str(detail.get('id')) != identifier or detail.get('siglaOrgao') != 'PLEN'
                        or detail.get('data') != row['data']):
                    raise CollectionError('Detalhe não corresponde à votação da lista.')
                classification = classify_vote(detail)
            except CollectionError as error:
                detail = None
                errors.append(str(error))
        if detail and classification['candidate'] and participant_count < participant_limit:
            participant_count += 1
            vote_url = f'{API_BASE}/votacoes/{identifier}/votos'
            try:
                participants, participant_source = _paged(vote_url, cache / 'participants' / identifier,
                                                         collect=collect, refresh=refresh, request=request)
                audit = _participant_audit(participants, classification['recordedTally'])
            except CollectionError as error:
                errors.append(str(error))
        observed = detail or row
        issues = []
        if classification['candidate']:
            if not detail:
                issues.append('Detalhe ainda não conferido na amostra.')
            if classification['method'] == 'unknown':
                issues.append('Método de votação não confirmado pelo texto da API.')
            if len(classification['targetPropositions']) != 1:
                issues.append('Proposição de referência não identificada de forma única.')
            if audit is None:
                issues.append('Votos individuais ainda não conferidos na amostra.')
            elif not audit['consistent']:
                issues.append('Placar e votos individuais não foram reconciliados.')
        entries.append({'id': identifier, 'date': row['data'], 'registeredAt': observed.get('dataHoraRegistro'),
                        'description': observed.get('descricao'), 'approval': observed.get('aprovacao'),
                        'sourceUrl': f'{API_BASE}/votacoes/{identifier}', **classification,
                        'detailCollected': detail is not None, 'detailSource': detail_source,
                        'participants': audit, 'participantSources': participant_source,
                        'errors': errors, 'reviewIssues': issues, 'publicationStatus': 'needs_review'})
    entries.sort(key=lambda entry: (entry['date'], entry['registeredAt'] or '', entry['id']), reverse=True)
    counts = Counter(entry['category'] for entry in entries)
    return {'schemaVersion': 1, 'ruleVersion': RULE_VERSION, 'generatedAt': utc_now(),
            'period': {'start': start.isoformat(), 'end': through.isoformat()},
            'scope': 'Câmara · Plenário · inventário de fontes; sem publicação automática',
            'guideUrl': GUIDE_URL, 'listSourceUrl': source_url, 'listSources': list_sources,
            'listComplete': True, 'listPageCount': len(list_sources), 'voteCount': len(entries),
            'duplicateCount': duplicate_count, 'categoryCounts': dict(sorted(counts.items())),
            'candidateCount': sum(entry['candidate'] for entry in entries),
            'detailLimit': detail_limit, 'detailAttemptCount': detail_count,
            'sampleOrder': 'placar explícito primeiro; dentro de cada grupo, data mais recente primeiro',
            'detailCount': sum(entry['detailCollected'] for entry in entries),
            'participantLimit': participant_limit, 'participantAttemptCount': participant_count,
            'participantAuditCount': sum(entry['participants'] is not None for entry in entries),
            'methodCounts': dict(sorted(Counter(entry['method'] for entry in entries).items())),
            'errorCount': sum(bool(entry['errors']) for entry in entries), 'entries': entries}


def _table_text(value):
    return str(value or '').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def render_report(inventory):
    period = inventory['period']
    lines = ['# Placar — inventário de fontes da Câmara', '',
             f'Período de ocorrência: {period["start"]} a {period["end"]}.',
             f'Lista completa da API: {inventory["voteCount"]} votações em {inventory["listPageCount"]} páginas.',
             f'Regra: `{inventory["ruleVersion"]}`. Gerado em {inventory["generatedAt"]}.', '',
             'Este é um levantamento. Candidato não significa votação elegível ou resumo aprovado.',
             'Lista completa significa toda a paginação retornada pela API, não garantia de registro de todas as decisões.',
             'A data do registro é guardada separadamente da data de ocorrência.', '',
             '## Classificação provisória', '', '| Categoria | Votações |', '| --- | ---: |']
    lines.extend(f'| {category} | {count} |' for category, count in inventory['categoryCounts'].items())
    lines.extend(['', f'Candidatos provisórios: {inventory["candidateCount"]}.',
                  f'Detalhes coletados: {inventory["detailCount"]} (limite {inventory["detailLimit"]}).',
                  f'Votações com votos individuais conferidos: {inventory["participantAuditCount"]} '
                  f'(limite {inventory["participantLimit"]}).', f'Registros com falha: {inventory["errorCount"]}.', '',
                  'O método fica desconhecido quando a fonte não o declara explicitamente. '
                  'Contagens ou linhas individuais não transformam uma votação simbólica em nominal.', '',
                  '## Registros', '', '| Data | ID e fonte | Categoria | Candidato | Método | Descrição oficial |',
                  '| --- | --- | --- | --- | --- | --- |'])
    for entry in inventory['entries']:
        lines.append(f'| {entry["date"]} | [{entry["id"]}]({entry["sourceUrl"]}) | '
                     f'{entry["category"]} | {"sim" if entry["candidate"] else "não"} | '
                     f'{entry["method"]} | {_table_text(entry["description"])} |')
    lines.extend(['', f'[Lista oficial]({inventory["listSourceUrl"]}). [Limitações oficiais]({GUIDE_URL}).', ''])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, default=2026)
    parser.add_argument('--through', type=date.fromisoformat, default=date.today())
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--detail-limit', type=int, default=40)
    parser.add_argument('--participant-limit', type=int, default=10)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        inventory = collect_inventory(root=args.root, start=date(args.year, 1, 1), through=args.through,
                                      collect=args.collect, refresh=args.refresh, detail_limit=args.detail_limit,
                                      participant_limit=args.participant_limit)
    except (CollectionError, ValueError) as error:
        parser.exit(1, f'Inventário não gravado; relatório anterior preservado: {error}\n')
    output = args.root / 'data' / 'reviews' / f'chamber-vote-inventory-{args.through}.json'
    _atomic_bytes(output, _json_bytes(inventory))
    _atomic_bytes(output.with_suffix('.md'), render_report(inventory).encode('utf-8'))
    summary = {key: inventory[key] for key in ('voteCount', 'listPageCount', 'categoryCounts', 'candidateCount',
                                              'detailCount', 'participantAuditCount', 'methodCounts', 'errorCount')}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(output.relative_to(args.root))


if __name__ == '__main__':
    main()
