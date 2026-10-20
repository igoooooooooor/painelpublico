"""Páginas com endereço próprio para buscadores e ferramentas de IA, robots.txt, sitemap.xml e llms.txt.

O app continua o mesmo: o servidor acrescenta ao HTML montado (dist/index.html) título, descrição, endereço
canônico, Open Graph, dados estruturados e, dentro de #app, o conteúdo essencial da página em HTML (resumo da
ficha, listas, números e fontes das seções), montado por ``seo_sections`` com as mesmas funções do backend que
servem a API. O JavaScript mantém esse conteúdo até ter o equivalente carregado; robôs e pessoas sem JavaScript
leem o HTML. As respostas usam o mesmo cache do modo de produção, invalidado quando o banco ou os snapshots mudam.
Títulos e descrições das seções vêm de frontend/data/site-pages.json, compartilhado com o app.
"""
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import sys
from urllib.parse import unquote

from .settlement import settled_cutoff
from . import citizen, costs, profiles, seo_sections as sections, votes
from .config import ROOT, SNAPSHOTS_PATH
from .database import fold

SITE_NAME = 'Painel Público'
CONTACT_EMAIL = 'contato@painelpublico.com'
SITE_PAGES_PATH = ROOT / 'frontend' / 'data' / 'site-pages.json'
LEGACY_VOTES_PATH = ROOT / 'frontend' / 'data' / 'votes.json'
OG_IMAGE_PATH = '/og-image.png'
OG_IMAGE_SIZE = (1200, 630)
OG_IMAGE_ALT = 'Painel Público: quanto custa e como trabalha cada parlamentar'


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


SITE_PAGES = _read_json(SITE_PAGES_PATH, {})
# Seções do app com endereço próprio: caminho → (view do app, título, descrição). Mesma fonte do título da aba no app.
SECTIONS = {entry['path']: (entry['view'], entry.get('title'), entry['description']) for entry in SITE_PAGES.get('sections', [])}
SECTION_PATH_BY_VIEW = {view: path for path, (view, _, _) in SECTIONS.items()}
DEFAULT_DESCRIPTION = SECTIONS.get('/', (None, None, ''))[2]
# Votações selecionadas que o app ainda mostra sem o catálogo: têm página, mas o catálogo pode não conhecê-las.
LEGACY_VOTE_IDS = {str(vote.get('id')) for vote in _read_json(LEGACY_VOTES_PATH, []) if isinstance(vote, dict)}
# Comparação compartilhável de dois partidos: /partidos/PL-vs-PT (siglas codificadas na URL).
PARTY_PAIR_PATH = re.compile(r'^/partidos/([^/]{1,60})-vs-([^/]{1,60})$')
# Comparação compartilhável de dois políticos: /comparar/deputado-73604-vs-senador-22.
COMPARE_PAIR_PATH = re.compile(r'^/comparar/(deputado|senador)-(\d{1,9})-vs-(deputado|senador)-(\d{1,9})$')
PROFILE_PATH = re.compile(r'^/(deputado|senador)/(\d{1,9})(?:-[a-z0-9-]*)?/?$')
VOTE_DETAIL_PATH = re.compile(r'^/placar/(\d{1,12}-\d{1,6})$')
# Endereços antigos de seções, mantidos para os links já compartilhados.
LEGACY_SECTION_PATHS = {'/alertas': '/picos-e-concentracoes'}
ROLE_BY_PREFIX = {'deputado': ('camara', 'deputado'), 'senador': ('senado', 'senador')}
PREFIX_BY_HOUSE = {'camara': 'deputado', 'senado': 'senador'}
ROLE_LABEL = {'deputado': 'Deputado(a) federal', 'senador': 'Senador(a)'}
MONTHS = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
BODY_ERRORS = (sqlite3.Error, ValueError, TypeError, KeyError, OSError, ArithmeticError, AttributeError)


def site_origin(headers):
    """Endereço público: PAINEL_SITE_URL ou o Host recebido pelo túnel (sempre https fora de localhost)."""
    configured = os.environ.get('PAINEL_SITE_URL', '').strip().rstrip('/')
    if configured:
        return configured
    host = re.sub(r'[^A-Za-z0-9.:\-\[\]]', '', headers.get('Host', '') or '') or 'localhost'
    local = host.startswith(('127.0.0.1', 'localhost', '[::1]'))
    return f'{"http" if local else "https"}://{host}'


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', fold(name)).strip('-')


