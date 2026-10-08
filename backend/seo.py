"""Páginas com endereço próprio para buscadores e ferramentas de IA, robots.txt, sitemap.xml e llms.txt.

O app continua o mesmo: o servidor só acrescenta ao HTML montado (dist/index.html) título, descrição,
endereço canônico, dados estruturados e um resumo em texto da ficha dentro de #app. O JavaScript substitui
esse resumo ao abrir a página; robôs que não executam JavaScript leem o resumo. As respostas usam o
mesmo cache do modo de produção, invalidado quando o banco muda.
"""
from __future__ import annotations

import html
import json
import os
import re

from . import citizen, profiles
from .config import SNAPSHOTS_PATH
from .database import fold

SITE_NAME = 'Painel Público'
DEFAULT_DESCRIPTION = ('Quanto custa, se trabalha e se há gastos incomuns: deputados(as) e senadores(as) em dados '
                       'públicos oficiais da Câmara e do Senado, com fonte e data. Projeto pessoal e apartidário.')
# Seções do app com endereço próprio: caminho → (view do app, título, descrição).
SECTIONS = {
    '/': ('home', None, DEFAULT_DESCRIPTION),
    '/alertas': ('alerts', 'Alertas de gastos incomuns na cota parlamentar',
                 'Gastos da cota de deputados(as) e senadores(as) que fogem do padrão pelas mesmas regras para todos(as). Alertas não indicam irregularidade.'),
    '/placar': ('votes', 'Placar das votações da Câmara',
                'Como os(as) deputados(as) votaram nas propostas selecionadas do Plenário, com resumo e fonte oficial.'),
    '/politicos': ('politicians', 'Deputados(as) e senadores(as)',
                   'Busque qualquer deputado(a) federal ou senador(a) e veja custo do mandato, presença, votos e alertas.'),
    '/partidos': ('parties', 'Comparar partidos',
                  'Gasto médio de cota, presença, alertas e votos de dois partidos lado a lado, na Câmara e no Senado.'),
    '/comparar': ('compare', 'Comparar políticos',
                  'Dois(duas) parlamentares lado a lado: custo, cota, alertas, presença e votos.'),
    '/presenca': ('attendance', 'Presença no Plenário da Câmara',
                  'Presença de cada deputado(a) nas sessões deliberativas de 2026, com faltas justificadas e não justificadas.'),
    '/minha-cidade': ('city', 'Minha cidade',
                      'Quem representa sua cidade, emendas parlamentares e contas da prefeitura, com dados do IBGE, TSE e Tesouro.'),
}
PROFILE_PATH = re.compile(r'^/(deputado|senador)/(\d{1,9})(?:-[a-z0-9-]*)?/?$')
ROLE_BY_PREFIX = {'deputado': ('camara', 'deputado'), 'senador': ('senado', 'senador')}
PREFIX_BY_HOUSE = {'camara': 'deputado', 'senado': 'senador'}
ROLE_LABEL = {'deputado': 'Deputado(a) federal', 'senador': 'Senador(a)'}
MONTHS = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']


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


