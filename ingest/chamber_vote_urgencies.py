"""Pedidos de urgência (art. 155 do Regimento) ligados a uma votação do texto principal já publicada.

O voto na urgência aprova ou rejeita o pedido para acelerar a tramitação, não o conteúdo do projeto.
Cada pedido vem de uma revisão editorial local e só é publicado depois de conferido, falhando fechado:

- o requerimento é a proposição do próprio ID da votação (REQ), com o número que o relatório nominal mostra;
- o projeto-alvo é o único projeto afetado no registro da API, é o da votação principal ligada e aparece
  no objeto do relatório nominal;
- a votação principal ligada é a primeira deliberação do texto principal desse projeto depois do pedido,
  sem outra no meio (inclusive as que não estão no catálogo);
- placar, resultado e votos individuais seguem as mesmas conferências das decisões sobre trechos.
"""
from __future__ import annotations

import re
import unicodedata

from ingest.chamber_vote_inventory import API_BASE, CollectionError, _load
from ingest.chamber_vote_segments import api_outcome, verify_nominal

URGENCY_OUTCOMES = {'approved', 'rejected'}
URGENCY_FIELDS = ('title', 'summary', 'decisionLabel', 'yesMeaning', 'noMeaning')
# Maioria absoluta da composição da Câmara, exigida pelo art. 155 do Regimento Interno.
URGENCY_QUORUM = 257
TARGET_TYPES = {'PL', 'PLP', 'PEC', 'MPV', 'PDL'}
REQUEST_LABEL = re.compile(r'REQ (\d+)/(\d{4})')
FICHA = 'https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={}'


