"""Pedidos de urgência (art. 155 do Regimento) ligados a uma votação do texto principal já publicada.

O voto na urgência aprova ou rejeita o pedido para acelerar a tramitação, não o conteúdo do projeto.
Cada pedido vem de uma revisão editorial local e só é publicado depois de conferido, falhando fechado:

- o requerimento é a proposição do próprio ID da votação (REQ), com o número que o relatório nominal mostra;
  a ementa não é conferida, porque às vezes só descreve o assunto do projeto;
- o projeto-alvo é o único projeto afetado no registro da API, é o da votação principal ligada e aparece,
  com a palavra urgência, no objeto do relatório nominal;
- a votação principal ligada é a primeira deliberação do texto principal desse projeto depois do pedido,
  sem outra no meio (inclusive as que não estão no catálogo), pela ordem dos relatórios nominais e com
  folga para o atraso do horário de registro da API;
- placar, resultado e votos individuais seguem as mesmas conferências das decisões sobre trechos.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from ingest.chamber_vote_inventory import API_BASE, CollectionError, _load
from ingest.chamber_vote_segments import _roll_call_number, api_outcome, verify_nominal

URGENCY_OUTCOMES = {'approved', 'rejected'}
URGENCY_FIELDS = ('title', 'summary', 'decisionLabel', 'yesMeaning', 'noMeaning')
# Maioria absoluta da composição da Câmara, exigida pelo art. 155 do Regimento Interno.
URGENCY_QUORUM = 257
TARGET_TYPES = {'PL', 'PLP', 'PEC', 'MPV', 'PDL'}
# Tipos do Placar: pedidos sem votação principal ligada só entram para esses projetos.
PLACAR_TYPES = {'PL', 'PLP', 'PEC'}
REQUEST_LABEL = re.compile(r'REQ (\d+)/(\d{4})')
FICHA = 'https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={}'


def _folded(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    return ''.join(character for character in text if not unicodedata.combining(character)).casefold()


def cites(text, number, year):
    """O texto cita a proposição pelo número e ano ("PL Nº 1.958/2021", "nº 177, de 2023", "PL 2342/22")."""
    for found_number, found_year in re.findall(r'(\d[\d.]*)\s*(?:/|,?\s*de\s+)\s*(\d{4}|\d{2})(?!\d)', _folded(text)):
        found = int(found_year) if len(found_year) == 4 else 2000 + int(found_year)
        if int(found_number.replace('.', '')) == number and found == year:
            return True
    return False


def _moment(value):
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _proposition_id(url):
    match = re.search(r'[?&]idProposicao=(\d+)', url or '')
    return int(match.group(1)) if match else None


def text_status(target_id, registered, entry, inventory_entries, parents, excluded, through):
    """Situação do texto de um projeto sem votação principal no Placar depois do pedido de urgência.

    Procedimentos (requerimentos, mudança de regime) não contam como deliberação do texto. A primeira
    deliberação depois do pedido tem de ser o texto principal excluído do Placar por votação simbólica;
    sem nenhuma deliberação, o texto não foi votado até o fim do inventário. Qualquer outro caso
    (emendas do Senado, subemenda sem texto, texto publicado no Placar) falha fechado.
    """
    later = []
    for other in inventory_entries.values():
        if int(other['id'].split('-')[0]) != target_id or other['date'] < entry['date'] or other.get('category') == 'procedure':
            continue
        moment = _moment(other.get('registeredAt'))
        if moment is None:
            raise CollectionError(f"{entry['id']}: deliberação do projeto sem horário de registro; ordem ambígua.")
        if moment > registered:
            later.append((moment, other))
    if not later:
        return {'kind': 'not_voted', 'through': through}
    later.sort(key=lambda pair: (pair[0], pair[1]['id']))
    candidates = [other for _, other in later if other.get('candidate')]
    if not candidates:
        raise CollectionError(f"{entry['id']}: a primeira deliberação depois do pedido não é a do texto principal.")
    first = candidates[0]
    # Antes do texto, só emendas votadas na mesma sessão (como a de uma comissão, rejeitada antes do texto).
    before = [other for _, other in later[:[other for _, other in later].index(first)]]
    if any(other.get('category') != 'amendment' or other['date'] != first['date'] for other in before):
        raise CollectionError(f"{entry['id']}: a primeira deliberação depois do pedido não é a do texto principal.")
    if first['id'] in parents:
        raise CollectionError(f"{entry['id']}: o texto foi votado no Placar ({first['id']}); ligue o pedido a essa votação.")
    if 'simbolic' not in _folded(excluded.get(first['id'], '')):
        raise CollectionError(f"{entry['id']}: texto votado sem votação simbólica confirmada na revisão.")
    return {'kind': 'symbolic', 'date': first['date']}


def build_urgencies(items, inventory_entries, reviews, *, taken, cache, collect, refresh, request,
                    standalone=None, excluded=None, through=None):
    """Valida as revisões e pendura cada pedido na votação principal; devolve os detalhes novos.

    Revisão sem ``parentId``: o projeto não tem votação principal no Placar depois do pedido. O pedido vai
    para ``standalone``, com o projeto e a situação do texto calculada do inventário (``text_status``).
    """
    from ingest.chamber_votes import (PROPOSITION_LABEL as proposition_label, REGISTRATION_LAG, VOTE_ID as vote_id,
                                      _official_source as official_source, _valid_review_date as valid_date)
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

        entry = inventory_entries.get(identifier)
        safe_sources = {key: official_source(sources.get(key)) for key in ('rollCall', 'request', 'proposition')}
        registered = _moment((entry or {}).get('registeredAt'))
        if entry is None or registered is None:
            raise CollectionError(f'{identifier}: pedido fora do inventário ou sem horário de registro.')
        if review.get('parentId') is None:
            parent = None
            target_id = _proposition_id(safe_sources['proposition'])
            if standalone is None or excluded is None or not through or target_id is None:
                raise CollectionError(f'{identifier}: pedido sem votação principal precisa da ficha do projeto.')
            targets = {target_id}
        else:
            parent = parents.get(review.get('parentId'))
            if parent is None or entry['date'] > parent['date']:
                raise CollectionError(f'{identifier}: pedido sem votação principal publicada depois dele.')
            targets = {_proposition_id(parent['sources'].get(key)) for key in ('proposition', 'referenceProposition')} - {None}
            if safe_sources['proposition'] != parent['sources']['proposition']:
                raise CollectionError(f'{identifier}: ficha do projeto diferente da votação principal ligada.')

        if parent is not None:
            # A votação principal ligada é a primeira deliberação do texto principal depois do pedido. A ordem
            # vem do número sequencial dos relatórios nominais (ideVotacao); o horário de registro da API, que
            # pode atrasar alguns minutos, só decide com folga, e o que cai dentro da folga fica ambíguo.
            parent_entry = inventory_entries.get(parent['id'])
            parent_registered = _moment((parent_entry or {}).get('registeredAt'))
            own_number = _roll_call_number(safe_sources['rollCall'])
            parent_number = _roll_call_number(parent['sources'].get('rollCall'))
            if (parent_registered is None or not registered < parent_registered
                    or own_number is None or parent_number is None or not own_number < parent_number):
                raise CollectionError(f'{identifier}: pedido não é anterior à votação principal ligada.')
            for other in inventory_entries.values():
                if (not other.get('candidate') or other['id'] == parent['id']
                        or int(other['id'].split('-')[0]) not in targets
                        or not entry['date'] <= other['date'] <= parent['date']):
                    continue
                moment = _moment(other.get('registeredAt'))
                if moment is None or registered - REGISTRATION_LAG < moment < parent_registered + REGISTRATION_LAG:
                    raise CollectionError(f'{identifier}: outra deliberação do texto principal fica entre o pedido '
                                          'e a votação ligada, ou a ordem é ambígua.')

        urgency_cache = cache_for(identifier)
        url = f'{API_BASE}/votacoes/{identifier}'
        payload, detail_source = _load(url, urgency_cache / 'details' / f'{identifier}.json',
                                       collect=collect, refresh=refresh, request=request, detail=True)
        record = payload['dados']
        description = _folded(record.get('descricao'))
        cited_articles = set(re.findall(r'art(?:igo|\.)?\s*(\d+)', description))
        if (record.get('id') != identifier or record.get('data') != entry['date']
                or not re.search(r'requerimento de urgencia', description) or cited_articles - {'155'}):
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
                or safe_sources['request'] != FICHA.format(prefix)):
            raise CollectionError(f'{identifier}: requerimento não confirma o pedido de urgência revisado.')
        # O artigo vem da descrição da API ou, quando ela não diz, da ementa oficial do requerimento.
        if '155' not in cited_articles and not re.search(r'art(?:igo|\.)?\s*155\b', _folded(proposition.get('ementa'))):
            raise CollectionError(f'{identifier}: registro da API não confirma um pedido de urgência do art. 155.')

        affected = [item for item in record.get('proposicoesAfetadas') or []
                    if isinstance(item, dict) and item.get('siglaTipo') in TARGET_TYPES]
        if (len(affected) != 1 or affected[0].get('id') not in targets
                or (parent is None and affected[0].get('siglaTipo') not in PLACAR_TYPES)):
            raise CollectionError(f'{identifier}: projeto afetado diferente do projeto da votação principal.')
        target = affected[0]
        # Mesmo ID, duas numerações: a dos Dados Abertos e a da votação principal publicada (apensados).
        numbers = {(target.get('numero'), target.get('ano'))}
        match = proposition_label.fullmatch(parent['proposition']) if parent is not None else None
        if match and target.get('id') == _proposition_id(parent['sources'].get('proposition')):
            numbers.add((int(match.group(2)), int(match.group(3))))
        if (not any(cites(review['reportObject'], number, year) for number, year in numbers)
                or 'urgencia' not in _folded(review['reportObject'])):
            raise CollectionError(f'{identifier}: objeto do relatório não cita a urgência do projeto-alvo.')

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
                   'registeredAt': registered.isoformat(), **({'dataNotes': notes} if notes else {})}
        if parent is not None:
            parent.setdefault('urgencies', []).append(urgency)
        else:
            urgency['project'] = {'label': f"{target['siglaTipo']} {target['numero']}/{target['ano']}", 'type': target['siglaTipo']}
            urgency['textStatus'] = text_status(target['id'], registered, entry, inventory_entries, parents, excluded, through)
            urgency.pop('registeredAt')
            standalone.append(urgency)
        details[identifier] = detail
    for item in items:
        if 'urgencies' in item:
            item['urgencies'].sort(key=lambda urgency: (urgency.pop('registeredAt'), urgency['id']))
    if standalone:
        standalone.sort(key=lambda urgency: (urgency['date'], urgency['id']), reverse=True)
    return details