def _chamber_presence(number):
    try:
        rows = json.loads((SNAPSHOTS_PATH / 'presenca.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    row = next((r for r in rows if isinstance(r, dict) and str(r.get('id')) == number), None)
    return row if row and row.get('dias') else None


def profile_facts(db, identifier):
    """Os números curtos das 3 respostas da ficha, ou None se a pessoa não estiver na base."""
    record = citizen.politician(db, identifier)
    if record is None:
        return None
    person = record['pessoa']
    facts = {'person': person, 'snapshotAt': (record.get('snapshotAt') or '')[:10], 'lines': []}
    cost = (profiles.profile(identifier) or {}).get('mandateCost') or {}
    if isinstance(cost.get('monthlyAverageCents'), int) and cost.get('usedMonths'):
        facts['lines'].append(('Quanto custa', f'Custa em média {money_cents(cost["monthlyAverageCents"])} por mês '
                               f'({month_range(cost["usedMonths"])}), somando salário bruto, auxílios, cota parlamentar e verba do gabinete, em valores da época.'))
    if record.get('hasExpenseData'):
        average = record.get('media')
        comparison = ''
        if average:
            difference = record['total'] / average - 1
            comparison = (' Parecido com a média do cargo.' if abs(difference) < 0.1
                          else f' {round(abs(difference) * 100)}% {"acima" if difference > 0 else "abaixo"} da média do cargo ({money(average)}).')
        facts['lines'].append(('Cota parlamentar', f'{money(record["total"])} em reembolsos da cota em 2026.{comparison}'))
    else:
        facts['lines'].append(('Cota parlamentar', 'Sem notas da cota importadas para 2026 (ausência de dado não é zero).'))
    house, number = identifier.split(':', 1)
    presence = _chamber_presence(number) if house == 'camara' else None
    if presence:
        facts['lines'].append(('Trabalha', f'Presença no Plenário em 2026: {round(presence["presente"] / presence["dias"] * 100)}% '
                               f'({presence["presente"]} de {presence["dias"]} dias com sessão deliberativa).'))
    alerts = record.get('alertas') or []
    if record.get('hasExpenseData'):
        facts['lines'].append(('Gastos incomuns', f'{len(alerts)} {"alerta" if len(alerts) == 1 else "alertas"} pelas regras do painel, iguais para todos(as). Alertas não indicam irregularidade.'
                               if alerts else 'Nenhum gasto incomum nas notas da cota de 2026 pelas regras do painel.'))
    facts['sourceUrl'] = (f'https://www.camara.leg.br/deputados/{number}' if house == 'camara'
                          else f'https://www25.senado.leg.br/web/senadores/senador/-/perfil/{number}')
    return facts


def shorten(text, limit=160):
    """Corta no fim de uma palavra, como os buscadores mostram a descrição."""
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(' ', 1)[0].rstrip(' ,.;:(') + '…'


def _escape(value):
    return html.escape(str(value or ''), quote=True)


def _head(title, description, url, json_ld=None, noindex=False):
    full_title = f'{title} · {SITE_NAME}' if title else f'{SITE_NAME}: quanto custa e como trabalha cada parlamentar'
    tags = [f'<title>{_escape(full_title)}</title>',
            f'<meta name="description" content="{_escape(description)}">',
            f'<link rel="canonical" href="{_escape(url)}">',
            '<meta property="og:type" content="website">',
            f'<meta property="og:site_name" content="{SITE_NAME}">',
            f'<meta property="og:title" content="{_escape(full_title)}">',
            f'<meta property="og:description" content="{_escape(description)}">',
            f'<meta property="og:url" content="{_escape(url)}">',
            '<meta property="og:locale" content="pt_BR">',
            '<meta name="twitter:card" content="summary">']
    if noindex:
        tags.append('<meta name="robots" content="noindex">')
    if json_ld:
        # "<" escapado: o JSON não consegue fechar o <script>.
        tags.append('<script type="application/ld+json">' + json.dumps(json_ld, ensure_ascii=False).replace('<', '\\u003c') + '</script>')
    return '\n'.join(tags)


def render(page_html, title, description, url, body='', json_ld=None, noindex=False):
    """Troca o <title> do app pelos metadados da página e põe o resumo dentro de #app."""
    page_html = re.sub(r'<title>.*?</title>', lambda _: _head(title, description, url, json_ld, noindex), page_html, count=1, flags=re.S)
    if body:
        page_html = page_html.replace('<div class="app" id="app"></div>', f'<div class="app" id="app">{body}</div>', 1)
    return page_html


def section_page(page_html, path, origin):
    _, title, description = SECTIONS[path]
    json_ld = None
    if path == '/':
        json_ld = {'@context': 'https://schema.org', '@type': 'WebSite', 'name': SITE_NAME, 'url': origin + '/',
                   'inLanguage': 'pt-BR', 'description': DEFAULT_DESCRIPTION}
    return render(page_html, title, description, origin + path, json_ld=json_ld)


def profile_page(db, page_html, path, origin):
    """(status, html, redirect) para /deputado/<id>-<nome> e /senador/<id>-<nome>."""
    match = PROFILE_PATH.match(path)
    house, role = ROLE_BY_PREFIX[match.group(1)]
    identifier = f'{house}:{match.group(2)}'
    facts = profile_facts(db, identifier)
    if facts is None or facts['person'].get('role') != role:
        return 404, render(page_html, 'Ficha não encontrada', DEFAULT_DESCRIPTION, origin + path, noindex=True), None
    person = facts['person']
    canonical = profile_path(identifier, person['name'])
    if path.rstrip('/') != canonical:
        return 301, None, canonical
    role_label = ROLE_LABEL[role]
    subtitle = ' · '.join(filter(None, [role_label, person.get('party'), person.get('uf')]))
    description = shorten(f'{subtitle}. ' + ' '.join(text for _, text in facts['lines']))
    party_place = '-'.join(filter(None, [person.get('party'), person.get('uf')]))
    title = f'{person["name"]} ({party_place}): quanto custa e como trabalha' if party_place else f'{person["name"]}: quanto custa e como trabalha'
    json_ld = {'@context': 'https://schema.org', '@type': 'Person', 'name': person['name'], 'jobTitle': role_label,
               'url': origin + canonical, 'sameAs': [facts['sourceUrl']]}
    if person.get('party'):
        json_ld['affiliation'] = {'@type': 'PoliticalParty', 'name': person['party']}
    items = ''.join(f'<li><b>{_escape(label)}:</b> {_escape(text)}</li>' for label, text in facts['lines'])
    body = (f'<article class="seo-summary"><h1>{_escape(person["name"])}</h1><p>{_escape(subtitle)}</p><ul>{items}</ul>'
            f'<p>Fontes: dados públicos oficiais da {"Câmara dos Deputados" if house == "camara" else "Senado Federal"}. '
            f'Retrato de {_escape(facts["snapshotAt"] or "data não informada")}. '
            f'<a href="{_escape(facts["sourceUrl"])}">Página oficial</a>.</p>'
            f'<p>{SITE_NAME} é um projeto pessoal e apartidário que reúne dados públicos. Alertas não indicam irregularidade.</p></article>')
    return 200, render(page_html, title, description, origin + canonical, body, json_ld), None


def robots(origin):
    # Buscadores e ferramentas de IA podem ler as páginas; a API não precisa ser rastreada.
    return f'User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {origin}/sitemap.xml\n'


def sitemap(db, origin):
    stamp = db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone()
    lastmod = f'<lastmod>{stamp[0][:10]}</lastmod>' if stamp and stamp[0] else ''
    urls = [origin + path for path in SECTIONS]
    for identifier, name in db.execute('''SELECT a.id,a.name FROM authorities a JOIN roster r ON r.authorityId=a.id
            WHERE r.sourceId IN ('camara_deputies_current','senado_senators_current') ORDER BY a.id'''):
        if identifier.split(':', 1)[0] in PREFIX_BY_HOUSE and identifier.split(':', 1)[1].isdigit():
            urls.append(origin + profile_path(identifier, name))
    entries = ''.join(f'<url><loc>{_escape(url)}</loc>{lastmod}</url>' for url in dict.fromkeys(urls))
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n'


def llms(origin):
    return f"""# {SITE_NAME}

> {DEFAULT_DESCRIPTION}

Cada deputado(a) federal e senador(a) tem uma página com endereço próprio, no formato
{origin}/deputado/<id>-<nome> ou {origin}/senador/<id>-<nome> (lista completa no sitemap).
Os números vêm de dados públicos oficiais (Câmara dos Deputados, Senado Federal, Portal da Transparência,
IBGE, TSE e Tesouro) e cada página indica fonte e data. Alertas seguem regras fixas e iguais para todos(as)
e não indicam irregularidade. Ausência de dado não significa zero.

## Páginas

- [Início]({origin}/): resumo da Câmara e do Senado
- [Políticos]({origin}/politicos): busca de deputados(as) e senadores(as)
- [Alertas]({origin}/alertas): gastos incomuns na cota parlamentar e as regras usadas
- [Placar]({origin}/placar): votações selecionadas do Plenário da Câmara
- [Comparar partidos]({origin}/partidos)
- [Minha cidade]({origin}/minha-cidade)
- [Sitemap]({origin}/sitemap.xml)

## Sobre

Projeto pessoal, independente e apartidário, com código aberto: https://github.com/igor05k/painelpublico
"""
