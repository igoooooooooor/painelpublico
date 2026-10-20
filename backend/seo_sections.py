"""Conteúdo das seções entregue no HTML inicial, para pessoas sem JavaScript e para buscadores e ferramentas de IA.

Cada função devolve o HTML que vai dentro de ``<div class="view">`` em ``#app``: os mesmos números, períodos, fontes
e avisos que o app mostra, calculados pelas mesmas funções do backend (``citizen``, ``votes``, ``cities``) e com os
componentes do design system (``.ph``, ``.card``, ``.k``, ``.muted``, ``.src``). Nada aqui recalcula custo, cota ou
alerta: a camada só formata resultados. O app mantém este conteúdo na tela até ter o equivalente carregado da API.
"""
from __future__ import annotations

import html
import json
import math

from . import citizen, cities, votes
from .config import SNAPSHOTS_PATH

SITE_NAME = 'Painel Público'
MONTHS_SHORT = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
MONTHS_LONG = ['', 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro',
               'outubro', 'novembro', 'dezembro']
ROLE_LABEL = {'deputado': 'Deputado(a) federal', 'senador': 'Senador(a)'}
PREFIX_BY_HOUSE = {'camara': 'deputado', 'senado': 'senador'}
HOME_ALERT_COUNT = 8
ALERT_PAGE_SIZE = 12
SCOREBOARD_MAX_PAGES = 10
VOTE_TYPE_NAMES = {'PL': 'Projeto de lei', 'PLP': 'Projeto de lei complementar', 'PEC': 'Proposta de emenda à Constituição'}
VOTE_OUTCOMES = {'approved': 'Aprovado nesta votação', 'rejected': 'Rejeitado nesta votação', 'not_approved': 'Não aprovado nesta votação'}
SEGMENT_OUTCOMES = {'kept': 'Trecho mantido', 'removed': 'Trecho retirado', 'approved': 'Aprovada', 'rejected': 'Rejeitada'}
URGENCY_OUTCOMES = {'approved': 'Urgência aprovada', 'rejected': 'Urgência rejeitada', 'not_approved': 'Urgência não aprovada'}
VOTE_CHOICE_GROUPS = ['Sim', 'Não', 'Abstenção', 'Obstrução', 'Presidiu']
INDEPENDENCE_NOTE = (f'{SITE_NAME} é um projeto pessoal e apartidário que reúne dados públicos oficiais. '
                     'Alertas não indicam irregularidade. Dado ausente não significa zero.')


def esc(value):
    return html.escape('' if value is None else str(value), quote=True)


def pt_int(value):
    return f'{int(value):,}'.replace(',', '.')


def money(value):
    """R$ com separadores brasileiros e sem centavos."""
    return 'R$ ' + f'{value:,.0f}'.replace(',', '.')


def half_up(value):
    """Arredonda como Math.round no app (meio para cima), não como round() do Python (meio para o par)."""
    return int(math.floor(value + 0.5))


def short_amount(value):
    """'R$ 1,2 mi' ou 'R$ 253 mil', como formatCitizenAmount no app."""
    if abs(value) >= 1e6:
        return 'R$ ' + f'{value / 1e6:.1f}'.replace('.', ',').removesuffix(',0') + ' mi'
    if abs(value) >= 1e3:
        return f'R$ {pt_int(half_up(value / 1e3))} mil'
    return 'R$ ' + (f'{value:.2f}'.replace('.', ',') if value else '0')


def thousands(value):
    return pt_int(half_up(value / 1e3))


def pct(part, whole):
    return half_up(part / whole * 100) if whole else 0


def date_br(value):
    text = str(value or '')
    if len(text) < 10 or text[4] != '-' or text[7] != '-':
        return ''
    return f'{text[8:10]}/{text[5:7]}/{text[:4]}'


def month_label(value):
    """'fev/2023' a partir de 'AAAA-MM' ou 'AAAA-MM-DD'; vazio se inválido."""
    text = str(value or '')
    if len(text) < 7 or not text[:4].isdigit() or not text[5:7].isdigit() or not 1 <= int(text[5:7]) <= 12:
        return ''
    return f'{MONTHS_SHORT[int(text[5:7])]}/{text[:4]}'


def period_text(period):
    """'fev/2023 a set/2026', como na home."""
    first, last = month_label((period or {}).get('inicio')), month_label((period or {}).get('fim'))
    return f'{first} a {last}' if first and last else 'período não informado'


def span_text(start, end):
    """'fev/2023–set/2026', como citizenQuotaPeriod no app."""
    first, last = month_label(start), month_label(end)
    if not first or not last:
        return ''
    return first if first == last else f'{first}–{last}'


def person_name(name):
    text = str(name or '')
    return text.title() if text == text.upper() else text


def profile_href(identifier):
    house, _, number = str(identifier or '').partition(':')
    if house not in PREFIX_BY_HOUSE or not number.isdigit():
        return None
    return f'/{PREFIX_BY_HOUSE[house]}/{number}'


def role_description(person):
    parts = [ROLE_LABEL.get(person.get('role'), 'Parlamentar'), person.get('party'), person.get('uf')]
    text = ' · '.join(esc(part) for part in parts if part)
    return text + (' · fora da lista atual' if person.get('foraDaLista') else '')


def person_link(person, css_class='citizen-who'):
    href = profile_href(person.get('id'))
    inner = f'<span><b>{esc(person_name(person.get("name")))}</b><small>{role_description(person)}</small></span>'
    return f'<a class="{css_class}" href="{href}">{inner}</a>' if href else f'<span class="{css_class}">{inner}</span>'


def page_head(kicker, title, lead=''):
    return (f'<header class="ph"><span class="k">{esc(kicker)}</span><h1 class="h ph-t">{esc(title)}</h1>'
            + (f'<p class="ph-lead">{esc(lead)}</p>' if lead else '') + '</header>')


def snapshot_note(stamp):
    return f' Fotografia da base: {date_br(stamp)}.' if date_br(stamp) else ''


# ---------------------------------------------------------------- alertas

def alert_kind(alert):
    if alert.get('tipo') == 'pico':
        return 'type-peak', 'Mês acima da referência'
    if alert.get('tipo') == 'fornecedor':
        label = 'Passagens intermediadas' if alert.get('intermediacao') else 'Concentração em fornecedor'
        return 'type-supplier', label + (' · parcial' if alert.get('parcial') else '')
    return 'info', 'Para conferir'


