"""Parse official Câmara party roll-call reports and match named participants."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
import re
import unicodedata

from ingest.chamber_vote_inventory import CollectionError


__all__ = ['parse_roll_call', 'identify_participants']

_VOTE_CHOICES = {'Sim', 'Não', 'Abstenção', 'Artigo 17', 'Obstrução', 'Presidiu'}
_SPACE = re.compile(r'\s+')
_COUNT = re.compile(r'(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:\.[0-9]{3})+)\Z')
_SESSION = re.compile(r'SESSÃO\s+[^.]*?\bN[º°.]?\s*\d+\s*-\s*(\d{2}/\d{2}/\d{4})', re.I)
_SESSION_OPEN = re.compile(r'Abertura da sessão\s*:\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', re.I)
_SESSION_CLOSE = re.compile(r'Encerramento da sessão\s*:\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', re.I)
_VOTE_START = re.compile(r'Início da votação\s*:\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', re.I)
_VOTE_END = re.compile(r'Encerramento da votação\s*:\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', re.I)
_PROPOSITION = re.compile(
    r'Proposição\s*:\s*([A-Z]+)\s*N[º°.]?\s*(\d+)\s*/\s*(\d+)\s*'
    r'-\s*(.*?)\s*-\s*Nominal\s+Eletrônica\b', re.I)
_SUBTOTAL = re.compile(r'Total\s+(.+?)\s*:\s*((?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:\.[0-9]{3})+))\Z', re.I)


def _clean(value):
    return _SPACE.sub(' ', value or '').strip()


def _decode(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, (bytes, bytearray)):
        raise CollectionError('O relatório não é texto ou bytes HTML.')
    raw = bytes(content)
    head = raw[:8192].decode('ascii', errors='ignore')
    match = re.search(r'charset\s*=\s*["\']?([\w.-]+)', head, re.I)
    encoding = match.group(1) if match else 'utf-8'
    try:
        return raw.decode(encoding, errors='strict')
    except (LookupError, UnicodeDecodeError) as error:
        raise CollectionError(f'Codificação HTML inválida: {encoding}.') from error


class _ReportParser(HTMLParser):
    """Keep only the two named report tables and visible page text."""

    TARGETS = {'listaVotacao', 'listagem'}
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
            'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.section_counts = {name: 0 for name in self.TARGETS}
        self.rows = {name: [] for name in self.TARGETS}
        self.current_row = None
        self.current_cell = None
        self.visible = []
        self.suppressed = 0

    def _section(self):
        for _, section in reversed(self.stack):
            if section:
                return section
        return None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = dict(attrs)
        section = attributes.get('id') if tag == 'div' else None
        if section in self.TARGETS:
            self.section_counts[section] += 1
        else:
            section = None
        if tag in {'script', 'style'}:
            self.suppressed += 1
        if tag in self.VOID:
            return
        active = self._section()
        self.stack.append((tag, section))
        if active and tag == 'tr':
            if self.current_row is not None:
                raise CollectionError('Linha HTML aninhada no relatório.')
            self.current_row = []
        elif active and tag in {'td', 'th'}:
            if self.current_row is not None:
                if self.current_cell is not None:
                    raise CollectionError('Célula HTML anterior não foi encerrada.')
                try:
                    colspan = int(attributes.get('colspan', '1'))
                except (TypeError, ValueError):
                    raise CollectionError('Colspan inválido no relatório.') from None
                if colspan < 1:
                    raise CollectionError('Colspan inválido no relatório.')
                self.current_cell = {'tag': tag, 'colspan': colspan, 'parts': []}

    def handle_endtag(self, tag):
        tag = tag.lower()
        active = self._section()
        if active and tag in {'td', 'th'} and self.current_cell is not None:
            self.current_cell['text'] = _clean(' '.join(self.current_cell.pop('parts')))
            self.current_row.append(self.current_cell)
            self.current_cell = None
        elif active and tag == 'tr' and self.current_row is not None:
            self.rows[active].append(self.current_row)
            self.current_row = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                removed = self.stack[index:]
                del self.stack[index:]
                if any(item[0] in {'script', 'style'} for item in removed):
                    self.suppressed = max(0, self.suppressed - 1)
                return

    def handle_startendtag(self, tag, attrs):
        if tag.lower() in self.VOID:
            self.handle_starttag(tag, attrs)
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if self.suppressed:
            return
        self.visible.append(data)
        if self.current_cell is not None:
            self.current_cell['parts'].append(data)


def _single(pattern, text, field):
    found = list(pattern.finditer(text))
    if len(found) != 1:
        raise CollectionError(f'{field} ausente ou ambíguo no relatório.')
    return found[0]


def _parse_datetime(match, field):
    try:
        return datetime.strptime(f'{match.group(1)} {match.group(2)}', '%d/%m/%Y %H:%M')
    except ValueError:
        raise CollectionError(f'Data ou hora inválida em {field}.') from None


def _parse_count(value, field):
    value = _clean(value)
    if not _COUNT.fullmatch(value):
        raise CollectionError(f'Contagem inválida em {field}.')
    return int(value.replace('.', ''))


def _tally(rows):
    labels = {'Sim': 'yes', 'Não': 'no', 'Abstenção': 'abstention',
              'Total da Votação': 'total'}
    values = {}
    for row in rows:
        if not row or row[0]['tag'] != 'th':
            continue
        label = _clean(row[0]['text']).rstrip(':').strip()
        if label not in labels:
            continue
        field = labels[label]
        if field in values:
            raise CollectionError(f'Contagem duplicada para {label}.')
        if len(row) != 2 or row[1]['tag'] != 'td' or row[0]['colspan'] != 1 or row[1]['colspan'] != 1:
            raise CollectionError(f'Linha de contagem inválida para {label}.')
        values[field] = _parse_count(row[1]['text'], label)
    for field, label in [('yes', 'Sim'), ('no', 'Não'), ('total', 'Total da Votação')]:
        if field not in values:
            raise CollectionError(f'Contagem de {label} ausente no relatório.')
    values.setdefault('abstention', None)
    counted = values['yes'] + values['no'] + (values['abstention'] or 0)
    if counted > values['total']:
        raise CollectionError('As contagens excedem o total da votação.')
    return values


def _normalize_name(value):
    decomposed = unicodedata.normalize('NFD', _clean(value).casefold())
    unaccented = ''.join(character for character in decomposed
                         if unicodedata.category(character) != 'Mn')
    return _SPACE.sub(' ', unaccented).strip()


def _participants(rows):
    result = []
    header_count = 0
    party = None
    party_counts = {}
    party_closed = set()
    identities = set()
    for row in rows:
        if len(row) == 3 and all(cell['tag'] == 'th' and cell['colspan'] == 1 for cell in row):
            labels = tuple(_normalize_name(cell['text']) for cell in row)
            if labels == ('parlamentar', 'uf', 'voto'):
                header_count += 1
                continue
        if len(row) == 1:
            cell = row[0]
            text = _clean(cell['text'])
            if cell['tag'] == 'th' and cell['colspan'] == 3:
                if party is not None and party not in party_closed:
                    raise CollectionError(f'Falta subtotal para o partido {party}.')
                party = text
                party_key = _normalize_name(party)
                if not party or party_key in party_counts:
                    raise CollectionError('Partido vazio ou repetido no relatório.')
                party_counts[party_key] = {'name': party, 'count': 0}
                party = party_key
                continue
            subtotal = _SUBTOTAL.fullmatch(text) if cell['tag'] == 'td' and cell['colspan'] == 3 else None
            if subtotal:
                subtotal_party = _normalize_name(subtotal.group(1))
                if party is None or subtotal_party != party or party in party_closed:
                    raise CollectionError('Subtotal sem grupo de partido correspondente.')
                count = _parse_count(subtotal.group(2), 'subtotal')
                if count != party_counts[party]['count']:
                    raise CollectionError(f'Subtotal incompatível para o partido {party_counts[party]["name"]}.')
                party_closed.add(party)
                party = None
                continue
        if len(row) != 3 or any(cell['tag'] != 'td' or cell['colspan'] != 1 for cell in row):
            raise CollectionError('Linha de parlamentar malformada no relatório.')
        if party is None:
            raise CollectionError('Voto sem grupo de partido no relatório.')
        name, uf, vote = (_clean(cell['text']) for cell in row)
        if vote == 'Art. 17':
            vote = 'Artigo 17'
        if not name or not re.fullmatch(r'[A-Z]{2}', uf) or vote not in _VOTE_CHOICES:
            raise CollectionError('Nome, UF ou opção de voto inválida no relatório.')
        identity = (_normalize_name(name), uf)
        if identity in identities:
            raise CollectionError(f'Parlamentar duplicado no relatório: {name} ({uf}).')
        identities.add(identity)
        party_counts[party]['count'] += 1
        result.append({'name': name, 'uf': uf, 'party': party_counts[party]['name'], 'vote': vote})
    if header_count != 1:
        raise CollectionError('Cabeçalho Parlamentar/UF/Voto ausente ou repetido.')
    if party is not None or not party_counts or party_closed != set(party_counts):
        raise CollectionError('Grupos de partido incompletos no relatório.')
    return result


def parse_roll_call(content):
    """Parse one official nominal electronic roll-call report, failing closed."""
    parser = _ReportParser()
    try:
        parser.feed(_decode(content))
        parser.close()
    except CollectionError:
        raise
    except Exception as error:
        raise CollectionError('HTML do relatório inválido.') from error
    if parser.current_cell is not None or parser.current_row is not None:
        raise CollectionError('Tabela HTML incompleta no relatório.')
    if parser.section_counts != {'listaVotacao': 1, 'listagem': 1}:
        raise CollectionError('Blocos de placar ou de votantes ausentes ou repetidos.')
    text = _clean(' '.join(parser.visible))
    session_date = _single(_SESSION, text, 'sessão').group(1)
    try:
        report_day = datetime.strptime(session_date, '%d/%m/%Y').date()
    except ValueError:
        raise CollectionError('Data da sessão inválida.') from None
    dated = [
        ('abertura da sessão', _SESSION_OPEN),
        ('encerramento da sessão', _SESSION_CLOSE),
        ('início da votação', _VOTE_START),
        ('encerramento da votação', _VOTE_END),
    ]
    times = {}
    for field, pattern in dated:
        match = _single(pattern, text, field)
        value = _parse_datetime(match, field)
        if value.date() != report_day:
            raise CollectionError(f'Data divergente em {field}.')
        times[field] = value
    if times['encerramento da votação'] < times['início da votação']:
        raise CollectionError('Encerramento da votação anterior ao início.')
    if times['encerramento da sessão'] < times['abertura da sessão']:
        raise CollectionError('Encerramento da sessão anterior à abertura.')
    proposition = _single(_PROPOSITION, text, 'proposição nominal eletrônica')
    proposition_type, number, year, object_name = proposition.groups()
    if not _clean(object_name):
        raise CollectionError('Objeto da votação ausente no cabeçalho.')
    tally = _tally(parser.rows['listaVotacao'])
    participants = _participants(parser.rows['listagem'])
    participant_counts = Counter(row['vote'] for row in participants)
    for field, label in (('yes', 'Sim'), ('no', 'Não')):
        if participant_counts[label] != tally[field]:
            raise CollectionError(f'Contagem de {label} diverge dos votos nominais.')
    if tally['abstention'] is not None and participant_counts['Abstenção'] != tally['abstention']:
        raise CollectionError('Contagem de Abstenção diverge dos votos nominais.')
    counted_votes = sum(participant_counts[vote] for vote in ('Sim', 'Não', 'Abstenção'))
    if counted_votes != tally['total']:
        raise CollectionError('Total da votação diverge dos votos Sim, Não e Abstenção.')
    return {
        'date': report_day.isoformat(),
        'proposition': {'type': proposition_type.upper(), 'number': int(number), 'year': int(year)},
        'object': _clean(object_name).upper(),
        'endedAt': times['encerramento da votação'].strftime('%Y-%m-%dT%H:%M'),
        'tally': tally,
        'participants': participants,
    }


def _official_key(row):
    if not isinstance(row, dict):
        raise CollectionError('Registro de deputado oficial inválido.')
    identifier = row.get('id')
    name = row.get('nome')
    uf = row.get('siglaUf')
    if (not (isinstance(identifier, int) and not isinstance(identifier, bool) and identifier > 0)
            or not isinstance(name, str) or not _clean(name)
            or not isinstance(uf, str) or not re.fullmatch(r'[A-Za-z]{2}', _clean(uf))):
        raise CollectionError('Identidade de deputado oficial incompleta.')
    return (_normalize_name(name), _clean(uf).upper()), identifier


def identify_participants(report_rows, deputies):
    """Resolve report names to unique official IDs using exact normalized name+UF."""
    if not isinstance(report_rows, list) or not isinstance(deputies, list):
        raise CollectionError('Listas de participantes inválidas.')
    official = {}
    for deputy in deputies:
        key, identifier = _official_key(deputy)
        official.setdefault(key, set()).add(identifier)
    result = []
    seen = set()
    for row in report_rows:
        if not isinstance(row, dict):
            raise CollectionError('Participante do relatório inválido.')
        name, uf, party, vote = (row.get(field) for field in ('name', 'uf', 'party', 'vote'))
        if (not isinstance(name, str) or not _clean(name)
                or not isinstance(uf, str) or not re.fullmatch(r'[A-Z]{2}', _clean(uf))
                or not isinstance(party, str) or not _clean(party)
                or vote not in _VOTE_CHOICES):
            raise CollectionError('Identidade ou voto do relatório inválido.')
        key = (_normalize_name(name), _clean(uf))
        if key in seen:
            raise CollectionError(f'Parlamentar duplicado no relatório: {name} ({uf}).')
        seen.add(key)
        matches = official.get(key, set())
        if not matches:
            raise CollectionError(f'Deputado oficial não encontrado: {name} ({uf}).')
        if len(matches) != 1:
            raise CollectionError(f'Identidade oficial ambígua: {name} ({uf}).')
        result.append({
            'deputado_': {'id': next(iter(matches)), 'nome': name,
                          'siglaPartido': _clean(party), 'siglaUf': _clean(uf)},
            'tipoVoto': vote,
        })
    return result
