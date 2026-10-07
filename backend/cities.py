"""Consulta nacional de cidades, sem importar snapshots eleitorais no SQLite."""
from collections import defaultdict
from contextlib import closing
from pathlib import Path
import re
import sqlite3

from . import amendments
from .config import SNAPSHOTS_PATH
from .database import fold
from .profiles import _load

CITY_FIELDS = ('id', 'name', 'uf', 'population', 'populationYear', 'tseCode')
CANDIDATE_FIELDS = ('id', 'name', 'ballotName', 'office', 'party', 'uf', 'year',
                    'round', 'result', 'sourceDate', 'votes')
FEDERAL_OFFICES = {'DEPUTADO FEDERAL': 'deputado', 'SENADOR': 'senador'}


def _snapshot():
    data = _load(SNAPSHOTS_PATH / 'cities.json')
    return data if data and isinstance(data.get('municipalities'), list) else {}


def _city_rows(data):
    return [row for row in data.get('municipalities', [])
            if isinstance(row, dict) and re.fullmatch(r'\d{7}', str(row.get('id', '')))]


def search(query='', limit=20):
    data = _snapshot()
    words = fold(str(query)[:120]).split()
    found = [row for row in _city_rows(data)
             if all(word in fold(f"{row.get('name', '')} {row.get('uf', '')}") for word in words)]
    found.sort(key=lambda row: (fold(row.get('name', '')), row.get('uf', '')))
    return {'items': [{key: row.get(key) for key in CITY_FIELDS} for row in found[:limit]],
            'total': len(found), 'available': bool(_city_rows(data)),
            'source': data.get('sources', {}).get('municipalities', {})}


def _current_federal(db_path, uf):
    """Só lê o roster vigente; ausência do banco não impede consultar a cidade."""
    if not Path(db_path).is_file():
        return [], False
    try:
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            result = db.execute('''SELECT DISTINCT a.id,a.name,a.role,a.party,a.uf,
                s.url AS sourceUrl,s.period AS sourcePeriod,s.fetchedAt,s.status AS sourceStatus
                FROM authorities a JOIN roster r ON r.authorityId=a.id
                JOIN sources s ON s.id=r.sourceId
                WHERE a.uf=? AND ((a.role='deputado' AND r.sourceId='camara_deputies_current')
                OR (a.role='senador' AND r.sourceId='senado_senators_current'))
                ORDER BY a.role,a.name,a.id''', (uf,)).fetchall()
        return [{**dict(row), 'office': 'DEPUTADO FEDERAL' if row['role'] == 'deputado' else 'SENADOR'}
                for row in result], True
    except sqlite3.Error:
        return [], False


def _name(value):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', fold(value)).split())


def _links(candidates, roster):
    """Nome exato normalizado + UF + cargo, único nos dois sentidos; sem dados pessoais."""
    by_name = defaultdict(set)
    for member in roster:
        by_name[(_name(member['name']), member['uf'], member['role'])].add(member['id'])
    proposals = {}
    reverse = defaultdict(set)
    for row in candidates:
        role = FEDERAL_OFFICES.get(row.get('office'))
        matches = set()
        for field in ('name', 'ballotName'):
            key = _name(row.get(field))
            if key:
                matches.update(by_name.get((key, row.get('uf'), role), set()))
        if len(matches) == 1:
            identifier = next(iter(matches))
            proposals[row['id']] = identifier
            reverse[identifier].add(row['id'])
    return {key: value for key, value in proposals.items() if len(reverse[value]) == 1}


def _rows(data, section, key):
    collection = data.get(section, {})
    values = collection.get(key, []) if isinstance(collection, dict) else []
    return [{field: row.get(field) for field in CANDIDATE_FIELDS if field in row}
            for row in values if isinstance(row, dict) and row.get('id')]


def detail(identifier, db_path):
    if not re.fullmatch(r'\d{7}', identifier):
        return None
    data = _snapshot()
    city = next((row for row in _city_rows(data) if str(row['id']) == identifier), None)
    if city is None:
        return None
    municipal = _rows(data, 'municipalElected', identifier)
    state = _rows(data, 'stateElected', city['uf'])
    votes = _rows(data, 'municipalVotes', identifier)
    roster, roster_available = _current_federal(db_path, city['uf'])
    links = _links(state, roster)
    for row in state + votes:
        if row['id'] in links:
            row['profileId'] = links[row['id']]
    municipal_message = '' if municipal else 'Não há resultado municipal de 2024 confirmado nesta base. Ausência não significa que não houve eleição.'
    if identifier == '5300108':
        municipal_message = 'Brasília não elege prefeito nem vereadores. No Distrito Federal, consulte governador e deputados distritais.'
    elif identifier == '2605459':
        municipal_message = 'Fernando de Noronha é um distrito estadual e não elege prefeito nem vereadores.'
    sources = dict(data.get('sources', {}))
    sources['currentFederal'] = {}
    for chamber, label in (('camara', 'Lista atual da Câmara'), ('senado', 'Lista atual do Senado')):
        member = next((row for row in roster if row['id'].startswith(chamber + ':')), None)
        if member:
            sources['currentFederal'][chamber] = {
                'label': label, 'url': member.get('sourceUrl'), 'period': member.get('sourcePeriod'),
                'fetchedAt': member.get('fetchedAt'), 'status': member.get('sourceStatus'),
                'note': '' if member.get('sourceStatus') == 'imported' else
                    'A atualização desta lista não foi concluída. Exibimos a lista anterior preservada; a data da tentativa não confirma sua atualidade.'}
    return {'municipality': {key: city.get(key) for key in CITY_FIELDS},
            'generatedAt': data.get('generatedAt'), 'sources': sources,
            'municipalElected': municipal, 'stateElected': state, 'topFederalVotes': votes,
            'amendments': amendments.detail(identifier, db_path, SNAPSHOTS_PATH / 'amendments.json'),
            'currentFederal': roster, 'coverage': data.get('coverage', {}),
            'messages': {
                'municipalElection': municipal_message,
                'generalElection': '' if state else 'Resultados de 2026 não disponíveis nesta base para esta UF. Não indica ausência de representantes.',
                'votes': '' if votes else 'Votos por município de 2026 ainda não disponíveis nesta base para esta cidade.',
                'currentFederal': '' if roster else ('Lista parlamentar ainda não disponível para esta UF.' if roster_available else 'Lista parlamentar local indisponível.')},
            'profileLinks': {'matched': len(links), 'eligible': sum(row.get('office') in FEDERAL_OFFICES for row in state),
                             'method': 'Nome exato normalizado, UF e cargo, com correspondência única nos dois sentidos.'}}