def alert_card(alert):
    """Cartão compacto do alerta: tipo, pessoa, título, a frase com os números e o contexto do ano."""
    kind, label = alert_kind(alert)
    year = str(alert.get('periodo') or '')[:4]
    month = alert.get('mes')
    when = f'{MONTHS_SHORT[month]}/{year}' if alert.get('tipo') == 'pico' and isinstance(month, int) and 1 <= month <= 12 else f'em {year}'
    context = alert.get('contexto') or {}
    sources = alert.get('fontesOficiais') or []
    source_links = ', '.join(f'<a href="{esc(source["url"])}" rel="noopener">{esc(source["label"])} ↗</a>' for source in sources
                             if isinstance(source, dict) and str(source.get('url', '')).startswith('https://'))
    return (f'<article class="card citizen-alert" data-kind="{kind}">'
            f'<div class="citizen-top"><span class="citizen-chip {kind}"><i></i>{esc(label)}</span><span class="muted">{esc(when)}</span></div>'
            f'{person_link(alert.get("pessoa") or {})}'
            f'<h3 class="citizen-title">{esc(alert.get("titulo"))}</h3>'
            f'<p class="citizen-statement">{esc(alert.get("frase"))}</p>'
            + (f'<p class="citizen-context">{esc(context["frase"])}</p>' if context.get('frase') else '')
            + (f'<p class="muted">Detalhamento oficial: {source_links}.</p>' if source_links else '')
            + '</article>')


def alerts_body(db):
    radar = citizen.radar(db, {'pageSize': str(ALERT_PAGE_SIZE)})
    counts = radar.get('contagem') or {}
    span = radar.get('periodo') or {}
    scope = span_text(span.get('inicio'), span.get('fim'))
    total = radar.get('total') or 0
    rules = [('pico', 'type-peak', 'Mês acima da referência',
              'O gasto do mês é pelo menos 1,75 vez a referência da própria pessoa (mediana dos 12 meses anteriores), com pelo menos R$ 10 mil de diferença, e fica acima do gasto típico dos(as) colegas.'),
             ('fornecedor', 'type-supplier', 'Concentração em fornecedor',
              'Pelo menos 50% e R$ 30 mil das notas do ano foram para um mesmo fornecedor. Inclui passagens intermediadas por agência.')]
    rule_cards = ''.join(f'<article class="card alerts-rule" data-kind="{kind}"><b>{esc(title)}</b><span>{esc(text)}</span>'
                         f'<b class="mono alerts-rule-count">{pt_int(counts.get(key, 0))}</b></article>' for key, kind, title, text in rules)
    items = radar.get('itens') or []
    status = (f'{pt_int(total)} {"alerta" if total == 1 else "alertas"} no mandato{f" ({esc(scope)})" if scope else ""} · '
              f'dos mais recentes aos mais antigos{f"; os {len(items)} mais recentes abaixo" if total > len(items) else ""}')
    return (f'<div class="alerts-page"><section class="alerts-hero"><div class="alerts-intro">'
            f'<h1 class="h ph-t">Alertas</h1>'
            f'<p class="ph-lead">Meses acima da referência e concentração em fornecedor nas notas da cota de deputados(as) e senadores(as), '
            f'pelas mesmas regras para todos(as). Os alertas não indicam irregularidade: confira sempre as notas na fonte oficial.</p>'
            f'<a class="alerts-how-link" href="/metodologia#methodology-alerts">Como as regras funcionam →</a></div>'
            f'<div class="alerts-rules">{rule_cards}</div></section>'
            f'<p class="muted alerts-status" role="status">{status}</p>'
            f'<div class="alerts-grid">{"".join(alert_card(alert) for alert in items) or "<p class=\"note\">Nenhum alerta na base atual.</p>"}</div>'
            f'<section class="card citizen-how" id="alerts-how"><span class="k">Como funciona</span>'
            f'<p><b>Mês acima da referência:</b> o gasto do mês passou de 1,75 vez a mediana dos 12 meses anteriores da própria pessoa. '
            f'A avaliação começa em fevereiro de 2024, quando há 12 meses de mandato para comparar.</p>'
            f'<p><b>Concentração em fornecedor:</b> metade ou mais do dinheiro do ano foi para a mesma empresa, ano a ano desde 2023.</p>'
            f'<p class="muted">Pode ter explicação, como um evento no estado ou um contrato fixo. Os dados vêm das notas que a Câmara e o Senado publicam. '
            f'Na Câmara, as passagens aéreas emitidas pela agência da Câmara (SIGEPA) entram pela página de bilhetes da cota, porque o arquivo aberto das notas deixou de trazê-las em ago/2025.'
            f'{snapshot_note(radar.get("snapshotAt"))}</p></section></div>')


# ---------------------------------------------------------------- home

def _home_cost_card(summary):
    chamber = (summary.get('custoMensal') or {}).get('deputado') or {}
    senate = (summary.get('custoMensal') or {}).get('senador') or {}
    average = chamber.get('media')
    if not isinstance(average, (int, float)):
        return ('<section class="card home-cost"><span class="home-cost-label">Um(a) deputado(a) custa, em média, por mês</span>'
                '<div class="home-cost-value">Sem dados</div><p class="muted">O custo mensal ainda não foi calculado para a lista atual.</p>'
                '<a class="more" href="/politicos">Ver a lista de políticos →</a></section>')
    low, high = chamber.get('minimo'), chamber.get('maximo')
    excluded = chamber.get('foraDaFaixa') if isinstance(chamber.get('foraDaFaixa'), int) else 0
    out_of_range = (f' O menor e o maior deixam de fora {excluded} {"deputado(a)" if excluded == 1 else "deputados(as)"} com verba de '
                    'gabinete publicada pela Câmara como R$ 0,00 em algum mês, que entram só na média.') if excluded > 0 else ''
    has_range = all(isinstance(value, (int, float)) for value in (low, high)) and high > low
    range_html = ''
    if has_range:
        position = (average - low) / (high - low) * 100
        range_html = (f'<div class="home-range" role="img" aria-label="Média de R$ {thousands(average)} mil, entre R$ {thousands(low)} mil e R$ {thousands(high)} mil">'
                      f'<span class="home-range-track"><i style="left:{position:.1f}%"></i></span>'
                      f'<span class="home-range-ends"><span>menor R$ {thousands(low)} mil</span><span>maior R$ {thousands(high)} mil</span></span></div>')
    senate_html = (f'<div class="home-cost-senate"><span>Senador(a), em média</span><b>R$ {thousands(senate["media"])} mil/mês</b></div>'
                   if isinstance(senate.get('media'), (int, float)) else '')
    return (f'<section class="card home-cost"><span class="home-cost-label">Um(a) deputado(a) custa, em média, por mês</span>'
            f'<div class="home-cost-value">R$ {thousands(average)}<small> mil</small></div>'
            f'<p class="home-cost-parts">Salário, auxílios, cota parlamentar e verba do gabinete, somados.</p>{range_html}{senate_html}'
            f'<p class="home-cost-note">Média de {chamber.get("comCusto", 0)} deputados(as) com custo identificado, dos {chamber.get("total", 0)} da lista atual, '
            f'nos meses com todas as partes publicadas e as notas da cota já assentadas (3 meses de folga); valores da época. Na Câmara, ficam fora 13º, encargos do gabinete e apartamento funcional. '
            f'Câmara e Senado publicam partes diferentes do custo: compare só dentro da mesma Casa.{out_of_range}</p>'
            f'<a class="more" href="/politicos">Ver quanto custa cada um(a) →</a></section>')


