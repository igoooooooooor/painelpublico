"""Build the reviewed voting catalogue and separate roll-call snapshots.

Reviews are local editorial inputs, never an automatic publication decision.
Offline by default; downloads and source checksums stay under data/.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from urllib.parse import urlsplit

from ingest.chamber_vote_inventory import API_BASE, ROOT, CollectionError, _load, _paged
from ingest.chamber_vote_rules import classify_vote
from ingest.project_status import _atomic_bytes, _json_bytes, _valid_date, request_bytes, utc_now

VOTE_ID = re.compile(r'[0-9]+-[0-9]+')
CHOICES = {'Sim': 'Sim', 'Não': 'Não', 'Abstenção': 'Abstenção',
           'Obstrução': 'Obstrução', 'Artigo 17': 'Presidiu', 'Presidiu': 'Presidiu'}
REVIEW_FIELDS = ('title', 'summary', 'decisionLabel', 'yesMeaning', 'noMeaning')


def _official_source(value, *, nullable=False):
    if nullable and value is None:
        return None
    parts = urlsplit(value) if isinstance(value, str) else None
    if (parts is None or parts.scheme != 'https' or parts.hostname not in
            {'www.camara.leg.br', 'camara.leg.br', 'dadosabertos.camara.leg.br'}
            or parts.username or parts.password or parts.port not in (None, 443)):
        raise CollectionError('A revisão precisa de um link oficial da Câmara.')
    return value


def _source_bytes(url, path, *, collect, refresh, request):
    """Cache a non-JSON official source with the same provenance as API caches."""
    previous = None
    try:
        content = path.read_bytes()
        metadata = json.loads(path.with_suffix('.meta.json').read_text())
        if (metadata.get('sourceUrl') == url and _valid_date(metadata.get('consultadoEm'))
                and metadata.get('sha256') == hashlib.sha256(content).hexdigest()
                and _nominal_report(content)):
            previous = (content, metadata)
    except (OSError, ValueError, AttributeError):
        pass
    if previous and not refresh:
        return previous
    if not collect:
        if previous:
            return previous
        raise CollectionError(f'{url}: fonte nominal ainda não coletada.')
    try:
        content = request(url)
    except (OSError, TimeoutError) as error:
        raise CollectionError(f'{url}: falha na fonte nominal; saída anterior preservada.') from error
    if not content:
        raise CollectionError(f'{url}: fonte nominal vazia.')
    if not _nominal_report(content):
        raise CollectionError(f'{url}: relatório não confirma método nominal eletrônico; fonte anterior preservada.')
    metadata = {'sourceUrl': url, 'consultadoEm': utc_now(),
                'sha256': hashlib.sha256(content).hexdigest()}
    _atomic_bytes(path, content)
    _atomic_bytes(path.with_suffix('.meta.json'), _json_bytes(metadata))
    return content, metadata


def _nominal_report(content):
    for encoding in ('utf-8', 'latin-1'):
        text = unescape(content.decode(encoding, errors='replace'))
        text = re.sub(r'<[^>]+>', ' ', text)
        text = ''.join(character for character in unicodedata.normalize('NFKD', text)
                       if not unicodedata.combining(character)).casefold()
        if re.search(r'nominal\s+eletronica', text):
            return True
    return False


def normalize_participants(rows, tally):
    people = {}
    for row in rows:
        person = row.get('deputado_')
        identifier = str(person.get('id', '')) if isinstance(person, dict) else ''
        choice = CHOICES.get(str(row.get('tipoVoto', '')).strip())
        if (not identifier.isdigit() or not choice or not person.get('nome')
                or not re.fullmatch(r'[A-Z]{2}', str(person.get('siglaUf', '')))):
            raise CollectionError('Voto individual sem pessoa, UF ou escolha reconhecida.')
        participant = {'id': f'camara:{identifier}', 'name': person['nome'],
                       'party': person.get('siglaPartido') or '', 'uf': person['siglaUf'], 'vote': choice}
        if identifier in people and people[identifier] != participant:
            raise CollectionError('Votos individuais duplicados conflitantes.')
        people[identifier] = participant
    counts = Counter(person['vote'] for person in people.values())
    for key, choice in (('yes', 'Sim'), ('no', 'Não'), ('abstention', 'Abstenção')):
        if tally.get(key) is not None and counts[choice] != tally[key]:
            raise CollectionError(f'Placar divergente dos votos individuais: {key}.')
    if tally.get('total') is not None and sum(counts[choice] for choice in ('Sim', 'Não', 'Abstenção')) != tally['total']:
        raise CollectionError('Total do placar divergente dos votos individuais.')
    if not people:
        raise CollectionError('A lista nominal está vazia.')
    parties = defaultdict(lambda: {'yes': 0, 'no': 0, 'other': 0})
    for participant in people.values():
        key = {'Sim': 'yes', 'Não': 'no'}.get(participant['vote'], 'other')
        parties[participant['party']][key] += 1
    return (sorted(people.values(), key=lambda person: (person['name'].casefold(), person['id'])),
            [{'party': party, **counts} for party, counts in sorted(parties.items())])


def build_catalogue(inventory, reviews, *, root=ROOT, collect=False, refresh=False, request=request_bytes):
    if not isinstance(inventory, dict) or inventory.get('listComplete') is not True:
        raise CollectionError('O catálogo exige o inventário completo da API.')
    if not isinstance(reviews, list):
        raise CollectionError('A revisão deve ser uma lista.')
    period = inventory['period']
    start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end'])
    cache = root / 'data' / 'raw' / 'chamber-vote-inventory' / f'{start}_{end}'
    entries = {entry['id']: entry for entry in inventory['entries']}
    items, details, reviewed_ids = [], {}, set()
    for review in reviews:
        identifier = review.get('id') if isinstance(review, dict) else None
        if not isinstance(identifier, str) or not VOTE_ID.fullmatch(identifier) or identifier in reviewed_ids:
            raise CollectionError('Revisão sem ID válido ou com ID duplicado.')
        entry = entries.get(identifier)
        if entry is None or not entry.get('candidate'):
            raise CollectionError(f'{identifier}: decisão fora dos candidatos do inventário.')
        reviewed_ids.add(identifier)
        if review.get('status') == 'pending':
            if not review.get('reason'):
                raise CollectionError(f'{identifier}: pendência sem motivo.')
            continue
        if (review.get('status') != 'confirmed' or not review.get('reviewedAt')
                or any(not isinstance(review.get(field), str) or not review[field].strip() for field in REVIEW_FIELDS)
                or not isinstance(review.get('evidence'), dict)
                or any(not review['evidence'].get(field) for field in ('method', 'object', 'text'))):
            raise CollectionError(f'{identifier}: revisão incompleta.')
        sources = review.get('sources', {})
        safe_sources = {key: _official_source(sources.get(key), nullable=key == 'text')
                        for key in ('rollCall', 'text', 'decision', 'proposition')}
        url = f'{API_BASE}/votacoes/{identifier}'
        payload, detail_source = _load(url, cache / 'details' / f'{identifier}.json',
                                      collect=collect, refresh=refresh, request=request, detail=True)
        record = payload['dados']
        classification = classify_vote(record)
        targets, tally = classification['targetPropositions'], classification['recordedTally']
        if (record.get('id') != identifier or record.get('data') != entry['date']
                or not classification['candidate'] or len(targets) != 1 or not tally
                or tally['yes'] is None or tally['no'] is None):
            raise CollectionError(f'{identifier}: detalhe não confirma decisão, objeto de referência e placar.')
        target = targets[0]
        expected_proposition = f'https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={target["id"]}'
        if safe_sources['proposition'] != expected_proposition:
            raise CollectionError(f'{identifier}: ficha da revisão não corresponde à proposição de referência.')
        content, report_source = _source_bytes(safe_sources['rollCall'], cache / 'reports' / f'{identifier}.html',
                                               collect=collect, refresh=refresh, request=request)
        if not _nominal_report(content):
            raise CollectionError(f'{identifier}: relatório não confirma método nominal eletrônico.')
        rows, participant_sources = _paged(f'{url}/votos', cache / 'participants' / identifier,
                                           collect=collect, refresh=refresh, request=request)
        participants, party_totals = normalize_participants(rows, tally)
        theme_rows, theme_sources = _paged(f'{API_BASE}/proposicoes/{target["id"]}/temas',
                                           cache / 'themes' / str(target['id']),
                                           collect=collect, refresh=refresh, request=request)
        themes = {}
        for theme in theme_rows:
            if (not isinstance(theme.get('codTema'), int) or isinstance(theme['codTema'], bool)
                    or not isinstance(theme.get('tema'), str) or not theme['tema'].strip()):
                raise CollectionError(f'{identifier}: tema oficial inválido.')
            theme_id = f'chamber-theme-{theme["codTema"]}'
            if theme_id in themes and themes[theme_id]['label'] != theme['tema']:
                raise CollectionError(f'{identifier}: tema oficial conflitante.')
            themes[theme_id] = {'id': theme_id, 'label': theme['tema']}
        outcome = 'approved' if record.get('aprovacao') == 1 else 'not_approved' if record.get('aprovacao') == 0 else None
        # Rejection is stated only after explicit review of the result.
        if outcome == 'not_approved' and review.get('outcome') == 'rejected':
            outcome = 'rejected'
        items.append({'id': identifier, 'date': entry['date'],
                      'proposition': f'{target["siglaTipo"]} {target["numero"]}/{target["ano"]}',
                      'type': target['siglaTipo'], **{field: review[field] for field in REVIEW_FIELDS},
                      'outcome': outcome, 'tally': tally, 'themes': list(themes.values()),
                      'sources': {'vote': url, **safe_sources}, 'reviewedAt': review['reviewedAt']})
        details[identifier] = {'id': identifier, 'participants': participants, 'partyTotals': party_totals,
                               'sourceMetadata': {'vote': detail_source, 'rollCall': report_source,
                                                  'participants': participant_sources, 'themes': theme_sources}}
    items.sort(key=lambda item: (item['date'], item['id']), reverse=True)
    published = len(items)
    coverage = {'inventoryCount': inventory['voteCount'], 'candidateCount': inventory['candidateCount'],
                'reviewedCount': len(reviewed_ids), 'publishedCount': published,
                'pendingCount': inventory['candidateCount'] - published,
                'detail': f'{published} decisões nominais conferidas de {inventory["candidateCount"]} candidatos '
                          f'provisórios em {inventory["voteCount"]} registros da API. Recorte de {start.year}: texto principal '
                          'de PL, PLP e PEC no Plenário da Câmara. Os demais candidatos aguardam conferência; '
                          'o catálogo ainda não cobre todo o mandato. Temas da Câmara descrevem a proposição '
                          'de referência. Campo ausente não significa zero. O resultado é o desta decisão, '
                          'não a situação legal atual do projeto.'}
    details_version = hashlib.sha256(_json_bytes(details)).hexdigest()
    return {'schemaVersion': 1, 'generatedAt': utc_now(), 'period': period, 'detailsVersion': details_version,
            'coverage': coverage, 'items': items}, details


def write_catalogue(snapshot, details, directory):
    # Each immutable generation becomes visible only through the final atomic index switch.
    version = snapshot['detailsVersion']
    if version != hashlib.sha256(_json_bytes(details)).hexdigest():
        raise CollectionError('A geração dos detalhes não corresponde ao índice.')
    directory.mkdir(parents=True, exist_ok=True)
    details_directory = directory / 'chamber-vote-details'
    details_directory.mkdir(parents=True, exist_ok=True)
    generation = details_directory / version
    if generation.exists():
        if any((generation / f'{identifier}.json').read_bytes() != _json_bytes(detail)
               for identifier, detail in details.items()):
            raise CollectionError('Geração existente de detalhes divergente; saída anterior preservada.')
    else:
        with tempfile.TemporaryDirectory(prefix='.staging-', dir=details_directory) as temporary:
            staged = Path(temporary) / version
            staged.mkdir()
            for identifier, detail in details.items():
                _atomic_bytes(staged / f'{identifier}.json', _json_bytes(detail))
            os.replace(staged, generation)
    _atomic_bytes(directory / 'chamber-votes.json', _json_bytes(snapshot))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--through', type=date.fromisoformat, default=date.today())
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args(argv)
    inventory_path = args.root / 'data' / 'reviews' / f'chamber-vote-inventory-{args.through}.json'
    reviews_path = args.reviews or args.root / 'data' / 'reviews' / f'chamber-vote-reviews-{args.through}.json'
    try:
        inventory = json.loads(inventory_path.read_text())
        reviews = json.loads(reviews_path.read_text())
        snapshot, details = build_catalogue(inventory, reviews, root=args.root,
                                            collect=args.collect, refresh=args.refresh)
        write_catalogue(snapshot, details, args.root / 'data' / 'snapshots')
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Catálogo não gravado; saída anterior preservada: {error}\n')
    print(json.dumps(snapshot['coverage'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