def _folded(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    return ''.join(character for character in text if not unicodedata.combining(character)).casefold()


def cites(text, number, year):
    """O texto cita a proposição pelo número e ano ("PL Nº 1.958/2021", "nº 177, de 2023")."""
    for found_number, found_year in re.findall(r'(\d[\d.]*)\s*(?:/|,?\s*de\s+)\s*(\d{4})', _folded(text)):
        if int(found_number.replace('.', '')) == number and int(found_year) == year:
            return True
    return False


def _proposition_id(url):
    match = re.search(r'[?&]idProposicao=(\d+)', url or '')
    return int(match.group(1)) if match else None


def build_urgencies(items, inventory_entries, reviews, *, taken, cache, collect, refresh, request):
    """Valida as revisões e pendura cada pedido na votação principal; devolve os detalhes novos."""
    from ingest.chamber_votes import (VOTE_ID as vote_id, _official_source as official_source,
                                      _valid_review_date as valid_date)
    if not isinstance(reviews, list):
        raise CollectionError('A revisão de urgências deve ser uma lista.')
    cache_for = cache if callable(cache) else (lambda _identifier: cache)
    parents = {item['id']: item for item in items}
    details, seen = {}, set()
    for review in reviews:
        identifier = review.get('id') if isinstance(review, dict) else None
        if (not isinstance(identifier, str) or not vote_id.fullmatch(identifier) or identifier in seen
                or identifier in parents or identifier in taken):
            raise CollectionError('Revisão de urgência sem ID válido, repetida ou igual a outra decisão publicada.')
        seen.add(identifier)
        if review.get('status') != 'confirmed':
            if review.get('status') not in ('pending', 'excluded') or not review.get('reason'):
                raise CollectionError(f'{identifier}: pedido de urgência não confirmado precisa de motivo.')
            continue
        evidence, sources, request_ref = review.get('evidence'), review.get('sources'), review.get('request')
        if (review.get('outcome') not in URGENCY_OUTCOMES or not valid_date(review.get('reviewedAt'))
                or any(not isinstance(review.get(field), str) or not review[field].strip() for field in URGENCY_FIELDS)
                or not isinstance(review.get('reportObject'), str) or not review['reportObject'].strip()
                or not isinstance(request_ref, dict) or not isinstance(request_ref.get('label'), str)
                or not REQUEST_LABEL.fullmatch(request_ref['label'])
                or not isinstance(evidence, dict) or any(not evidence.get(field) for field in ('method', 'object', 'text'))
                or not isinstance(sources, dict)):
            raise CollectionError(f'{identifier}: revisão de urgência incompleta.')
        notes = review.get('dataNotes', [])
        if not isinstance(notes, list) or len(notes) > 4 or any(not isinstance(note, str) or not note.strip() for note in notes):
            raise CollectionError(f'{identifier}: notas de dados inválidas.')

        parent = parents.get(review.get('parentId'))
        entry = inventory_entries.get(identifier)
        if parent is None or entry is None or entry['date'] > parent['date']:
            raise CollectionError(f'{identifier}: pedido sem votação principal publicada depois dele.')
        targets = {_proposition_id(parent['sources'].get(key)) for key in ('proposition', 'referenceProposition')} - {None}
        safe_sources = {key: official_source(sources.get(key)) for key in ('rollCall', 'request', 'proposition')}
        if safe_sources['proposition'] != parent['sources']['proposition']:
            raise CollectionError(f'{identifier}: ficha do projeto diferente da votação principal ligada.')

        # A votação principal ligada é a primeira deliberação do texto principal depois do pedido.
        parent_entry = inventory_entries.get(parent['id'])
        registered = str(entry.get('registeredAt') or '')
        if parent_entry is None or not registered or not registered < str(parent_entry.get('registeredAt') or ''):
            raise CollectionError(f'{identifier}: pedido não é anterior à votação principal ligada.')
        between = [other['id'] for other in inventory_entries.values()
                   if other.get('candidate') and other['id'] != parent['id']
                   and int(other['id'].split('-')[0]) in targets
                   and registered < str(other.get('registeredAt') or '') < parent_entry['registeredAt']]
        if between:
            raise CollectionError(f'{identifier}: outra deliberação do texto principal fica entre o pedido e a votação ligada.')

        urgency_cache = cache_for(identifier)
        url = f'{API_BASE}/votacoes/{identifier}'
        payload, detail_source = _load(url, urgency_cache / 'details' / f'{identifier}.json',
                                       collect=collect, refresh=refresh, request=request, detail=True)
        record = payload['dados']
        description = _folded(record.get('descricao'))
        if (record.get('id') != identifier or record.get('data') != entry['date']
                or not re.search(r'requerimento de urgencia', description) or not re.search(r'art\.?\s*155', description)):
            raise CollectionError(f'{identifier}: registro da API não confirma um pedido de urgência do art. 155.')
        if review['outcome'] != api_outcome(record.get('descricao'), record.get('aprovacao')):
            raise CollectionError(f'{identifier}: resultado da revisão diverge do registro da API.')

        # O requerimento é a proposição do próprio ID da votação.
        prefix = int(identifier.split('-')[0])
        proposition_payload, request_source = _load(
            f'{API_BASE}/proposicoes/{prefix}', urgency_cache / 'propositions' / f'{prefix}.json',
            collect=collect, refresh=refresh, request=request, detail=True)
        proposition = proposition_payload['dados']
        number, year = (int(value) for value in REQUEST_LABEL.fullmatch(request_ref['label']).groups())
        if (proposition.get('id') != prefix or proposition.get('siglaTipo') != 'REQ'
                or (proposition.get('numero'), proposition.get('ano')) != (number, year)
                or 'urgencia' not in _folded(proposition.get('ementa'))
                or safe_sources['request'] != FICHA.format(prefix)):
            raise CollectionError(f'{identifier}: requerimento não confirma o pedido de urgência revisado.')

        affected = [item for item in record.get('proposicoesAfetadas') or []
                    if isinstance(item, dict) and item.get('siglaTipo') in TARGET_TYPES]
        if len(affected) != 1 or affected[0].get('id') not in targets:
            raise CollectionError(f'{identifier}: projeto afetado diferente do projeto da votação principal.')
        target = affected[0]
        if not cites(review['reportObject'], target.get('numero'), target.get('ano')):
            raise CollectionError(f'{identifier}: objeto do relatório não cita o projeto-alvo.')

        allowed = [{'type': 'REQ', 'number': number, 'year': year}]
        _report, tally, notes, detail = verify_nominal(
            identifier, record, entry, review, safe_sources['rollCall'], allowed, notes, detail_source,
            cache=urgency_cache, collect=collect, refresh=refresh, request=request)
        if review['outcome'] == 'approved' and (tally['yes'] or 0) < URGENCY_QUORUM:
            raise CollectionError(f'{identifier}: urgência aprovada com menos Sim que o quórum do art. 155.')
        detail['sourceMetadata']['request'] = request_source

        urgency = {'id': identifier, 'date': entry['date'],
                   'request': {'label': request_ref['label'], 'url': safe_sources['request']},
                   **{field: review[field] for field in URGENCY_FIELDS}, 'outcome': review['outcome'],
                   'quorum': URGENCY_QUORUM, 'tally': tally,
                   'sources': {'vote': url, **safe_sources}, 'reviewedAt': review['reviewedAt'],
                   'registeredAt': registered, **({'dataNotes': notes} if notes else {})}
        parent.setdefault('urgencies', []).append(urgency)
        details[identifier] = detail
    for item in items:
        if 'urgencies' in item:
            item['urgencies'].sort(key=lambda urgency: (urgency.pop('registeredAt'), urgency['id']))
    return details
