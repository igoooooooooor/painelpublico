"""Read the reviewed Câmara voting scoreboard snapshots."""
from __future__ import annotations

from datetime import date
import json
import re
import threading
from pathlib import Path

from .config import SNAPSHOTS_PATH
from .database import fold

INDEX_NAME = 'chamber-votes.json'
DETAILS_DIRECTORY = 'chamber-vote-details'
_VOTE_ID = re.compile(r'^\d+-\d+$')
_DETAILS_VERSION = re.compile(r'^[0-9a-f]{64}$')
_THEME_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
_PARTICIPANT_ID = re.compile(r'^camara:\d+$')
_VOTE_CHOICES = {'Sim', 'Não', 'Abstenção', 'Obstrução', 'Presidiu'}
_OUTCOMES = {'approved', 'rejected', 'not_approved'}
_ITEM_FIELDS = ('id', 'date', 'proposition', 'type', 'title', 'summary', 'decisionLabel',
                'yesMeaning', 'noMeaning', 'outcome', 'tally', 'themes', 'sources', 'reviewedAt')
_COVERAGE_FIELDS = ('inventoryCount', 'candidateCount', 'reviewedCount', 'publishedCount', 'pendingCount')
_OPTIONAL_COVERAGE_FIELDS = ('excludedCount', 'missingTextCount', 'missingAbstentionCount', 'missingThemeCount')

_cache_lock = threading.Lock()
_snapshot_cache: dict[Path, tuple[tuple[int, int], object]] = {}


def _reject_json_constant(value):
    raise ValueError(f'Constante JSON inválida: {value}')


def _load_json(path):
    """Load one snapshot, caching only while its resolved path and file stat match."""
    resolved = Path(path).expanduser().resolve()
    with _cache_lock:
        for _ in range(2):
            try:
                before = resolved.stat()
            except OSError:
                _snapshot_cache.pop(resolved, None)
                return None
            signature = (before.st_mtime_ns, before.st_size)
            cached = _snapshot_cache.get(resolved)
            if cached is not None and cached[0] == signature:
                return cached[1]
            try:
                value = json.loads(resolved.read_text(encoding='utf-8'), parse_constant=_reject_json_constant)
                after = resolved.stat()
            except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
                _snapshot_cache.pop(resolved, None)
                return None
            if signature == (after.st_mtime_ns, after.st_size):
                _snapshot_cache[resolved] = (signature, value)
                return value
        _snapshot_cache.pop(resolved, None)
        return None


def _text(value, *, limit=5000, required=True):
    return (isinstance(value, str) and len(value) <= limit and
            (not required or bool(value.strip())))


def _count(value, *, nullable=False):
    return ((nullable and value is None) or
            (isinstance(value, int) and not isinstance(value, bool) and value >= 0))


def _summary_item(value):
    """Validate and project the public summary fields, excluding all detail-only data."""
    if not isinstance(value, dict) or not _VOTE_ID.fullmatch(str(value.get('id', ''))):
        return None
    if not _text(value.get('date'), limit=10):
        return None
    try:
        parsed_date = date.fromisoformat(value['date'])
    except ValueError:
        return None
    if parsed_date.isoformat() != value['date']:
        return None
    if value.get('type') not in {'PL', 'PLP', 'PEC'}:
        return None
    for key, limit in (('proposition', 100), ('title', 300), ('summary', 5000),
                       ('decisionLabel', 300), ('yesMeaning', 500), ('noMeaning', 500), ('reviewedAt', 80)):
        if not _text(value.get(key), limit=limit):
            return None
    if value.get('outcome') not in _OUTCOMES | {None}:
        return None

    tally = value.get('tally')
    if not isinstance(tally, dict) or any(not _count(tally.get(key), nullable=True)
                                          for key in ('yes', 'no', 'abstention', 'total')):
        return None
    themes = value.get('themes')
    if not isinstance(themes, list):
        return None
    safe_themes = []
    seen_themes = set()
    for theme in themes:
        if (not isinstance(theme, dict) or not isinstance(theme.get('id'), str)
                or not _THEME_ID.fullmatch(theme['id']) or not _text(theme.get('label'), limit=120)
                or theme['id'] in seen_themes):
            return None
        seen_themes.add(theme['id'])
        safe_themes.append({'id': theme['id'], 'label': theme['label']})
    sources = value.get('sources')
    if not isinstance(sources, dict):
        return None
    safe_sources = {}
    for key in ('vote', 'rollCall', 'proposition'):
        source = sources.get(key)
        if not _text(source, limit=2048) or not source.startswith('https://'):
            return None
        safe_sources[key] = source
    if 'text' not in sources:
        return None
    text_source = sources['text']
    if text_source is not None and (not _text(text_source, limit=2048) or not text_source.startswith('https://')):
        return None
    safe_sources['text'] = text_source
    decision_source = sources.get('decision')
    if 'decision' in sources:
        if decision_source is not None and (not _text(decision_source, limit=2048)
                                            or not decision_source.startswith('https://')):
            return None
        safe_sources['decision'] = decision_source
    if 'referenceProposition' in sources:
        reference = sources['referenceProposition']
        if not _text(reference, limit=2048) or not reference.startswith('https://'):
            return None
        safe_sources['referenceProposition'] = reference
    notes = value.get('dataNotes')
    if 'dataNotes' in value and (not isinstance(notes, list) or len(notes) > 4
                                or any(not _text(note, limit=500) for note in notes)):
        return None

    return {
        'id': value['id'], 'date': value['date'], 'proposition': value['proposition'], 'type': value['type'],
        'title': value['title'], 'summary': value['summary'], 'decisionLabel': value['decisionLabel'],
        'yesMeaning': value['yesMeaning'], 'noMeaning': value['noMeaning'], 'outcome': value['outcome'],
        'tally': {key: tally[key] for key in ('yes', 'no', 'abstention', 'total')},
        'themes': safe_themes, 'sources': safe_sources, 'reviewedAt': value['reviewedAt'],
        **({'dataNotes': notes} if 'dataNotes' in value else {}),
    }