def _home_stats(summary, alerts_total):
    quota = (summary.get('reembolsos') or {}).get('deputado') or {}
    categories = [category for category in summary.get('categoriasCamara') or [] if category.get('valor', 0) > 0]
    positive_total = sum(category['valor'] for category in categories)
    stats = []
    if isinstance(quota.get('total'), (int, float)):
        stats.append((short_amount(quota['total']), f'de cota usada pelos deputados(as) da lista, {esc(period_text(quota.get("periodo")))}'))
    if isinstance(alerts_total, int):
        stats.append((pt_int(alerts_total), 'alertas na cota pelas regras do painel; não indicam irregularidade'))
    if categories and positive_total > 0:
        stats.append((f'{half_up(categories[0]["valor"] / positive_total * 100)}%', f'da cota foi para {esc(categories[0]["nome"].lower())}'))
    if not stats:
        return ''
    return '<dl class="home-stats">' + ''.join(f'<div><dt>{label}</dt><dd>{value}</dd></div>' for value, label in stats) + '</dl>'


def _home_top_card(summary):
    ranking = summary.get('topCamara') or []
    top = ranking[:5]
    quota = (summary.get('reembolsos') or {}).get('deputado') or {}
    biggest = max([person.get('gastoMensal') or 0 for person in top] + [1])
    rows = ''.join(
        f'<li><a href="{profile_href(person.get("id")) or "/politicos"}"><span class="home-rank">{index}</span>'
        f'<span class="home-rank-name"><b>{esc(person.get("nome"))}</b><small>{esc(person.get("partido") or "")} · {esc(person.get("uf") or "")}</small></span>'
        f'<span class="home-rank-value">R$ {thousands(person.get("gastoMensal") or 0)} mil</span>'
        f'<i style="width:{max(0, person.get("gastoMensal") or 0) / biggest * 100:.2f}%"></i></a></li>'
        for index, person in enumerate(top, start=1))
    return (f'<section class="card home-panel"><div class="home-panel-head"><h2 class="h">Quem mais usa a cota</h2><span class="muted">Média mensal nos meses com notas já assentadas</span></div>'
            + (f'<ol class="home-ranking">{rows}</ol>' if rows else '<p>Sem reembolsos importados para ordenar.</p>')
            + f'<span class="muted">Os cinco maiores valores entre {len(ranking)} deputados(as) com dados. {esc(period_text(quota.get("mediaPeriodo") or quota.get("periodo")))}. Valores altos não indicam irregularidade.</span>'
            f'<a class="more" href="/politicos">Ver a lista completa →</a></section>')


def _home_categories_card(summary):
    categories = summary.get('categoriasCamara') or []
    quota = (summary.get('reembolsos') or {}).get('deputado') or {}
    if not categories:
        return '<section class="card home-panel"><h2 class="h">Para onde vai a cota</h2><p>Sem despesas importadas para os(as) deputados(as) da lista.</p></section>'
    biggest = max([category['valor'] for category in categories] + [1])
    positive_total = sum(category['valor'] for category in categories if category['valor'] > 0)
    rows = ''.join(
        f'<li><span>{esc(category["nome"])}</span><b>{short_amount(category["valor"]) if abs(category["valor"]) >= 1e3 else money(category["valor"])}'
        + (f' <small>{f"{category["valor"] / positive_total * 100:.1f}".replace(".", ",").removesuffix(",0")}%</small>' if category['valor'] > 0 and positive_total else '')
        + f'</b><i style="width:{max(0.5, max(0, category["valor"]) / biggest * 100):.2f}%"></i></li>' for category in categories)
    total = f' · {short_amount(quota["total"])} no mandato' if isinstance(quota.get('total'), (int, float)) else ''
    return (f'<section class="card home-panel"><div class="home-panel-head"><h2 class="h">Para onde vai a cota</h2><span class="muted">{len(categories)} categorias{total}</span></div>'
            f'<ul class="home-category-list">{rows}</ul>'
            f'<span class="muted">{esc(period_text(quota.get("periodo")))}. Todos os reembolsos importados dos(as) deputados(as) da lista, preservando estornos. Percentuais consideram categorias com saldo positivo; estornos permanecem no total líquido.</span></section>')


def home_body(db):
    summary = citizen.summary(db)
    radar = citizen.radar(db, {'pageSize': str(HOME_ALERT_COUNT)})
    alerts = radar.get('itens') or []
    span = radar.get('periodo') or {}
    scope = span_text(span.get('inicio'), span.get('fim'))
    hero = ('<div class="home-intro"><h1 class="home-title">Quanto custa cada parlamentar — e como ele trabalha.</h1>'
            '<p class="home-lead">Gastos, presença e votos de deputados(as) e senadores(as), a partir dos dados oficiais da Câmara e do Senado.</p>'
            '<form class="home-search" action="/politicos" method="get" role="search"><label for="home-search-input">Busque um nome, partido ou estado</label>'
            '<div class="home-search-box"><input id="home-search-input" name="q" type="search" maxlength="120" autocomplete="off" placeholder="Ex.: Tabata, PL, Minas Gerais"><button type="submit">Buscar</button></div></form>'
            '<div class="home-shortcuts"><a href="/minha-cidade">Minha cidade</a><a href="/comparar">Comparar dois políticos</a><a href="/placar">Placar das votações</a></div></div>')
    alerts_section = ''
    if alerts:
        alerts_section = (f'<section class="citizen-home"><div class="citizen-head"><div><h2 class="h">Alertas da cota</h2>'
                          f'<span class="muted">Meses acima da referência e concentração em fornecedor nas notas do mandato{f" ({esc(scope)})" if scope else ""} '
                          f'de deputados(as) e senadores(as), pelas mesmas regras para todos(as), dos mais recentes aos mais antigos. Não indicam irregularidade.</span></div></div>'
                          f'<div class="carousel citizen-carousel">{"".join(alert_card(alert) for alert in alerts)}</div>'
                          f'<a class="opt citizen-cta" href="/alertas">Ver os {pt_int(radar.get("total") or 0)} alertas</a></section>')
    return (f'<section class="home-hero">{hero}{_home_cost_card(summary)}</section>'
            f'{_home_stats(summary, radar.get("total"))}{alerts_section}'
            f'<div class="home-pair">{_home_top_card(summary)}{_home_categories_card(summary)}</div>'
            f'<span class="src">Listas e reembolsos: Câmara dos Deputados e Senado Federal.{snapshot_note(summary.get("snapshotAt"))} '
            f'Presença e votações têm a cobertura indicada em suas telas.</span>')