def profile_path(identifier, name=None):
    house, number = identifier.split(':', 1)
    return f'/{PREFIX_BY_HOUSE[house]}/{number}' + (f'-{slug(name)}' if name else '')


def money(value):
    """R$ com separadores brasileiros e sem centavos (resumos curtos)."""
    return 'R$ ' + f'{value:,.0f}'.replace(',', '.')


def money_cents(cents):
    whole, rest = divmod(abs(int(cents)), 100)
    return f'{"-" if cents < 0 else ""}R$ {whole:,}'.replace(',', '.') + f',{rest:02d}'


def month_range(periods):
    """'fev/2023–jul/2026, 42 meses'; meses não seguidos viram trechos separados."""
    serials = sorted({int(period[:4]) * 12 + int(period[5:7]) - 1 for period in periods})
    if not serials:
        return ''
    runs = []
    for serial in serials:
        if runs and serial == runs[-1][-1] + 1:
            runs[-1].append(serial)
        else:
            runs.append([serial])
    label_of = lambda serial: f'{MONTHS[serial % 12 + 1]}/{serial // 12}'
    label = ', '.join(label_of(run[0]) if len(run) == 1 else f'{label_of(run[0])}–{label_of(run[-1])}'
                      for run in runs)
    return f'{label}, {len(serials)} {"mês" if len(serials) == 1 else "meses"}'


def period_label(start, end):
    """'fev/2023–set/2026' a partir de 'AAAA-MM'; vazio se faltar alguma ponta."""
    def label(value):
        if not isinstance(value, str) or len(value) != 7:
            return ''
        return f'{MONTHS[int(value[5:7])]}/{value[:4]}'
    first, last = label(start), label(end)
    return '' if not first or not last else first if first == last else f'{first}–{last}'


