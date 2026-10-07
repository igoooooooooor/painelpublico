"""Emendas municipais: fotografia do Portal, sem misturar naturezas financeiras."""
from collections import defaultdict
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import re
import sqlite3

from .database import fold
from .profiles import _load

SOURCE_URL = 'https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares'


def _name(value):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', fold(str(value or ''))).split())


def _roster(db_path):
    if not Path(db_path).is_file():
        return []
    try:
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('''SELECT DISTINCT a.id,a.name
                FROM authorities a JOIN roster r ON r.authorityId=a.id
                WHERE (a.role='deputado' AND r.sourceId='camara_deputies_current')
                   OR (a.role='senador' AND r.sourceId='senado_senators_current')''')]
    except sqlite3.Error:
        return []


def author_links(data, roster):
    """Correspondência nacional exata e única; destino não informa a UF do autor."""
    names = defaultdict(set)
    for member in roster:
        if re.fullmatch(r'(camara|senado):\d+', member['id']):
            names[_name(member['name'])].add(member['id'])
    authors = defaultdict(set)
    # O catálogo inclui também autorias sem destino municipal identificável.
    catalog = data.get('authors')
    if not isinstance(catalog, list):
        catalog = [author for city in data.get('municipalities', {}).values()
                   for author in city.get('authors', [])]
    collective = set()
    for author in catalog:
        identifier = str(author['id'])
        variants = author.get('nameVariants') or [author.get('name')]
        authors[identifier].update(_name(name) for name in variants)
        if any(not _name(kind).startswith('emenda individual') for kind in author.get('types', [])):
            collective.add(identifier)
    candidates = {}
    reverse = defaultdict(set)
    for identifier, variants in authors.items():
        if len(variants) != 1 or identifier in collective:
            continue
        name = next(iter(variants))
        if not name or any(word in name.split() for word in ('bancada', 'comissao', 'relator')):
            continue
        matches = names.get(name, set())
        if len(matches) == 1:
            profile = next(iter(matches))
            candidates[identifier] = profile
            reverse[profile].add(identifier)
    return {key: value for key, value in candidates.items() if len(reverse[value]) == 1}


def detail(identifier, db_path, snapshot_path):
    data = _load(snapshot_path) or {}
    source = deepcopy(data.get('source') or {'label': 'Portal da Transparência', 'url': SOURCE_URL})
    base = {'year': data.get('year'), 'source': source, 'coverage': data.get('coverage', {}),
            'totals': {'committedCents': None, 'paidCents': None, 'restosPaidCents': None},
            'recordCount': 0, 'authors': [], 'records': [],
            'specialTransfers': {'identified': False, 'recordCount': 0,
                                 'totals': {'committedCents': None, 'paidCents': None, 'restosPaidCents': None}}}
    if not isinstance(data.get('municipalities'), dict) or source.get('status') == 'unavailable':
        return {**base, 'status': 'unavailable',
                'message': 'A base local de emendas está indisponível. Ausência de dados não significa valor zero.'}
    row = data['municipalities'].get(identifier)
    if not row or not row.get('recordCount'):
        if source.get('status') == 'stale':
            source['note'] = 'A atualização falhou. A ausência de registros se refere à fotografia anterior preservada.'
        return {**base, 'status': 'no_records',
                'message': 'Nenhuma emenda com este código municipal foi encontrada no ano da proposta consultado. Isso não significa que a cidade não recebeu recursos.'}
    result = {**base, **deepcopy(row)}
    links = author_links(data, _roster(db_path))
    for author in result['authors']:
        author.pop('profileId', None)
        if str(author['id']) in links:
            author['profileId'] = links[str(author['id'])]
    result['profileLinks'] = {'matched': sum('profileId' in row for row in result['authors']),
                              'eligible': len(result['authors']),
                              'method': 'Nome público exato normalizado, único nos dois sentidos na base nacional e no roster atual. Sem inferir UF pelo destino.'}
    result.setdefault('status', 'available')
    if source.get('status') == 'stale':
        result['status'] = 'stale'
        result['message'] = 'A atualização falhou. Exibimos a fotografia anterior preservada, com sua data de coleta.'
    return result