# ---------------------------------------------------------------- políticos

def roster(db):
    """Quem está na lista oficial atual de cada Casa: (id, nome, cargo, partido, UF), em ordem alfabética por Casa."""
    rows = db.execute('''SELECT a.id,a.name,a.role,a.party,a.uf FROM authorities a JOIN roster r ON r.authorityId=a.id
            WHERE r.sourceId IN (?,?) AND a.role IN ('deputado','senador') ORDER BY a.role,a.name,a.id''',
                      (citizen.CURRENT['deputado'], citizen.CURRENT['senador']))
    seen, people = set(), []
    for identifier, name, role, party, uf in rows:
        if identifier in seen or profile_href(identifier) is None:
            continue
        seen.add(identifier)
        people.append({'id': identifier, 'name': name, 'role': role, 'party': party, 'uf': uf})
    return people


def directory_list(people):
    items = ''.join(f'<li><a href="{profile_href(person["id"])}">{esc(person_name(person["name"]))}</a>'
                    f'<small>{esc(" · ".join(part for part in (person.get("party"), person.get("uf")) if part))}</small></li>' for person in people)
    return f'<ul class="seo-directory">{items}</ul>'


def politicians_body(db):
    people = roster(db)
    deputies = [person for person in people if person['role'] == 'deputado']
    senators = [person for person in people if person['role'] == 'senador']
    senate_note = (' O Senado tem 81 cadeiras; registros extras no retrato da fonte podem refletir suplentes em transição.'
                   if len(senators) > 81 else '')
    return (page_head('Deputados(as) e senadores(as)', 'Políticos', 'Busque qualquer um(a) e veja quanto custa por mês, com os alertas.')
            + f'<div class="citizen-roster-summary" role="status"><b>{len(deputies)} deputados(as)</b> · <b>{len(senators)} registros do Senado</b></div>'
            '<div class="citizen-actions"><a class="fchip" href="/comparar">Comparar políticos(as) →</a><a class="fchip" href="/partidos">Comparar partidos →</a>'
            '<a class="fchip" href="/presenca">Presença dos deputados →</a></div>'
            f'<section class="card wide"><h2 class="h">Câmara dos Deputados</h2><p class="muted">{len(deputies)} deputados(as) federais na lista oficial atual, em ordem alfabética. '
            f'Cada ficha mostra o custo de um mês de referência, a média do mandato, notas da cota, presença, votos e alertas.</p>{directory_list(deputies)}</section>'
            f'<section class="card wide"><h2 class="h">Senado Federal</h2><p class="muted">{len(senators)} registros na lista oficial atual.{senate_note}</p>{directory_list(senators)}</section>'
            '<span class="src">Fonte: listas oficiais da Câmara dos Deputados e do Senado Federal. A busca mostra só deputados(as) federais e senadores(as) com mandato em curso; '
            'eleitos(as) em 2026 aparecem a partir da posse, em 1º de fevereiro de 2027. Custo por mês na lista: média do mandato nos meses disponíveis com as partes exigidas e as notas assentadas. Na ficha, essa média é contexto para o custo de um mês específico; '
            'Câmara e Senado não publicam as mesmas partes, então compare só dentro da mesma Casa.</span>')


# ---------------------------------------------------------------- presença