def _chamber_presence(number):
    try:
        rows = json.loads((SNAPSHOTS_PATH / 'presenca.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(rows, list):
        return None
    row = next((r for r in rows if isinstance(r, dict) and str(r.get('id')) == number), None)
    if not row:
        return None
    counts = [row.get(key) for key in ('presente', 'falta', 'justificadas', 'dias')]
    # O resumo para buscadores respeita a mesma consistência exigida na ficha.
    if (any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts)
            or counts[3] <= 0 or sum(counts[:3]) != counts[3]):
        return None
    return row


def _latest_cost_month(cost, as_of=None):
    """(mês, centavos) do número principal da ficha: o mês mais recente com as quatro partes e 3 meses de
    folga até a fotografia das notas (`profileCostPickMonth`); sem mês com folga, o mais recente."""
    used = costs.settled_periods(cost.get('usedMonths') or [], None)
    if not used or not isinstance(cost.get('monthlyAverageCents'), int):
        return None
    parts = ('remuneration', 'allowances', 'quota', 'office')
    # Lacunas confirmadas participam da média de cada parte, mas não são um total mensal completo.
    complete = [period for period in used if all(
        costs._cents((((cost.get('months') or {}).get(period) or {}).get('valuesCents') or {}).get(key))
        for key in parts)]
    if not complete:
        return None
    period = costs.settled_periods(complete, as_of)[-1]
    values = ((cost.get('months') or {}).get(period) or {}).get('valuesCents') or {}
    return period, sum(values[key] for key in parts)


def _senate_cost_line(senate_cost, record):
    """Linha do custo de um(a) senador(a), com as regras do cartão (`senateCostLatest`/`senateCostFigures`): mês mais
    recente com as três partes (remuneração > 0, equipe, cota do banco) e notas assentadas; média das partes
    sobre esses meses, cada uma arredondada para baixo."""
    if not isinstance(senate_cost, dict) or not isinstance(senate_cost.get('months'), dict):
        return None
    quota = {f'{m["year"]:04d}-{int(m["month"]):02d}': int(round(m['valor'] * 100)) for m in record.get('meses') or []
             if isinstance(m, dict) and isinstance(m.get('year'), int) and isinstance(m.get('month'), int) and isinstance(m.get('valor'), (int, float))}
    complete = {}
    for period, month in senate_cost['months'].items():
        remuneration, office = month.get('remunerationCents'), month.get('officeCents')
        if (costs._cents(remuneration) and remuneration > 0 and costs._cents(office) and period in quota):
            complete[period] = (remuneration, office, quota[period])
    if not complete:
        return None
    as_of = record.get('snapshotAt')
    settled = costs.settled_periods(complete, as_of)
    latest = settled[-1]
    total = sum(complete[latest])
    average = sum(sum(values[i] for p in settled for values in [complete[p]]) // len(settled) for i in range(3))
    caveat = ' (a cota desse mês ainda recebe notas; o valor pode subir)' if _cost_month_unsettled(latest, as_of) else ''
    return (f'Somou {money_cents(total)} em {MONTHS[int(latest[5:7])]}/{latest[:4]}{caveat}; média de {money_cents(average)} por mês '
            f'({len(settled)} {"mês" if len(settled) == 1 else "meses"} com as três partes identificadas). Soma remuneração do(a) senador(a), '
            'equipe do gabinete e cota parlamentar, em valores da época; não compare com o custo de deputados(as).')


def _senate_presence(identifier):
    """Presenças registradas no Diário do Senado, como no cartão: contagem, sem percentual nem faltas."""
    try:
        data = json.loads((SNAPSHOTS_PATH / 'senado-presenca.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    presence = data.get('presenca') if isinstance(data, dict) else None
    items = presence.get('items') if isinstance(presence, dict) else None
    row = next((r for r in items or [] if isinstance(r, dict) and r.get('id') == identifier), None)
    if not row or not isinstance(row.get('presente'), int) or isinstance(row['presente'], bool) or row['presente'] <= 0:
        return None
    sessions = row.get('sessoesEmExercicio')
    span = presence.get('period') if isinstance(presence.get('period'), str) else ''
    if isinstance(sessions, int) and not isinstance(sessions, bool):
        sessions = max(sessions, row['presente'])
        return (f'{row["presente"]} sessões deliberativas com presença registrada no Diário do Senado, de {sessions} com lista validada em que '
                f'estava em exercício{f" ({span})" if span else ""}. Faltas e justificativas não apuradas; sem percentual.')
    return (f'{row["presente"]} sessões deliberativas com presença registrada no Diário do Senado{f" ({span})" if span else ""}. '
            'Faltas e justificativas não apuradas; sem percentual.')


def _cost_month_unsettled(period, as_of):
    """True quando o mês principal ainda não tem os 3 meses de folga (nenhum mês assentado): a cota pode subir."""
    cutoff = settled_cutoff(as_of)
    return cutoff is not None and period > cutoff


def profile_facts(db, identifier):
    """Os números curtos das 3 respostas da ficha, ou None se a pessoa não estiver na base."""
    record = citizen.politician(db, identifier)
    if record is None:
        return None
    person = record['pessoa']
    stamp = (record.get('snapshotAt') or '')[:10]
    # Na página, a data vai em dia/mês/ano, como no app.
    facts = {'person': person, 'snapshotAt': '/'.join(reversed(stamp.split('-'))) if stamp else '', 'lines': []}
    cost = (profiles.profile(identifier) or {}).get('mandateCost') or {}
    latest = _latest_cost_month(cost, record.get('snapshotAt'))
    average = costs.chamber_average(cost, record.get('snapshotAt'))
    if latest and average:
        period, total = latest
        # Os dois números antes da explicação: a descrição para buscadores corta em 160 caracteres.
        caveat = ' (a cota desse mês ainda recebe notas; o valor pode subir)' if _cost_month_unsettled(period, record.get('snapshotAt')) else ''
        facts['lines'].append(('Quanto custa', f'Custou {money_cents(total)} em {MONTHS[int(period[5:7])]}/{period[:4]}{caveat}; '
                               f'média do mandato de {money_cents(average[0])} por mês '
                               f'({month_range(average[1])}). Soma salário bruto, auxílios, cota parlamentar '
                               'e verba do gabinete, em valores da época.'))
    monthly = record.get('mediaMensal')
    if record.get('hasExpenseData') and monthly is not None:
        average = record.get('media')
        period = record.get('mediaPeriodo') or record.get('periodo') or {}
        comparison = ''
        if average:
            difference = monthly / average - 1
            comparison = (' Parecido com a média do cargo.' if abs(difference) < 0.1
                          else f' {sections.half_up(abs(difference) * 100)}% {"acima" if difference > 0 else "abaixo"} da média do cargo ({money(average)}).')
        facts['lines'].append(('Cota parlamentar', f'{money(monthly)} por mês em reembolsos da cota '
                               f'({period_label(period.get("inicio"), period.get("fim"))}, nos meses com notas já assentadas).{comparison}'))
    else:
        facts['lines'].append(('Cota parlamentar', 'Sem notas da cota importadas (ausência de dado não é zero).'))
    house, number = identifier.split(':', 1)
    presence = _chamber_presence(number) if house == 'camara' else None
    if presence:
        facts['lines'].append(('Trabalha', f'Presença no Plenário no mandato ({period_label(presence.get("inicio"), presence.get("fim"))}): {sections.half_up(presence["presente"] / presence["dias"] * 100)}% '
                               f'({presence["presente"]} de {presence["dias"]} dias com sessão deliberativa).'))
    if house == 'senado':
        senate_cost = _senate_cost_line((profiles.profile(identifier) or {}).get('senateCost'), record)
        if senate_cost:
            facts['lines'].insert(0, ('Quanto custa', senate_cost))
        registered = _senate_presence(identifier)
        if registered:
            facts['lines'].append(('Trabalha', registered))
    alerts = record.get('alertas') or []
    coverage = record.get('coberturaAlertas') or []
    evaluated = any((c.get('regra') == 'pico' and c.get('avaliados')) or (c.get('regra') == 'fornecedor' and c.get('avaliado'))
                    for c in coverage)
    if alerts:
        facts['lines'].append(('Picos e concentrações na cota', f'{len(alerts)} {"pico ou concentração" if len(alerts) == 1 else "picos e concentrações"} pelas regras do painel, iguais para todos(as). Não indicam irregularidade.'))
    elif evaluated:
        facts['lines'].append(('Picos e concentrações na cota', 'Nenhum pico ou concentração nos meses do mandato avaliados pelas regras do painel.'))
    elif record.get('hasExpenseData'):
        facts['lines'].append(('Picos e concentrações na cota', 'Dados insuficientes para avaliar picos e concentrações na cota do mandato.'))
    facts['sourceUrl'] = (f'https://www.camara.leg.br/deputados/{number}' if house == 'camara'
                          else f'https://www25.senado.leg.br/web/senadores/senador/-/perfil/{number}')
    facts['alerts'] = alerts
    return facts


def shorten(text, limit=160):
    """Corta no fim de uma palavra, como os buscadores mostram a descrição."""
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(' ', 1)[0].rstrip(' ,.;:(') + '…'


def _escape(value):
    return html.escape(str(value or ''), quote=True)


# ---------------------------------------------------------------- dados estruturados

def organization(origin):
    return {'@type': 'Organization', 'name': SITE_NAME, 'url': origin + '/', 'logo': origin + '/favicon.svg', 'email': CONTACT_EMAIL}


def website_ld(origin):
    return {'@context': 'https://schema.org', '@type': 'WebSite', 'name': SITE_NAME, 'url': origin + '/', 'inLanguage': 'pt-BR',
            'description': DEFAULT_DESCRIPTION, 'publisher': organization(origin)}


def webpage_ld(origin, url, title, description, page_type='WebPage', **extra):
    data = {'@context': 'https://schema.org', '@type': page_type, 'name': title, 'description': description, 'url': url,
            'inLanguage': 'pt-BR', 'isPartOf': {'@type': 'WebSite', 'name': SITE_NAME, 'url': origin + '/'}, 'publisher': organization(origin)}
    data.update(extra)
    return data


def breadcrumb_ld(origin, items):
    return {'@context': 'https://schema.org', '@type': 'BreadcrumbList',
            'itemListElement': [{'@type': 'ListItem', 'position': position, 'name': name, 'item': origin + path}
                                for position, (name, path) in enumerate(items, start=1)]}


# ---------------------------------------------------------------- montagem do HTML

def full_title(title):
    return f'{title} · {SITE_NAME}' if title else f'{SITE_NAME}: quanto custa e como trabalha cada parlamentar'


def _head(title, description, url, origin, json_ld=None, noindex=False):
    page_title = full_title(title)
    image = origin + OG_IMAGE_PATH
    tags = [f'<title>{_escape(page_title)}</title>',
            f'<meta name="description" content="{_escape(description)}">',
            f'<link rel="canonical" href="{_escape(url)}">',
            '<meta property="og:type" content="website">',
            f'<meta property="og:site_name" content="{SITE_NAME}">',
            f'<meta property="og:title" content="{_escape(page_title)}">',
            f'<meta property="og:description" content="{_escape(description)}">',
            f'<meta property="og:url" content="{_escape(url)}">',
            '<meta property="og:locale" content="pt_BR">',
            f'<meta property="og:image" content="{_escape(image)}">',
            f'<meta property="og:image:width" content="{OG_IMAGE_SIZE[0]}">',
            f'<meta property="og:image:height" content="{OG_IMAGE_SIZE[1]}">',
            f'<meta property="og:image:alt" content="{_escape(OG_IMAGE_ALT)}">',
            '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{_escape(page_title)}">',
            f'<meta name="twitter:description" content="{_escape(description)}">',
            f'<meta name="twitter:image" content="{_escape(image)}">']
    if noindex:
        tags.append('<meta name="robots" content="noindex">')
    for item in ([json_ld] if isinstance(json_ld, dict) else json_ld or []):
        # "<" escapado: o JSON não consegue fechar o <script>.
        tags.append('<script type="application/ld+json">' + json.dumps(item, ensure_ascii=False).replace('<', '\\u003c') + '</script>')
    return '\n'.join(tags)


def render(page_html, title, description, url, origin, body='', json_ld=None, noindex=False, marker=None):
    """Troca o <title> do app pelos metadados da página e põe o conteúdo inicial dentro de #app.

    ``marker`` é o endereço que o app compara ao abrir (``data-server-render``): com ele, o app mantém este
    conteúdo na tela enquanto a API não respondeu e não o mostra em outra página."""
    page_html = re.sub(r'<title>.*?</title>', lambda _: _head(title, description, url, origin, json_ld, noindex), page_html, count=1, flags=re.S)
    if body:
        wrapper = f'<div class="view" data-server-render="{_escape(marker or url)}">{body}</div>'
        page_html = page_html.replace('<div class="app" id="app"></div>', f'<div class="app" id="app">{wrapper}</div>', 1)
    return page_html


def _fallback_body(title, description):
    return sections.page_head(SITE_NAME, title or SITE_NAME, description) + '<p class="note">Os dados desta página não estão disponíveis neste momento.</p>'


def section_body(db, path):
    """Conteúdo inicial de uma seção; sem banco, só as páginas que não dependem dele têm conteúdo completo."""
    if path == '/metodologia':
        return sections.methodology_body(SITE_PAGES.get('methodology') or {}, SECTION_PATH_BY_VIEW)
    if path == '/sobre':
        return sections.about_body(SITE_PAGES.get('about') or {})
    if path == '/placar':
        return sections.scoreboard_body()
    if path == '/presenca':
        return sections.attendance_body()
    if path == '/minha-cidade':
        return sections.city_body()
    if path == '/comparar':
        return sections.compare_body()
    if db is None:
        return ''
    if path == '/':
        return sections.home_body(db)
    if path == '/picos-e-concentracoes':
        return sections.alerts_body(db)
    if path == '/politicos':
        return sections.politicians_body(db)
    if path == '/partidos':
        return sections.parties_body(db)
    return ''


def _safe_body(compute, title, description):
    try:
        return compute()
    except BODY_ERRORS as error:
        print(f'Aviso: conteúdo inicial indisponível ({error.__class__.__name__}: {error})', file=sys.stderr, flush=True)
        return _fallback_body(title, description)


def section_page(db, page_html, path, origin):
    _, title, description = SECTIONS[path]
    url = origin + path
    body = _safe_body(lambda: section_body(db, path), title, description)
    if path == '/':
        json_ld = [website_ld(origin)]
    else:
        page_type = 'AboutPage' if path == '/sobre' else 'CollectionPage' if path in ('/politicos', '/picos-e-concentracoes', '/placar', '/presenca') else 'WebPage'
        json_ld = [webpage_ld(origin, url, full_title(title), description, page_type), breadcrumb_ld(origin, [('Início', '/'), (title, path)])]
    return render(page_html, title, description, url, origin, body, json_ld, marker=path)


def party_pair_page(page_html, path, origin):
    """Metadados próprios para o link de comparação; a tela confere as siglas ao carregar."""
    match = PARTY_PAIR_PATH.match(path)
    first, second = (unquote(part).strip()[:30] for part in match.groups())
    title = f'{first} × {second} · Comparar partidos'
    description = (f'{first} e {second} lado a lado: gasto médio de cota, presença, picos e concentrações e como votaram '
                   'na Câmara e no Senado, com dados públicos oficiais.')
    body = (f'<div class="compare-intro"><span class="k">Câmara e Senado</span><h1 class="h ph-t">{_escape(first)} × {_escape(second)}</h1>'
            f'<p class="ph-lead">{_escape(description)}</p></div><p class="note">A comparação é montada no navegador. <a href="/partidos">Ver os partidos</a>.</p>')
    # noindex: o par é escolha de quem compartilha, não uma página para indexar.
    return render(page_html, title, description, origin + path, origin, body, noindex=True, marker=path)


def compare_pair_page(db, page_html, path, origin):
    """Metadados com os dois nomes; quem não está na base aparece como "Ficha não encontrada" no app."""
    match = COMPARE_PAIR_PATH.match(path)
    people, links = [], []
    for prefix, number in (match.group(1, 2), match.group(3, 4)):
        house, role = ROLE_BY_PREFIX[prefix]
        record = citizen.politician(db, f'{house}:{number}')
        person = record['pessoa'] if record else None
        if person is None or person.get('role') != role:
            return 200, section_page(db, page_html, '/comparar', origin), None
        party_place = '-'.join(filter(None, [person.get('party'), person.get('uf')]))
        people.append(f'{person["name"]} ({party_place})' if party_place else person['name'])
        links.append(f'<a class="fchip" href="{profile_path(f"{house}:{number}", person["name"])}">{_escape(person["name"])} →</a>')
    title = f'{people[0]} × {people[1]} · Comparar políticos'
    description = f'{people[0]} e {people[1]} lado a lado: custo, cota, presença, votos, picos e concentrações, com dados públicos oficiais.'
    body = (f'<div class="compare-intro"><span class="k">Comparar</span><h1 class="h ph-t">{_escape(people[0])} × {_escape(people[1])}</h1>'
            f'<p class="ph-lead">{_escape(description)}</p></div><div class="citizen-actions">{"".join(links)}</div>')
    # noindex: o par é escolha de quem compartilha, não uma página para indexar.
    return 200, render(page_html, title, description, origin + path, origin, body, noindex=True, marker=path), None


def profile_page(db, page_html, path, origin):
    """(status, html, redirect) para /deputado/<id>-<nome> e /senador/<id>-<nome>."""
    match = PROFILE_PATH.match(path)
    house, role = ROLE_BY_PREFIX[match.group(1)]
    identifier = f'{house}:{match.group(2)}'
    # Nome e cargo bastam para o 404 e o redirecionamento; os números só são calculados na URL canônica.
    person = citizen._people(db, [identifier]).get(identifier)
    if person is None or person.get('role') != role:
        return 404, render(page_html, 'Ficha não encontrada', DEFAULT_DESCRIPTION, origin + path, origin,
                           sections.not_found_body(), noindex=True, marker=path), None
    canonical = profile_path(identifier, person['name'])
    if path.rstrip('/') != canonical:
        return 301, None, canonical
    facts = profile_facts(db, identifier)
    person = facts['person']
    role_label = ROLE_LABEL[role]
    subtitle = ' · '.join(filter(None, [role_label, person.get('party'), person.get('uf')]))
    description = shorten(f'{subtitle}. ' + ' '.join(text for _, text in facts['lines']))
    party_place = '-'.join(filter(None, [person.get('party'), person.get('uf')]))
    title = f'{person["name"]} ({party_place}): quanto custa e como trabalha' if party_place else f'{person["name"]}: quanto custa e como trabalha'
    url = origin + canonical
    person_ld = {'@context': 'https://schema.org', '@type': 'Person', 'name': person['name'], 'jobTitle': role_label,
                 'url': url, 'sameAs': [facts['sourceUrl']], 'mainEntityOfPage': url}
    if person.get('party'):
        person_ld['affiliation'] = {'@type': 'PoliticalParty', 'name': person['party']}
    json_ld = [person_ld, breadcrumb_ld(origin, [('Início', '/'), ('Políticos', '/politicos'), (person['name'], canonical)])]
    items = ''.join(f'<li><b>{_escape(label)}:</b> {_escape(text)}</li>' for label, text in facts['lines'])
    house_name = 'da Câmara dos Deputados' if house == 'camara' else 'do Senado Federal'
    body = (f'<a class="back" href="/politicos">‹ Todos os políticos</a>'
            f'<article class="seo-summary"><h1>{_escape(person["name"])}</h1><p>{_escape(subtitle)}</p><ul>{items}</ul>'
            f'<p>Fontes: dados públicos oficiais {house_name}. Retrato de {_escape(facts["snapshotAt"] or "data não informada")}. '
            f'<a href="{_escape(facts["sourceUrl"])}" rel="noopener">Página oficial ↗</a>.</p>'
            f'<p>{sections.INDEPENDENCE_NOTE} <a href="/metodologia">Como os números são calculados</a>.</p>'
            f'<div class="citizen-actions"><a class="fchip" href="/comparar">Comparar com outro(a) →</a><a class="fchip" href="/picos-e-concentracoes">Todos os picos e concentrações →</a></div></article>')
    return 200, render(page_html, title, description, url, origin, body, json_ld, marker=profile_path(identifier)), None


def vote_page(page_html, path, origin):
    """Página de uma votação do Placar, com endereço canônico próprio e o conteúdo da decisão no HTML."""
    identifier = VOTE_DETAIL_PATH.match(path).group(1)
    payload = votes.detail(identifier)
    _, section_title, section_description = SECTIONS['/placar']
    if payload is None:
        if identifier in LEGACY_VOTE_IDS:
            # Votação selecionada montada no app a partir dos metadados versionados; sem catálogo, fica fora do índice.
            return 200, render(page_html, section_title, section_description, origin + path, origin, noindex=True), None
        return 404, render(page_html, 'Votação não encontrada', section_description, origin + path, origin,
                           sections.not_found_body(), noindex=True, marker=path), None
    vote = payload['vote']
    title = f'{shorten(vote["title"], 90)} · Placar'
    date = sections.date_br(vote.get('date'))
    description = shorten(f'{vote.get("proposition")}, votado em {date}: {vote.get("decisionLabel")}. {vote.get("summary")}')
    url = origin + path
    about = {'@type': 'Legislation', 'name': vote.get('proposition'), 'legislationIdentifier': vote.get('proposition')}
    proposition_url = (vote.get('sources') or {}).get('proposition')
    if isinstance(proposition_url, str) and proposition_url.startswith('https://'):
        about['url'] = proposition_url
    json_ld = [webpage_ld(origin, url, full_title(title), description, about=about),
               breadcrumb_ld(origin, [('Início', '/'), ('Placar', '/placar'), (vote['title'], path)])]
    body = _safe_body(lambda: sections.vote_body(payload), title, description)
    return 200, render(page_html, title, description, url, origin, body, json_ld, marker=path), None


def not_found_page(page_html, path, origin):
    return render(page_html, 'Página não encontrada', DEFAULT_DESCRIPTION, origin + path, origin, sections.not_found_body(),
                  noindex=True, marker=path)


def page(db, page_html, path, origin):
    """(status, html, redirect) de qualquer endereço de página; ``db`` pode ser None antes da primeira importação."""
    if path in LEGACY_SECTION_PATHS:
        return 301, None, LEGACY_SECTION_PATHS[path]
    if PARTY_PAIR_PATH.match(path):
        return 200, party_pair_page(page_html, path, origin), None
    if path in SECTIONS:
        return 200, section_page(db, page_html, path, origin), None
    if VOTE_DETAIL_PATH.match(path):
        return vote_page(page_html, path, origin)
    if COMPARE_PAIR_PATH.match(path):
        if db is None:
            return 200, section_page(db, page_html, '/comparar', origin), None
        return compare_pair_page(db, page_html, path, origin)
    if PROFILE_PATH.match(path):
        if db is None:
            # Sem banco, a ficha ainda abre pelo app; só não há resumo nem nome.
            return 200, render(page_html, 'Ficha', DEFAULT_DESCRIPTION, origin + path, origin, noindex=True), None
        return profile_page(db, page_html, path, origin)
    return 404, not_found_page(page_html, path, origin), None


# ---------------------------------------------------------------- robots, sitemap, llms

def robots(origin):
    # Buscadores e ferramentas de IA podem ler as páginas e os arquivos do app; a API não precisa ser rastreada.
    return f'User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {origin}/sitemap.xml\n'


def _lastmod(value):
    text = str(value or '')[:10]
    return f'<lastmod>{text}</lastmod>' if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text) else ''


def sitemap(db, origin):
    stamp = db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone()
    data_lastmod = _lastmod(stamp[0] if stamp else None)
    entries = [(origin + path, data_lastmod) for path in SECTIONS]
    for identifier, name in db.execute('''SELECT a.id,a.name FROM authorities a JOIN roster r ON r.authorityId=a.id
            WHERE r.sourceId IN ('camara_deputies_current','senado_senators_current') ORDER BY a.id'''):
        if identifier.split(':', 1)[0] in PREFIX_BY_HOUSE and identifier.split(':', 1)[1].isdigit():
            entries.append((origin + profile_path(identifier, name), data_lastmod))
    for identifier, reviewed_at in votes.sitemap_entries():
        entries.append((f'{origin}/placar/{identifier}', _lastmod(reviewed_at)))
    seen, xml = set(), []
    for url, lastmod in entries:
        if url not in seen:
            seen.add(url)
            xml.append(f'<url><loc>{_escape(url)}</loc>{lastmod}</url>')
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{"".join(xml)}</urlset>\n'


def llms(origin):
    section_lines = '\n'.join(f'- [{title or "Início"}]({origin}{path}): {description}' for path, (_, title, description) in SECTIONS.items())
    return f"""# {SITE_NAME}

> {DEFAULT_DESCRIPTION}

Cada deputado(a) federal e senador(a) tem uma página com endereço próprio, no formato
{origin}/deputado/<id>-<nome> ou {origin}/senador/<id>-<nome>, com o custo de um mês de referência e a média do mandato, cota, presença, votos,
picos e concentrações, sempre com o período dos dados e a data da fotografia. Cada votação do Placar tem endereço próprio,
{origin}/placar/<id>, com a decisão, o que significava votar Sim e Não, o resultado e o voto de cada deputado(a).
A lista completa está no sitemap: {origin}/sitemap.xml. O conteúdo essencial de cada página está no HTML inicial,
sem depender de JavaScript.

## Seções

{section_lines}

## Como ler os números

Os números vêm de dados públicos oficiais (Câmara dos Deputados, Senado Federal, Portal da Transparência,
IBGE, TSE, Tesouro Nacional e Receita Federal) e cada página indica fonte, período e data da coleta. Câmara e
Senado publicam partes diferentes do custo: compare só dentro da mesma Casa. Picos e concentrações seguem regras fixas e
iguais para todos(as) e não indicam irregularidade. Ausência de dado não significa zero. Valores são da época, sem
correção pela inflação. Regras completas: {origin}/metodologia.

## Uso e citação

A base (banco, snapshots e revisões do Placar) é publicada sob CC BY 4.0 nos releases de dados do repositório
{SITE_PAGES.get('repository', '')}; o código é aberto (MIT). Ao citar, use o endereço da página e a data da
fotografia dos dados indicada nela. Projeto pessoal, independente e apartidário; correções: {CONTACT_EMAIL}.
"""