def _index(path=None):
    snapshot_path = Path(path) if path is not None else Path(SNAPSHOTS_PATH) / INDEX_NAME
    data = _load_json(snapshot_path)
    if not isinstance(data, dict) or data.get('schemaVersion') != 1:
        return None
    details_version = data.get('detailsVersion')
    if 'detailsVersion' in data and (not isinstance(details_version, str)
                                     or not _DETAILS_VERSION.fullmatch(details_version)):
        return None
    if not _text(data.get('generatedAt'), limit=80):
        return None
    period = data.get('period')
    if not isinstance(period, dict) or not all(_text(period.get(key), limit=10) for key in ('start', 'end')):
        return None
    try:
        start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end'])
    except ValueError:
        return None
    if start.isoformat() != period['start'] or end.isoformat() != period['end'] or start > end:
        return None
    coverage = data.get('coverage')
    if not isinstance(coverage, dict) or any(not _count(coverage.get(key)) for key in _COVERAGE_FIELDS):
        return None
    if any(key in coverage and not _count(coverage[key]) for key in _OPTIONAL_COVERAGE_FIELDS):
        return None
    if any(key in coverage and coverage[key] > coverage['publishedCount']
           for key in ('missingTextCount', 'missingAbstentionCount', 'missingThemeCount')):
        return None
    if ('excludedCount' in coverage
            and (coverage['publishedCount'] + coverage['excludedCount'] + coverage['pendingCount']
                 != coverage['candidateCount']
                 or coverage['publishedCount'] + coverage['excludedCount'] > coverage['reviewedCount']
                 or coverage['reviewedCount'] > coverage['candidateCount'])):
        return None
    if not _text(coverage.get('detail'), limit=3000, required=False):
        return None
    items = data.get('items')
    if not isinstance(items, list):
        return None
    safe_items = []
    seen_ids = set()
    for raw_item in items:
        item = _summary_item(raw_item)
        if item is None or item['id'] in seen_ids:
            return None
        seen_ids.add(item['id'])
        safe_items.append(item)
    if coverage['publishedCount'] != len(safe_items):
        return None
    # Latest decisions first; IDs make same-day ordering stable.
    safe_items.sort(key=lambda item: item['id'])
    safe_items.sort(key=lambda item: item['date'], reverse=True)
    return {
        'generatedAt': data['generatedAt'], 'period': {'start': period['start'], 'end': period['end']},
        'coverage': {**{key: coverage[key] for key in (*_COVERAGE_FIELDS, *_OPTIONAL_COVERAGE_FIELDS)
                       if key in coverage}, 'detail': coverage['detail']},
        'items': safe_items, 'detailsVersion': details_version,
    }