def presence_rows():
    try:
        rows = json.loads((SNAPSHOTS_PATH / 'presenca.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    valid = []
    for row in rows:
        if not isinstance(row, dict) or not str(row.get('id', '')).isdigit():
            continue
        counts = [row.get(key) for key in ('presente', 'falta', 'justificadas', 'dias')]
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts) or counts[3] <= 0 or sum(counts[:3]) != counts[3]:
            continue
        valid.append(row)
    return valid


def attendance_body():
    rows = presence_rows()
    if not rows:
        return (page_head('Câmara · mandato', 'Presença no Plenário', 'Dados de presença indisponíveis neste recorte.')
                + '<p class="src">Fonte: página de presença em Plenário de cada deputado(a) na Câmara; nenhum registro está disponível neste recorte.</p>')
    average = sum(row['presente'] / row['dias'] for row in rows) / len(rows)
    first_start = min((row['inicio'] for row in rows if row.get('inicio')), default=None)
    full = sum(1 for row in rows if row['presente'] == row['dias'] and (not first_start or row.get('inicio') == first_start))
    below_half = sum(1 for row in rows if row['presente'] / row['dias'] < 0.5)
    sessions = max(row['dias'] for row in rows)
    starts = sorted(row['inicio'] for row in rows if row.get('inicio'))
    ends = sorted(row['fim'] for row in rows if row.get('fim'))
    period = span_text(starts[0], ends[-1]) if starts and ends else ''
    ordered = sorted(rows, key=lambda row: (row['presente'] / row['dias'], str(row.get('nome', ''))))

    def absences(row):
        parts = []
        if row.get('justificadas'):
            parts.append(f'{row["justificadas"]} {"falta justificada" if row["justificadas"] == 1 else "faltas justificadas"}')
        if row.get('falta'):
            parts.append(f'{row["falta"]} {"falta" if row["falta"] == 1 else "faltas"}')
        return ' · '.join(parts) or 'Nenhuma ausência'

    items = ''.join(
        f'<li><a class="attendance-row" href="/deputado/{row["id"]}"><span class="attendance-who"><b>{esc(row.get("nome"))}</b>'
        f'<small>{esc(row.get("partido") or "")} · {esc(row.get("uf") or "")}{f" · desde {esc(span_text(row["inicio"], row["inicio"]))}" if first_start and row.get("inicio") and row["inicio"] > first_start else ""}</small></span>'
        f'<span class="attendance-value"><b class="mono{" warn" if row["presente"] / row["dias"] < 0.5 else ""}">{pct(row["presente"], row["dias"])}%</b>'
        f'<small class="mono">{row["presente"]} de {row["dias"]}</small></span>'
        f'<span class="attendance-bar"><small>{esc(absences(row))}</small></span></a></li>' for row in ordered)
    stat = lambda value, label: f'<div class="card attendance-stat"><b class="mono">{value}</b><span>{label}</span></div>'
    return (f'<div class="attendance-page"><section class="attendance-hero"><div class="attendance-intro">'
            f'<span class="k">Câmara · {esc(period or "mandato")}</span><h1 class="h ph-t">Presença no Plenário</h1>'
            f'<p class="ph-lead">Quantos dos {sessions} dias com sessão deliberativa do Plenário cada deputado(a) foi, no mandato atual{f" ({esc(period)})" if period else ""}.</p></div>'
            f'<div class="attendance-summary"><div class="attendance-stats">{stat(f"{half_up(average * 100)}%", "presença média")}'
            f'{stat(full, "não faltaram nenhum dia, com o mandato inteiro")}{stat(below_half, "foram a menos da metade")}</div>'
            f'<p class="muted">Média dos dados disponíveis: dos dias com sessão, em média, entre os(as) {len(rows)} deputados(as) com dados de presença disponíveis.</p></div></section>'
            f'<div class="attendance-results"><span class="muted" role="status">{len(rows)} deputados(as), dos(as) menos aos(às) mais presentes</span><ol class="attendance-list">{items}</ol></div>'
            f'<p class="src attendance-source">Fonte: página de presença em Plenário de cada deputado(a) na Câmara, {sessions} dias com sessão deliberativa no mandato atual'
            f'{f" ({esc(period)})" if period else ""}. Falta justificada é qualquer motivo publicado pela Câmara (missão autorizada, licença, atestado, decisão da Mesa). Quem assumiu no meio do mandato tem menos dias na conta e aparece com o mês de início.</p></div>')


# ---------------------------------------------------------------- Placar

def vote_date(value):
    text = str(value or '')
    return f'{int(text[8:10])}/{MONTHS_SHORT[int(text[5:7])]}' if len(text) >= 10 and text[5:7].isdigit() and 1 <= int(text[5:7]) <= 12 else 'data não informada'


def vote_outcome(item):
    if item.get('kind') == 'urgency':
        return item.get('decisionLabel') or URGENCY_OUTCOMES.get(item.get('outcome'), 'Resultado não informado')
    if item.get('kind') == 'segment' or item.get('parent'):
        return item.get('decisionLabel') or SEGMENT_OUTCOMES.get(item.get('outcome'), 'Resultado não informado')
    related = item.get('related') or {}
    if related.get('relation') == 'approvedAfter' and item.get('outcome') != 'approved':
        return 'Versão rejeitada · projeto aprovado em seguida'
    return VOTE_OUTCOMES.get(item.get('outcome'), 'Resultado não informado')


# Mesmos nomes de SCOREBOARD_SEGMENT_KINDS em frontend/scripts/scoreboard-view.js.
SEGMENT_KINDS = {'destaque': 'Votação em separado de um trecho', 'emenda': 'Emenda', 'emendas': 'Emendas votadas em bloco',
                 'emenda_redacao': 'Emenda de redação', 'dispositivos': 'Dispositivos votados em bloco'}


def abstention(tally):
    """(contagem, nota) das abstenções, como scoreboardAbstention no app: publicada; zero pelo relatório nominal
    quando Sim + Não fecham o total; senão desconhecida."""
    value = tally.get('abstention')
    if isinstance(value, int) and not isinstance(value, bool):
        return value, ''
    parts = [tally.get(key) for key in ('yes', 'no', 'total')]
    if all(isinstance(part, int) and not isinstance(part, bool) for part in parts) and parts[0] + parts[1] == parts[2]:
        return 0, 'nenhuma no relatório nominal'
    return None, 'não publicada'


def count(value):
    return pt_int(value) if isinstance(value, int) and not isinstance(value, bool) else '—'


def vote_card(item):
    tally = item.get('tally') or {}
    href = f'/placar/{esc(item["id"])}'
    return (f'<article class="card scoreboard-card"><div class="scoreboard-card-body">'
            f'<p class="scoreboard-kicker"><span class="k">{esc(item.get("proposition"))} · {esc(vote_date(item.get("date")))}</span></p>'
            f'<h3 class="h"><a href="{href}">{esc(item.get("title"))}</a></h3>'
            + (f'<p class="muted scoreboard-summary">{esc(item["summary"])}</p>' if item.get('summary') else '')
            + f'</div><div class="scoreboard-card-result"><p class="scoreboard-outcome" data-outcome="{esc(item.get("outcome") or "")}">{esc(vote_outcome(item))}</p>'
            f'<p class="scoreboard-meta"><span><b>{count(tally.get("yes"))}</b> sim</span><span><b>{count(tally.get("no"))}</b> não</span>'
            f'<span>{"abst. não publicada" if abstention(tally)[0] is None else count(abstention(tally)[0]) + " abst."}</span></p>'
            f'<a class="more" href="{href}">Ver decisão e votos →</a></div></article>')


def scoreboard_items():
    """Todas as votações do texto principal do catálogo, página a página (a API pagina em até 24)."""
    first = votes.listing({'pageSize': '24'})
    if not first.get('available'):
        return first, []
    items = list(first.get('items') or [])
    for page in range(2, min(first.get('pageCount') or 1, SCOREBOARD_MAX_PAGES) + 1):
        items.extend(votes.listing({'pageSize': '24', 'page': str(page)}).get('items') or [])
    return first, items


def scoreboard_body():
    listing, items = scoreboard_items()
    if not listing.get('available'):
        return (page_head('Câmara · Plenário', 'Placar', 'Consulte as votações selecionadas e suas fontes oficiais.')
                + '<p class="scoreboard-fallback" role="status">O catálogo ampliado está indisponível neste momento.</p>'
                '<span class="src">Fonte: Câmara dos Deputados · dados abertos do Plenário.</span>')
    period = listing.get('period') or {}
    coverage = listing.get('coverage') or {}
    start, end = str(period.get('start') or ''), str(period.get('end') or '')
    year = start[:4] if start[:4] == end[:4] and start[:4].isdigit() else ''
    years = f'{start[:4]}{"" if start[:4] == end[:4] else "–" + end[2:4]}' if start[:4].isdigit() and end[:4].isdigit() else ''
    published = coverage.get('publishedCount')
    stats = ('<dl class="scoreboard-stats">'
             + (f'<div><dt>Votações conferidas</dt><dd>{count(published)}</dd></div>' if isinstance(published, int) else '')
             + '<div><dt>Tipos de proposta</dt><dd>PL · PLP · PEC</dd></div>'
             + (f'<div><dt>Período</dt><dd>{esc(years)}</dd></div>' if years else '') + '</dl>')
    groups, current = [], None
    for item in items:
        key = str(item.get('date') or '')[:7]
        if current is None or current[0] != key:
            current = (key, [])
            groups.append(current)
        current[1].append(item)
    month_name = lambda key: f'{MONTHS_LONG[int(key[5:7])].capitalize()} de {key[:4]}' if len(key) == 7 and key[5:7].isdigit() else 'Data não informada'
    sections = ''.join(f'<section class="scoreboard-month"><h2>{esc(month_name(key))} <span>{len(group)} {"votação" if len(group) == 1 else "votações"}</span></h2>'
                       f'{"".join(vote_card(item) for item in group)}</section>' for key, group in groups)
    timeframe = f'em {year}' if year else 'no período consultado'
    return (page_head('Câmara · Plenário', 'Placar', 'Veja o que foi decidido sobre o texto principal dos projetos e como cada deputado votou.')
            + stats
            + f'<div class="card scoreboard-coverage"><h2 class="h">O que é o Placar</h2>'
            f'<p>Aqui estão votações da Câmara {timeframe} em que os deputados votaram o texto principal de um projeto de lei ou de uma mudança na Constituição, com o voto de cada um registrado.</p>'
            f'<p><strong>{count(published)} votações nominais conferidas</strong>, uma a uma, nas fontes oficiais. Elas não são tudo o que a Câmara votou {"no ano" if year else "no período"}. '
            f'Um projeto aprovado aqui ainda pode não ter virado lei.</p>'
            + (f'<p>Período consultado: {date_br(start)} a {date_br(end)}.</p>' if date_br(start) and date_br(end) else '')
            + '<p><a href="/metodologia#methodology-scoreboard">Como montamos este Placar e seus limites →</a></p></div>'
            f'<div class="scoreboard-results">{sections or "<p class=\"card scoreboard-empty\">Nenhuma votação publicada.</p>"}</div>'
            '<span class="src">Fonte: Câmara dos Deputados · dados abertos do Plenário. Dado ausente não significa zero.</span>')


def vote_sources(sources, notes):
    labels = [('vote', 'Registro da votação'), ('rollCall', 'Relatório nominal'), ('text', 'Texto votado'), ('decision', 'Decisão na Câmara'),
              ('request', 'Requerimento de urgência'), ('proposition', 'Ficha da proposição'), ('referenceProposition', 'Proposição de referência nos Dados Abertos')]
    links = ''.join(f'<li><a href="{esc(sources[key])}" rel="noopener">{label} ↗</a></li>' for key, label in labels
                    if isinstance((sources or {}).get(key), str) and sources[key].startswith('https://'))
    note_html = ''.join(f'<p class="muted">{esc(note)}</p>' for note in notes or [] if isinstance(note, str))
    missing = '<p class="muted">O link seguro para o texto exato votado ainda não está disponível.</p>' if (sources or {}).get('text', '') is None else ''
    return (f'<section class="card scoreboard-sources"><span class="k">Fontes oficiais</span>'
            + (f'<ul class="scoreboard-source-links">{links}</ul>' if links else '<p class="muted">Links oficiais não informados para esta votação.</p>')
            + missing + note_html + '</section>')


def vote_participants(participants):
    rows = [person for person in participants or [] if isinstance(person, dict)]
    if not rows:
        return ('<section class="card scoreboard-voters"><span class="k">Votos individuais</span>'
                '<p class="muted">A lista individual não está disponível para esta votação.</p></section>')
    group_of = lambda person: person.get('vote') if person.get('vote') in VOTE_CHOICE_GROUPS else 'Outro registro' if person.get('vote') else 'Escolha não informada'
    sections = []
    for label in VOTE_CHOICE_GROUPS + ['Outro registro', 'Escolha não informada']:
        group = [person for person in rows if group_of(person) == label]
        if not group:
            continue
        items = []
        for person in group:
            href = profile_href(person.get('id')) if str(person.get('id', '')).startswith('camara:') else None
            meta = ' · '.join(part for part in ((person.get('vote') if label == 'Outro registro' else ''), person.get('party'), person.get('uf')) if part)
            name = f'<a href="{href}">{esc(person.get("name"))}</a>' if href else f'<span>{esc(person.get("name"))}</span>'
            items.append(f'<li>{name}{f"<small>{esc(meta)}</small>" if meta else ""}</li>')
        sections.append(f'<section class="scoreboard-voter-group"><h3>{label} <span>{pt_int(len(group))}</span></h3><ul>{"".join(items)}</ul></section>')
    return (f'<section class="card scoreboard-voters"><span class="k">Como votou cada deputado</span>'
            f'<p class="muted">{pt_int(len(rows))} registros nesta votação.</p>{"".join(sections)}</section>')


def vote_party_totals(party_totals):
    rows = [row for row in party_totals or [] if isinstance(row, dict)]
    if not rows:
        return ''
    total = lambda row: sum(max(0, row.get(key) or 0) for key in ('yes', 'no', 'other'))
    rows.sort(key=lambda row: (-total(row), str(row.get('party') or '')))
    items = ''.join(f'<li><b>{esc(row.get("party") or "Partido não informado")}</b>'
                    f'<span>Sim {count(row.get("yes"))} · Não {count(row.get("no"))} · Outros {count(row.get("other"))}</span></li>' for row in rows)
    return (f'<section class="card scoreboard-parties"><span class="k">Resumo por partido</span>'
            f'<p class="muted">Partido no registro desta votação, do maior para o menor.</p><ul class="scoreboard-party-totals">{items}</ul></section>')


def vote_body(payload):
    """Página de uma votação do Placar: decisão, significado de Sim e Não, resultado, votos por partido e por pessoa, fontes."""
    vote = payload.get('vote') or {}
    tally = vote.get('tally') or {}
    parent = vote.get('parent') or {}
    is_urgency = parent.get('relation') == 'urgency' or bool(vote.get('request') and vote.get('textStatus'))
    is_segment = bool(parent) or is_urgency
    kind_name = ('Pedido de urgência' if is_urgency else SEGMENT_KINDS.get(vote.get('kind'), 'Decisão sobre um trecho') if is_segment
                 else VOTE_TYPE_NAMES.get(vote.get('type'), ''))
    label = f'{vote["request"]["label"]} · ' if is_urgency and isinstance(vote.get('request'), dict) and vote['request'].get('label') else ''
    themes = ''.join(f'<span class="pill">{esc(theme.get("label"))}</span>' for theme in vote.get('themes') or [] if isinstance(theme, dict) and theme.get('label'))
    parent_html = ''
    if parent.get('id') and parent.get('title'):
        parent_html = (f'<section class="card scoreboard-related" role="note"><span class="k">Votação do texto principal</span>'
                       f'<p>{"Este pedido de urgência precede a votação" if is_urgency else "Este trecho faz parte da votação"} do texto “{esc(parent["title"])}”'
                       f'{f" ({esc(vote_outcome(parent).lower())} nessa votação)" if parent.get("outcome") else ""}, em {date_br(parent.get("date"))}.</p>'
                       f'<a class="more" href="/placar/{esc(parent["id"])}">Ver a votação do texto →</a></section>')
    pec_note = '<p class="muted scoreboard-pec-note">PEC precisa de 308 votos favoráveis (3/5 da Câmara) em cada um dos dois turnos.</p>' if vote.get('type') == 'PEC' and not is_segment else ''
    children = ''
    for key, title, child_outcomes in (('urgencies', 'Pedidos de urgência votados antes', URGENCY_OUTCOMES), ('segments', 'Decisões sobre trechos', SEGMENT_OUTCOMES)):
        rows = [child for child in vote.get(key) or [] if isinstance(child, dict) and child.get('id')]
        if rows:
            children += (f'<section class="card wide"><span class="k">{title}</span><ul class="scoreboard-segment-list">'
                         + ''.join(f'<li class="scoreboard-segment"><a href="/placar/{esc(child["id"])}">{esc(child.get("title") or child.get("decisionLabel") or child["id"])}</a> · '
                                   f'{esc(child.get("decisionLabel") or child_outcomes.get(child.get("outcome"), "Resultado não informado"))}</li>' for child in rows)
                         + '</ul></section>')
    return (f'<a class="back" href="/placar">‹ Voltar ao Placar</a>'
            f'<header class="scoreboard-detail-head"><p class="scoreboard-kicker">'
            + (f'<span class="scoreboard-type-name">{esc(kind_name)}</span>' if kind_name else '')
            + f'<span class="k">{esc(label)}{esc(vote.get("proposition") or "Proposição não informada")} · votado em {esc(vote_date(vote.get("date")))}</span></p>'
            f'<h1 class="h scoreboard-detail-title">{esc(vote.get("title") or "Título não informado")}</h1>'
            f'<p class="scoreboard-themes"><span class="scoreboard-outcome" data-outcome="{esc(vote.get("outcome") or "")}">{esc(vote_outcome(vote))}</span>{themes}</p></header>'
            f'<section class="card scoreboard-decision"><span class="k">O que foi decidido</span><h2 class="h">{esc(vote.get("decisionLabel") or "Decisão não informada")}</h2>'
            + (f'<p>{esc(vote["summary"])}</p>' if vote.get('summary') else '<p class="muted">Resumo não informado para esta versão.</p>')
            + f'<div class="scoreboard-meaning"><div><span class="k">Sim significava</span><p>{esc(vote.get("yesMeaning") or "Informação não disponível neste registro.")}</p></div>'
            f'<div><span class="k">Não significava</span><p>{esc(vote.get("noMeaning") or "Informação não disponível neste registro.")}</p></div></div>'
            f'{pec_note}<p class="muted">O resultado é o desta votação, não a situação atual da proposta.</p></section>'
            f'{parent_html}'
            f'<section class="card scoreboard-result"><span class="k">Resultado desta votação</span><dl class="scoreboard-tally">'
            f'<div><dt>Sim</dt><dd>{count(tally.get("yes"))}</dd></div><div><dt>Não</dt><dd>{count(tally.get("no"))}</dd></div>'
            f'<div><dt>Abstenção</dt><dd>{count(abstention(tally)[0])}</dd>{f"<small>{abstention(tally)[1]}</small>" if abstention(tally)[1] else ""}</div>'
            f'<div><dt>Total</dt><dd>{count(tally.get("total"))}</dd></div></dl>'
            f'<p class="muted">{esc(vote_outcome(vote))}. O total soma Sim, Não e Abstenção.</p></section>'
            f'{vote_participants(payload.get("participants")) if payload.get("participantsAvailable", True) else vote_participants([])}'
            f'{vote_party_totals(payload.get("partyTotals"))}{children}{vote_sources(vote.get("sources"), vote.get("dataNotes"))}'
            f'<span class="src">Fonte: Câmara dos Deputados · revisão em {date_br(vote.get("reviewedAt")) or "data não informada"}. '
            'O resultado descreve esta votação, sem indicar a situação atual da proposta.</span>')


# ---------------------------------------------------------------- partidos, comparar, cidade

def parties_body(db):
    data = citizen.parties(db)
    items = data.get('itens') or []
    rows = []
    for party in items:
        chamber, senate = party.get('deputado') or {}, party.get('senador') or {}
        average = chamber.get('media')
        alerts = (chamber.get('alertas') or 0) + (senate.get('alertas') or 0)
        rows.append(f'<tr><th scope="row">{esc(party.get("sigla"))}</th><td>{pt_int(party.get("membros") or 0)}</td>'
                    f'<td>{pt_int(chamber.get("membros") or 0)}</td><td>{pt_int(senate.get("membros") or 0)}</td>'
                    f'<td>{money(average) if isinstance(average, (int, float)) else "sem notas"}</td><td>{pt_int(alerts)}</td></tr>')
    table = ('<div class="seo-table-wrap"><table class="seo-table"><caption class="muted">Lista oficial atual; cota média mensal por deputado(a), nos meses com notas já assentadas, desde fev/2023. '
             'Sem notas importadas, a média fica em branco (ausência não é zero).</caption>'
             '<thead><tr><th scope="col">Partido</th><th scope="col">Registros</th><th scope="col">Câmara</th><th scope="col">Senado</th>'
             '<th scope="col">Cota média/mês (Câmara)</th><th scope="col">Alertas</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>') if rows else '<p class="note">Sem partidos na lista atual.</p>'
    return ('<div class="compare-intro"><span class="k">Câmara e Senado</span><h1 class="h ph-t">Partidos lado a lado</h1>'
            '<p class="ph-lead">Registros da lista, gastos com a cota, presença e votos de dois partidos. Compare a média, não o total: partidos maiores têm mais gente.</p></div>'
            f'<section class="card wide"><h2 class="h">Partidos na lista atual</h2>{table}'
            '<p class="muted">Com JavaScript, escolha dois partidos para ver cota média, presença, alertas e como as bancadas votaram, lado a lado, e compartilhe a comparação.</p></section>'
            f'<span class="src">Gastos pelas notas da cota, com as passagens aéreas emitidas pela agência da Câmara. Alertas não indicam irregularidade. Partidos maiores tendem a ter mais variação interna; '
            f'compare a média, não o total.{snapshot_note(data.get("snapshotAt"))}</span>')


def compare_body():
    return ('<div class="compare-intro"><span class="k">Comparar</span><h1 class="h ph-t">Lado a lado</h1>'
            '<p class="ph-lead">Gastos, alertas, presença e votos de dois(duas) políticos(as) na mesma tela.</p></div>'
            '<section class="card wide"><span class="k">Como funciona</span>'
            '<p>Escolha dois(duas) deputados(as) ou senadores(as) e veja custo médio por mês, cota, alertas, presença e como votaram nas votações do Placar, lado a lado. '
            'Câmara e Senado não publicam as mesmas partes do custo: a comparação direta de valores só vale entre pessoas da mesma Casa.</p>'
            '<p class="muted">A escolha das pessoas usa a busca do app. Sem JavaScript, abra a lista de políticos e consulte cada ficha.</p>'
            '<div class="citizen-actions"><a class="fchip" href="/politicos">Lista de deputados(as) e senadores(as) →</a><a class="fchip" href="/partidos">Comparar partidos →</a></div></section>')


def city_body():
    search = cities.search('', limit=1)
    total = search.get('total') or 0
    source = search.get('source') or {}
    coverage = f'{pt_int(total)} municípios do IBGE' if total else 'base de municípios indisponível neste momento'
    return (page_head('Onde você mora', 'Minha cidade', 'Digite sua cidade e veja quem governa, quanto a prefeitura gasta por morador e quanto dinheiro de emendas chegou.')
            + f'<section class="card wide"><span class="k">O que você encontra</span><ul class="seo-plain-list">'
            '<li><b>Quem governa:</b> prefeito(a), vice e vereadores(as) eleitos(as), governador(a) e os(as) deputados(as) federais e senadores(as) do estado, com link para cada ficha.</li>'
            '<li><b>Quanto a prefeitura gasta:</b> despesa por morador, saúde e educação, comparadas com cidades de porte parecido (contas anuais do Siconfi).</li>'
            '<li><b>Emendas parlamentares:</b> valores empenhados e pagos para o município, por ano e por autor(a) (Portal da Transparência).</li></ul>'
            f'<p class="muted">Cobertura: {coverage}. A busca por nome precisa de JavaScript; cada indicador informa a fonte, o ano e, quando a fonte não publicou o dado, diz isso em vez de mostrar zero.</p></section>'
            '<span class="src">Fontes: IBGE (municípios e população), TSE (resultados eleitorais), Tesouro Nacional/Siconfi (contas anuais) e Portal da Transparência (emendas).'
            + (f' Lista de municípios: {esc(source.get("label") or source.get("sourceUrl") or "IBGE")}.' if source else '') + '</span>')


# ---------------------------------------------------------------- páginas institucionais

def _answer(part):
    if isinstance(part, list):
        return '<ul>' + ''.join(f'<li>{esc(item)}</li>' for item in part) + '</ul>'
    return f'<p>{esc(part)}</p>'


def _links(links):
    if not links:
        return ''
    return '<p class="methodology-links">' + ''.join(
        f'<a href="{esc(url)}"{"" if str(url).startswith(("/", "mailto:")) else " rel=\"noopener\""}>{esc(label)}{"" if str(url).startswith(("/", "mailto:")) else " ↗"}</a>'
        for label, url in links) + '</p>'


def methodology_body(page, section_paths):
    sections = page.get('sections') or []
    toc = ''.join(f'<a href="#methodology-{esc(section["id"])}">{esc(section["title"])}</a>' for section in sections)
    blocks = []
    for section in sections:
        questions = ''.join(f'<details class="methodology-question"><summary>{esc(question["question"])}</summary><div class="methodology-answer">'
                            f'{"".join(_answer(part) for part in question.get("answer") or [])}{_links(question.get("links"))}</div></details>'
                            for question in section.get('questions') or [])
        view = section.get('view') or []
        view_link = f'<a class="methodology-view-link" href="{esc(section_paths.get(view[0], "/"))}">{esc(view[1])} →</a>' if len(view) == 2 else ''
        blocks.append(f'<section class="methodology-section" id="methodology-{esc(section["id"])}"><header><h2 class="h">{esc(section["title"])}</h2><p>{esc(section.get("lead"))}</p></header>'
                      f'<div class="methodology-questions">{questions}</div>{view_link}</section>')
    return (f'<div class="methodology-page"><section class="methodology-intro"><h1 class="h ph-t">{esc(page.get("title"))}</h1><p class="ph-lead">{esc(page.get("lead"))}</p>'
            f'<p class="card methodology-notice"><span><b>Alertas não indicam irregularidade.</b> {esc(str(page.get("notice") or "").removeprefix("Alertas não indicam irregularidade. "))}</span></p></section>'
            f'<div class="methodology-layout"><nav class="methodology-toc" aria-label="Nesta página"><span class="k">Nesta página</span>{toc}</nav>'
            f'<div class="methodology-sections">{"".join(blocks)}</div></div></div>')


def about_body(page):
    blocks = ''.join(f'<section class="methodology-section" id="about-{esc(section["id"])}"><header><h2 class="h">{esc(section["title"])}</h2></header>'
                     f'<div class="methodology-answer">{"".join(_answer(paragraph) for paragraph in section.get("paragraphs") or [])}{_links(section.get("links"))}</div></section>'
                     for section in page.get('sections') or [])
    return (f'<div class="methodology-page"><section class="methodology-intro"><h1 class="h ph-t">{esc(page.get("title"))}</h1><p class="ph-lead">{esc(page.get("lead"))}</p></section>'
            f'<div class="methodology-sections">{blocks}</div></div>')


# ---------------------------------------------------------------- erro

def not_found_body():
    return (page_head('Erro 404', 'Página não encontrada', 'O endereço não existe ou mudou. Os caminhos do site estão abaixo.')
            + '<section class="card wide"><span class="k">Talvez você procure</span><ul class="seo-plain-list">'
            '<li><a href="/politicos">Deputados(as) e senadores(as)</a>: custo, cota, presença, votos e alertas de cada ficha.</li>'
            '<li><a href="/alertas">Alertas da cota</a>: meses acima da referência e concentração em fornecedor.</li>'
            '<li><a href="/placar">Placar das votações</a>: como cada deputado(a) votou no texto principal dos projetos.</li>'
            '<li><a href="/minha-cidade">Minha cidade</a>: quem governa, contas da prefeitura e emendas.</li>'
            '<li><a href="/metodologia">Metodologia</a> e <a href="/sobre">sobre o projeto</a>.</li></ul></section>')