def _page_number(value, default, upper=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < 1:
        return 1
    return min(number, upper) if upper is not None else number


def listing(params=None, path=None):
    """Return filtered and paginated reviewed votes from the index snapshot."""
    params = params or {}
    snapshot = _index(path)
    page = _page_number(params.get('page', '1'), 1)
    page_size = _page_number(params.get('pageSize', '12'), 12, 24)
    if snapshot is None:
        return {'available': False, 'items': [], 'total': 0, 'page': page, 'pageSize': page_size,
                'pageCount': 0, 'period': None, 'coverage': None,
                'filters': {'types': [], 'themes': []}, 'generatedAt': None}

    all_items = snapshot['items']
    types = ['PL', 'PLP', 'PEC']
    themes_by_id = {}
    for item in all_items:
        for theme in item['themes']:
            themes_by_id.setdefault(theme['id'], theme)
    query = fold(str(params.get('q', ''))[:120]).strip()
    type_filter = str(params.get('type', '')).upper()
    theme_filter = str(params.get('theme', ''))
    filtered = [item for item in all_items
                if (not query or all(word in fold(f"{item['title']} {item['summary']} {item['proposition']}")
                                     for word in query.split()))
                and (not type_filter or item['type'] == type_filter)
                and (not theme_filter or any(theme['id'] == theme_filter for theme in item['themes']))]
    total = len(filtered)
    page_count = (total + page_size - 1) // page_size
    offset = (page - 1) * page_size
    return {'available': True, 'items': filtered[offset:offset + page_size], 'total': total,
            'page': page, 'pageSize': page_size, 'pageCount': page_count,
            'period': snapshot['period'], 'coverage': snapshot['coverage'],
            'filters': {'types': types, 'themes': sorted(themes_by_id.values(), key=lambda theme: (theme['label'], theme['id']))},
            'generatedAt': snapshot['generatedAt']}


def detail(identifier, path=None):
    """Return one reviewed summary and its optional local roll-call details."""
    if not isinstance(identifier, str) or not _VOTE_ID.fullmatch(identifier):
        return None
    snapshot_path = Path(path) if path is not None else Path(SNAPSHOTS_PATH) / INDEX_NAME
    snapshot = _index(snapshot_path)
    if snapshot is None:
        return None
    vote = next((item for item in snapshot['items'] if item['id'] == identifier), None)
    if vote is None:
        return None

    details_root = (snapshot_path.parent / DETAILS_DIRECTORY).resolve()
    details_version = snapshot['detailsVersion']
    details_directory = (details_root / details_version).resolve() if details_version else details_root
    details_path = (details_directory / f'{identifier}.json').resolve()
    # Keep detail file reads within the selected generation, including when local symlinks exist.
    directory_escaped = (details_version is not None and
                         (details_directory.parent != details_root or details_directory.name != details_version))
    if directory_escaped or details_path.parent != details_directory:
        details = None
    else:
        details = _load_json(details_path)
    participants, party_totals, available = [], [], False
    if isinstance(details, dict) and details.get('id') == identifier:
        raw_participants, raw_party_totals = details.get('participants'), details.get('partyTotals')
        valid_participants = isinstance(raw_participants, list)
        safe_participants = []
        seen_participants = set()
        if valid_participants:
            for participant in raw_participants:
                if (not isinstance(participant, dict) or not isinstance(participant.get('id'), str)
                        or not _PARTICIPANT_ID.fullmatch(participant['id'])
                        or participant['id'] in seen_participants
                        or not _text(participant.get('name'), limit=200)
                        or not _text(participant.get('party'), limit=80, required=False)
                        or not _text(participant.get('uf'), limit=2)
                        or not re.fullmatch(r'[A-Z]{2}', participant['uf'])
                        or participant.get('vote') not in _VOTE_CHOICES):
                    valid_participants = False
                    break
                seen_participants.add(participant['id'])
                safe_participants.append({key: participant[key] for key in ('id', 'name', 'party', 'uf', 'vote')})
        valid_party_totals = isinstance(raw_party_totals, list)
        safe_party_totals = []
        seen_parties = set()
        if valid_party_totals:
            for total in raw_party_totals:
                if (not isinstance(total, dict) or not _text(total.get('party'), limit=80, required=False)
                        or total['party'] in seen_parties
                        or any(not _count(total.get(key)) for key in ('yes', 'no', 'other'))):
                    valid_party_totals = False
                    break
                seen_parties.add(total['party'])
                safe_party_totals.append({key: total[key] for key in ('party', 'yes', 'no', 'other')})
        if valid_participants and valid_party_totals:
            participants, party_totals, available = safe_participants, safe_party_totals, True
    return {'available': True, 'vote': vote, 'participants': participants,
            'partyTotals': party_totals, 'participantsAvailable': available}
