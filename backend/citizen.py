"""Camada do cidadão: traduz a base e os sinais do radar em linguagem simples.

Não recalcula nem altera os sinais de public_store.py. Só reúne o que cada alerta
precisa para ser entendido sem conhecimento técnico: quem, quanto, comparado com o quê,
e onde conferir. Rotas no server.py: /api/c/resumo, /api/c/radar, /api/c/politicos, /api/c/politico/<id>
e /api/c/gastos.csv?id=<id>.
"""
import csv
import io
import json
import re
from statistics import median

from . import public_store as store
from . import costs
from .alert_rules import MANDATE_START, NOT_EVALUATED as NOT_EVALUATED_TEXT
from .config import HOUSING_COMPLEMENT_KIND

ROLES = ('deputado', 'senador')
ROLE_LABELS = {'deputado': 'deputados(as)', 'senador': 'senadores(as)'}
CURRENT = {'deputado': 'camara_deputies_current', 'senador': 'senado_senators_current'}
# Meses com notas da cota (authority_totals, alias t). Mês sem nota é ausência de dado, não gasto zero;
# assim licenças e trocas de suplente não diluem a média.
MONTH_COUNT = 't.monthCount'
# Média mensal da cota: compara deputados (mandato desde fev/2023) e senadores (2026) no mesmo critério.
MONTHLY = f't.amountCents*1.0/{MONTH_COUNT}'
# Notas detalhadas (ano corrente) mais as notas enxutas dos anos anteriores do mandato (visão quota_history).
QUOTA_MONTHS = '''(SELECT authorityId,year,month,category,kind,amountCents,1 count FROM expenses
    UNION ALL SELECT authorityId,year,month,category,kind,amountCents,1 FROM quota_history)'''
MONTHS = ['', 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto',
         'setembro', 'outubro', 'novembro', 'dezembro']

# Nomes curtos para as categorias da Câmara e do Senado (que usam textos diferentes).
CATEGORIES = [
    (r'divulga', 'Divulgação'),
    # Câmara: "PASSAGEM AÉREA - ..."; Senado: "Passagens aéreas, aquáticas e terrestres nacionais".
    (r'passage(m|ns) a[ée]reas?|a[ée]reas?$', 'Passagens aéreas'),
    (r'aeronave', 'Fretamento de avião'),
    (r've[íi]culos? automotor|loca[çc][ãa]o.*ve[íi]culo', 'Aluguel de carro'),
    (r'combust', 'Combustível'),
    (r'locomo[çc][ãa]o', 'Transporte, hospedagem e alimentação'),
    (r'escrit[óo]rio|alugu?el de im[óo]ve', 'Escritório'),
    (r'consultori|assessori|trabalhos t[ée]cnicos', 'Consultoria'),
    (r'hospedagem', 'Hospedagem'),
    (r'aliment', 'Alimentação'),
    (r'telefon', 'Telefone'),
    (r'seguran[çc]a', 'Segurança'),
    (r'material de consumo|postais|publica[çc]', 'Material e correio'),
    (r't[áa]xi|ped[áa]gio|estacionamento', 'Táxi e pedágio'),
    (r'terrestres|mar[íi]timas|fluviais', 'Ônibus e barco'),
    (r'moradia', 'Moradia'),
]


def category_name(name):
    text = (name or '').lower()
    for pattern, short_name in CATEGORIES:
        if re.search(pattern, text):
            return short_name
    return (name or 'Outros').strip().rstrip('.').capitalize()


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


def _people(db, ids):
    """Nome, cargo, partido, UF e metadados da fotografia oficial.

    `current` vem da lista oficial mais recente (tabela roster). Registros que só existem no arquivo de
    despesas (sem partido) herdam partido/UF do membro atual de mesmo nome, quando existe; os demais
    ficam marcados como fora da lista atual, sem perder o histórico.
    """
    ids = list(dict.fromkeys(i for i in ids if i))
    if not ids:
        return {}
    marks = ','.join('?' * len(ids))
    out = {r['id']: r for r in rows(db, f'SELECT id,name,role,party,uf,sourceId,sourceUrl,position,employmentStatus FROM authorities WHERE id IN ({marks})', ids)}
    roster_sources = (CURRENT['deputado'], CURRENT['senador'])
    members = {r[0] for r in db.execute(f'SELECT authorityId FROM roster WHERE sourceId IN (?,?) AND authorityId IN ({marks})', (*roster_sources, *ids))}
    for r in out.values():
        r['current'] = r['id'] in members
    missing = [r for r in out.values() if not r['current']]
    if missing:
        current_members = {}
        for r in rows(db, '''SELECT a.name,a.role,a.party,a.uf FROM authorities a JOIN roster m ON m.authorityId=a.id
                WHERE m.sourceId IN (?,?) AND a.party IS NOT NULL''', roster_sources):
            current_members[(r['role'], store.fold(r['name']))] = r
        for r in missing:
            match = None if r.get('party') else current_members.get((r['role'], store.fold(r['name'])))
            if match:
                r['party'], r['uf'] = match['party'], match['uf']
                r['name'] = match['name']
                r['current'] = True
            else:
                r['foraDaLista'] = True
    return out

def _monthly_series(db, authority, source, year):
    """Gasto por mês num ano: notas detalhadas (ano corrente) ou histórico do mandato (anos anteriores)."""
    rs = rows(db, '''SELECT month, SUM(c) c FROM (
            SELECT month, amountCents c FROM expenses INDEXED BY expense_authority WHERE authorityId=:a AND sourceId=:s AND year=:y AND kind='reembolso'
            UNION ALL SELECT month, amountCents FROM quota_history WHERE authorityId=:a AND sourceId=:s AND year=:y AND kind='reembolso')
        GROUP BY month ORDER BY month''', {'a': authority, 's': source, 'y': year})
    return {r['month']: r['c'] / 100 for r in rs}


def _context(db, person, authority, source, year, cache, total=None):
    """Escala do ano: um alerta de quem gasta pouco não pode parecer igual ao de quem gasta muito."""
    if '__averages' not in cache:
        cache['__averages'] = _averages(db)
    # A média do cargo é mensal (meses com notas); compara com a média mensal da pessoa no mesmo ano.
    average = (cache['__averages'].get(person.get('role')) or {}).get('media')
    series = _monthly_series(db, authority, source, int(year))
    if total is None:
        total = sum(series.values())
    months = len(series)
    if not average or not total or not months:
        return None
    monthly = total / months
    difference = monthly / average - 1
    group_label = ROLE_LABELS.get(person.get('role'), 'parlamentares')
    if abs(difference) < 0.1:
        comparison = f'parecido com a média mensal dos(as) {group_label}'
    else:
        comparison = (f'{round(abs(difference) * 100)}% {"mais" if difference > 0 else "menos"} que a média mensal '
                      f'dos(as) {group_label} ({store_money(average)})')
    return {'total': total, 'mediaMensal': monthly, 'meses': months, 'media': average, 'diferenca': difference,
            'frase': f'Em {year}, gastou {store_money(total)} na cota, {store_money(monthly)} por mês em média, {comparison}.'}


# Tipos de despesa do CEAPS → número usado nas páginas de detalhamento do portal do Senado
# (www6g.senado.leg.br/transparencia/sen/<senador>/ceaps/<n>/...), conferido em 8/10/2026.
SENATE_CEAPS_PAGES = (
    ('Aluguel de imóveis', 1), ('Aquisição de material de consumo', 2), ('Locomoção, hospedagem', 3),
    ('Contratação de consultorias', 4), ('Divulgação da atividade parlamentar', 5),
    ('Passagens aéreas', 8), ('Serviços de Segurança Privada', 9),
)
SENATE_DOCUMENT_NOTE = 'Análise dos registros publicados; imagem do documento não disponível nesta base.'


def _senate_page(category):
    for prefix, number in SENATE_CEAPS_PAGES:
        if (category or '').startswith(prefix):
            return number
    return None


def senate_sources(db, authority, year, months=None, supplier=None):
    """Links do detalhamento oficial do Senado para os registros de um alerta, por tipo de despesa."""
    code = authority.split(':', 1)[1] if authority.startswith('senado:') else None
    if not code or not code.isdigit():
        return []
    filters, args = ['authorityId=?', 'year=?', "kind='reembolso'"], [authority, year]
    if months:
        filters.append(f'month IN ({",".join("?" * len(months))})'); args += months
    if supplier:
        filters.append('supplierKey=?'); args.append(supplier)
    where = ' AND '.join(filters)
    # O filtro vai em cada lado da união: assim as duas tabelas usam o índice por pessoa e ano.
    found = rows(db, f'''SELECT DISTINCT category,month FROM (
            SELECT category,month FROM expenses INDEXED BY expense_authority WHERE {where}
            UNION ALL SELECT category,month FROM quota_history WHERE {where}) ORDER BY month,category''', args + args)
    links, seen = [], set()
    base = f'https://www6g.senado.leg.br/transparencia/sen/{code}/ceaps'
    for r in found:
        page = _senate_page(r['category'])
        if page is None:
            continue
        label = category_name(r['category'])
        if months:
            key = (page, r['month'])
            url = f'{base}/{page}/detalhe/?mesAno={r["month"]:02d}/{year}'
            label = f'{label} · {MONTHS[r["month"]][:3]}/{year}'
        else:
            key = (page,)
            url = f'{base}/{page}/?ano={year}'
            label = f'{label} · {year}'
        if key not in seen:
            seen.add(key)
            links.append({'label': label, 'url': url})
    return links


def _alert_period_label(detail):
    """'jan–set/2026' com os meses observados, para dizer de onde saiu um cálculo parcial."""
    first, last = (detail.get('monthsObserved') or [None, None])
    year = detail.get('year')
    if not first or not last:
        return str(year)
    short = [m[:3] for m in MONTHS]
    return f'{short[first]}/{year}' if first == last else f'{short[first]}–{short[last]}/{year}'


def _alert(db, signal, people, totals_cache):
    """Um sinal do radar em linguagem simples, lido do resultado gravado pela regra (sem recalcular).

    Mantém o texto técnico original em `criterio`. Nenhum campo classifica gravidade.
    """
    person = people.get(signal['authorityId'], {'name': signal.get('authorityName')})
    detail = json.loads(signal['detail']) if signal.get('detail') else {}
    base = {'id': signal['id'], 'tipo': signal['type'], 'valor': signal['amountCents'] / 100, 'periodo': signal['period'],
            'pessoa': {k: person.get(k) for k in ('id', 'name', 'role', 'party', 'uf', 'foraDaLista')}, 'criterio': signal['description'],
            'regra': detail.get('ruleVersion'), 'parcial': bool(detail.get('partial')), 'coletadoEm': detail.get('fetchedAt')}
    authority, source = signal['authorityId'], signal['sourceId']
    if authority.startswith('senado:') and detail:
        base['fontesOficiais'] = senate_sources(db, authority, detail['year'],
                                                months=[m['month'] for m in detail.get('months', [])] or None,
                                                supplier=detail.get('supplierKey'))
        base['notaDocumento'] = SENATE_DOCUMENT_NOTE
    if signal['type'] == 'pico' and detail:
        marked = detail['months']
        first = marked[0]
        year = detail['year']
        title = (f'Mês acima da referência: {MONTHS[first["month"]]} de {year}' if len(marked) == 1
                 else f'Meses acima da referência: {MONTHS[first["month"]]} a {MONTHS[marked[-1]["month"]]} de {year}')
        # Base publicada: 12 meses anteriores; resultados antigos (base anual) mantêm o texto da época.
        window = 'dos 12 meses anteriores' if detail.get('baseline', 'year') != 'year' else 'dos meses anteriores'
        times = lambda value: f'{value:.1f}'.replace('.', ',')
        if len(marked) >= 3:
            # Sequência longa: uma frase só; o valor e a referência de cada mês ficam no gráfico do cartão.
            low, high = min(m['multiple'] for m in marked), max(m['multiple'] for m in marked)
            sentence = (f'De {MONTHS[first["month"]]} a {MONTHS[marked[-1]["month"]]} de {year}, a cota ficou acima da referência '
                        f'em {len(marked)} meses seguidos, de {times(low)} a {times(high)} vezes a mediana {window} de cada mês. '
                        f'Nesses meses, somou {store_money(sum(m["valueCents"] for m in marked) / 100)}.')
        else:
            sentence = ' '.join(
                f'Em {MONTHS[m["month"]]}, a cota somou {store_money(m["valueCents"] / 100)}; a referência {window} '
                f'era {store_money(m["referenceCents"] / 100)} ({times(m["multiple"])} vezes).'
                for m in marked)
        base.update({'referencia': first['referenceCents'] / 100, 'vezes': first['multiple'], 'mes': first['month'], 'ano': year,
                     'base': detail.get('baseline', 'year'),
                     'meses': [{'ano': year, 'mes': m['month'], 'valor': m['valueCents'] / 100, 'referencia': m['referenceCents'] / 100,
                                'vezes': m['multiple']} for m in marked],
                     'piso': detail['floorCents'] / 100 if detail.get('floorCents') is not None else None,
                     'serie': [{'ano': p.get('year', year), 'mes': p['month'],
                                'valor': p['valueCents'] / 100 if p['valueCents'] is not None else None,
                                'estado': p.get('status')} for p in detail['series']],
                     'contexto': _context(db, person, authority, source, year, totals_cache),
                     'fimDeAno': detail.get('yearEndMonths') or [],
                     'titulo': title, 'frase': sentence, 'fonte': person.get('sourceUrl')})
    elif signal['type'] == 'fornecedor' and detail:
        year = detail['year']
        supplier_rows = rows(db, 'SELECT name,cnpj FROM suppliers WHERE key=?', (detail['supplierKey'],))
        category = rows(db, '''SELECT category FROM (
                SELECT category,amountCents FROM expenses INDEXED BY expense_authority WHERE authorityId=:a AND supplierKey=:k AND year=:y
                UNION ALL SELECT category,amountCents FROM quota_history WHERE authorityId=:a AND supplierKey=:k AND year=:y)
            GROUP BY category ORDER BY SUM(amountCents) DESC LIMIT 1''', {'a': authority, 'k': detail['supplierKey'], 'y': year})
        supplier_name = (supplier_rows[0]['name'] if supplier_rows else detail.get('supplierName') or 'um único fornecedor').strip()
        period = _alert_period_label(detail)
        partial = ' Período parcial: o ano ainda pode receber notas.' if detail.get('partial') else ''
        base.update({'fornecedor': supplier_name, 'cnpj': supplier_rows[0]['cnpj'] if supplier_rows else None,
                     'total': detail['totalCents'] / 100, 'parte': detail['share'], 'notas': detail['records'],
                     'categoria': category_name(category[0]['category']) if category else None,
                     'periodoObservado': period, 'mesesComNotas': detail.get('monthsWithNotes'),
                     'intermediacao': detail.get('intermediation'),
                     'titulo': ('Pagamentos de passagens intermediados por uma agência' if detail.get('intermediation')
                                else 'Concentração em fornecedor') + (' (período parcial)' if detail.get('partial') else ''),
                     'frase': _supplier_sentence(detail, supplier_name, period) + partial,
                     'fornecedorKey': detail['supplierKey'],
                     'contexto': _context(db, person, authority, source, year, totals_cache, detail['totalCents'] / 100)})
    elif signal['type'] == 'nota':
        e = rows(db, '''SELECT e.date,e.category,e.documentUrl,s.name supplier FROM expenses e LEFT JOIN suppliers s ON s.key=e.supplierKey
            WHERE e.id=?''', (signal['id'][len('nota:'):],))
        e = e[0] if e else {}
        base.update({'fornecedor': (e.get('supplier') or '').strip() or None, 'categoria': category_name(e.get('category')),
                     'data': e.get('date'), 'documento': store.safe_url(e.get('documentUrl')) if e.get('documentUrl') else None,
                     'titulo': f'Nota de {store_money(base["valor"])}',
                     'frase': f'Uma única nota de {category_name(e.get("category")).lower()}' + (f', paga a {e.get("supplier").strip()}.' if e.get('supplier') else '.')})
    return base


def _supplier_sentence(detail, supplier_name, period):
    """Porcentagem sempre com os valores absolutos e a cobertura (meses com notas) que a sustentam."""
    months = detail.get('monthsWithNotes')
    coverage = f' ({months} {"mês" if months == 1 else "meses"} com notas)' if months else ''
    share = f'{store_money(detail["supplierCents"] / 100)} ({round(detail["share"] * 100)}%)'
    base = f'Nas notas disponíveis de {period}{coverage}, que somam {store_money(detail["totalCents"] / 100)}, '
    intermediation = detail.get('intermediation')
    if intermediation:
        return (base + f'{share} foram pagos a {supplier_name} por passagens de outras companhias '
                f'({", ".join(intermediation["airlines"])}; {intermediation["records"]} de {detail["records"]} notas). '
                'É o total pago pelas passagens, não a receita da agência nem gasto com uma só companhia aérea.')
    return base + f'{share} foram para {supplier_name} ({detail["records"]} notas).'


def alert_coverage(db, identifier):
    """O que as regras puderam avaliar para a pessoa, por regra e ano do mandato, do mais recente ao mais antigo."""
    out = []
    for r in rows(db, 'SELECT sourceId,year,rule,detail FROM alert_coverage WHERE authorityId=? ORDER BY year DESC,rule DESC', (identifier,)):
        detail = json.loads(r['detail'])
        if r['rule'] == 'pico':
            out.append({'regra': 'pico', 'ano': r['year'], 'avaliados': detail['evaluated'], 'marcados': detail['flagged'],
                        'naoAvaliados': [{'motivo': key, 'texto': NOT_EVALUATED_TEXT.get(key, key), 'meses': months}
                                         for key, months in detail['notEvaluated'].items()],
                        'coletadoEm': detail.get('fetchedAt'), 'regraVersao': detail.get('ruleVersion')})
        else:
            out.append({'regra': 'fornecedor', 'ano': r['year'], 'avaliado': detail['evaluated'], 'parcial': detail['partial'],
                        'periodo': _alert_period_label({**detail, 'year': r['year']}), 'coletadoEm': detail.get('fetchedAt'),
                        'regraVersao': detail.get('ruleVersion')})
    return out


def store_money(v):
    return ('R$ ' + f'{v:,.0f}').replace(',', '.')


def radar(db, params):
    """Feed do cidadão. Por padrão só picos e concentração em fornecedor: notas altas sozinhas
    (aluguel de carro de R$ 10 mil, por exemplo) são comuns e viram ruído para quem não é do ramo.
    Alertas do mandato, dos mais recentes aos mais antigos; `ano` filtra um ano."""
    types = [t for t in (params.get('tipo') or 'pico,fornecedor').split(',') if t in ('pico', 'fornecedor', 'nota')]
    # Só parlamentares: contas institucionais (lideranças) não aparecem nas telas.
    clauses, args = [f"s.type IN ({','.join('?' * len(types))})", "a.role IN ('deputado','senador')"], list(types)
    if params.get('cargo') in ROLES:
        clauses.append('a.role=?'); args.append(params['cargo'])
    if params.get('id'):
        clauses.append('s.authorityId=?'); args.append(params['id'])
    # Anos disponíveis no filtro atual (sem o próprio filtro de ano), para os botões de ano.
    years = rows(db, f'''SELECT CAST(substr(s.period,1,4) AS INTEGER) ano,COUNT(*) total FROM signals s JOIN authorities a ON a.id=s.authorityId
        WHERE {' AND '.join(clauses)} GROUP BY ano ORDER BY ano DESC''', args)
    year = str(params.get('ano') or '')
    if year.isdigit() and len(year) == 4:
        clauses.append('substr(s.period,1,4)=?'); args.append(year)
    page, size, offset = store.page_args(params)
    where = ' AND '.join(clauses)
    total = db.execute(f'SELECT COUNT(*) FROM signals s JOIN authorities a ON a.id=s.authorityId WHERE {where}', args).fetchone()[0]
    # Intercala os tipos (maior pico, maior concentração, 2º pico...) para o feed não virar uma lista de um tipo só.
    signals = rows(db, f'''SELECT * FROM (SELECT s.*,a.name authorityName,
            ROW_NUMBER() OVER (PARTITION BY s.type ORDER BY s.period DESC,s.amountCents DESC,s.id) rank_position
            FROM signals s JOIN authorities a ON a.id=s.authorityId WHERE {where})
        ORDER BY rank_position, CASE type WHEN 'pico' THEN 0 WHEN 'fornecedor' THEN 1 ELSE 2 END LIMIT ? OFFSET ?''', [*args, size, offset])
    people = _people(db, [signal['authorityId'] for signal in signals])
    cache = {}
    items = [_alert(db, signal, people, cache) for signal in signals]
    count_clauses, count_args = ["a.role IN ('deputado','senador')"], []
    if params.get('cargo') in ROLES:
        count_clauses.append('a.role=?'); count_args.append(params['cargo'])
    if year.isdigit() and len(year) == 4:
        count_clauses.append('substr(s.period,1,4)=?'); count_args.append(year)
    counts = {r['type']: r['n'] for r in rows(db, f'''SELECT s.type,COUNT(*) n FROM signals s JOIN authorities a ON a.id=s.authorityId
        WHERE {' AND '.join(count_clauses)} GROUP BY s.type''', count_args)}
    return {'itens': items, 'total': total, 'page': page, 'pageSize': size, 'contagem': counts, 'anos': years,
            'periodo': _alert_span(db), 'snapshotAt': _snapshot(db)}


def _alert_span(db):
    """Primeiro e último mês com notas avaliadas pelas regras de alerta ('AAAA-MM'), para o texto das telas."""
    first, last = db.execute("SELECT MIN(periodStart),MAX(periodEnd) FROM authority_totals WHERE kind='reembolso'").fetchone()
    if not first:
        return None
    return {'inicio': max(first, f'{MANDATE_START[0]:04d}-{MANDATE_START[1]:02d}'), 'fim': last}


def _snapshot(db):
    r = db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone()
    return r[0] if r else None


def _averages(db):
    out = {}
    for role in ROLES:
        r = db.execute(f'''SELECT AVG({MONTHLY})/100.0, COUNT(*) FROM authority_totals t JOIN authorities a ON a.id=t.authorityId
            WHERE t.kind='reembolso' AND a.role=? AND a.id IN (SELECT authorityId FROM roster WHERE sourceId=?)''', (role, CURRENT[role])).fetchone()
        out[role] = {'media': r[0] or 0, 'n': r[1]}
    return out


def _politician_coverage(db):
    """Counts current roster records and members with observed reimbursements."""
    by_role = {role: {'count': 0, 'withExpenses': 0} for role in ROLES}
    counts = rows(db, '''SELECT a.role, COUNT(*) count,
            SUM(CASE WHEN t.authorityId IS NOT NULL THEN 1 ELSE 0 END) withExpenses
        FROM authorities a
        LEFT JOIN authority_totals t ON t.authorityId=a.id AND t.kind='reembolso'
        WHERE (a.role=? AND a.id IN (SELECT authorityId FROM roster WHERE sourceId=?)) OR (a.role=? AND a.id IN (SELECT authorityId FROM roster WHERE sourceId=?))
        GROUP BY a.role''',
        ('deputado', CURRENT['deputado'], 'senador', CURRENT['senador']))
    for row in counts:
        by_role[row['role']] = {
            'count': row['count'],
            'withExpenses': row['withExpenses'] or 0,
        }
    return by_role


def summary(db):
    """Resumo da página inicial, calculado sobre o roster atual e todos os reembolsos observados.

    Médias usam somente parlamentares com registros; sem registros, total e média ficam nulos.
    O ranking inclui todos os membros atuais da Câmara com registros, sem limitar a uma amostra.
    """
    aggregates = rows(db, f'''SELECT a.role,COUNT(*) total,COUNT(t.authorityId) comReembolsos,
            SUM(t.amountCents) cents,AVG({MONTHLY}) mediaCents,
            MIN(t.periodStart) inicio,MAX(t.periodEnd) fim
        FROM authorities a LEFT JOIN authority_totals t
            ON t.authorityId=a.id AND t.kind='reembolso'
        WHERE (a.role=? AND a.id IN (SELECT authorityId FROM roster WHERE sourceId=?)) OR (a.role=? AND a.id IN (SELECT authorityId FROM roster WHERE sourceId=?))
        GROUP BY a.role''',
        ('deputado', CURRENT['deputado'], 'senador', CURRENT['senador']))
    by_role = {role: {
        'total': 0, 'comReembolsos': 0, 'cents': None, 'mediaCents': None,
        'inicio': None, 'fim': None,
    } for role in ROLES}
    for row in aggregates:
        by_role[row['role']] = row

    parliamentarians, reimbursements = {}, {}
    for role, row in by_role.items():
        with_records = row['comReembolsos']
        parliamentarians[role] = {'total': row['total'], 'comReembolsos': with_records}
        reimbursements[role] = {
            'total': row['cents'] / 100 if with_records else None,
            'media': row['mediaCents'] / 100 if with_records else None,
            'comRegistros': with_records,
            'periodo': {'inicio': row['inicio'], 'fim': row['fim']},
        }

    category_rows = rows(db, f'''SELECT e.category,SUM(e.amountCents) cents
        FROM authorities a JOIN {QUOTA_MONTHS} e ON e.authorityId=a.id
        WHERE a.role='deputado' AND a.id IN (SELECT authorityId FROM roster WHERE sourceId=?) AND e.kind='reembolso'
        GROUP BY e.category''', (CURRENT['deputado'],))
    categories = {}
    for row in category_rows:
        name = category_name(row['category'])
        categories[name] = categories.get(name, 0) + row['cents'] / 100

    top = rows(db, f'''SELECT a.id,a.name nome,a.party partido,a.uf,t.amountCents/100.0 gasto,
            {MONTHLY}/100.0 gastoMensal,t.periodStart inicio,t.periodEnd fim
        FROM authorities a JOIN authority_totals t ON t.authorityId=a.id AND t.kind='reembolso'
        WHERE a.role='deputado' AND a.id IN (SELECT authorityId FROM roster WHERE sourceId=?)
        ORDER BY gastoMensal DESC,a.name,a.id''', (CURRENT['deputado'],))
    return {
        'parlamentares': parliamentarians,
        'reembolsos': reimbursements,
        'categoriasCamara': [
            {'nome': name, 'valor': value}
            for name, value in sorted(categories.items(), key=lambda item: (-item[1], item[0]))
        ],
        'topCamara': top,
        'snapshotAt': _snapshot(db),
    }


def politicians(db, params):
    """Lista de deputados(as) e senadores(as) em exercício, com custo médio mensal, cota e nº de alertas.

    O custo é o da ficha de cada Casa (``backend/costs.py``); como as Casas não publicam as mesmas partes,
    a ordem por custo (``ordem=gasto``) só faz sentido dentro de uma Casa: sem ``cargo``, ordena por Casa
    primeiro. Quem não tem custo identificado vai para o fim, sem valor estimado.
    """
    clauses, args = ["a.role IN ('deputado','senador')", "a.id IN (SELECT authorityId FROM roster WHERE sourceId IN (?,?))"], [CURRENT['deputado'], CURRENT['senador']]
    if params.get('cargo') in ROLES:
        clauses.append('a.role=?'); args.append(params['cargo'])
    if params.get('q'):
        clauses.append("(a.searchText LIKE ? ESCAPE '\\' OR UPPER(COALESCE(a.party,'')) = ? OR UPPER(COALESCE(a.uf,'')) = ?)")
        q = params['q'].strip()
        args += [store.query_text(params), q.upper(), q.upper()]
    sort_order = {
        'gasto': 'CASE WHEN t.authorityId IS NULL THEN 1 ELSE 0 END,gastoMensal DESC',
        # Pelo peso: valor envolvido nos alertas, não a contagem (vários alertas pequenos não passam à frente de um enorme).
        'alertas': 'valorAlertas DESC,alertas DESC,CASE WHEN t.authorityId IS NULL THEN 1 ELSE 0 END,gastoMensal DESC',
    }.get(params.get('ordem'), 'a.name')
    page, size, offset = store.page_args(params)
    where = ' AND '.join(clauses)
    total = db.execute(f'SELECT COUNT(*) FROM authorities a WHERE {where}', args).fetchone()[0]
    by_cost = params.get('ordem') == 'gasto'
    monthly = costs.monthly_costs(db)
    items = rows(db, f'''SELECT a.id,a.name,a.role,a.party,a.uf,a.position,a.employmentStatus,a.sourceUrl,
        CASE WHEN t.authorityId IS NULL THEN NULL ELSE t.amountCents/100.0 END gasto,
        CASE WHEN t.authorityId IS NULL THEN NULL ELSE {MONTHLY}/100.0 END gastoMensal,t.periodStart inicio,t.periodEnd fim,
        (t.authorityId IS NOT NULL) hasExpenseData,COALESCE(t.count,0) expenseCount,
        (SELECT COUNT(*) FROM signals s WHERE s.authorityId=a.id AND s.type IN ('pico','fornecedor')) alertas,
        COALESCE(v.amountCents,0)/100.0 valorAlertas,COALESCE(v.partial,0) valorAlertasParcial
        FROM authorities a LEFT JOIN authority_totals t ON t.authorityId=a.id AND t.kind='reembolso'
        LEFT JOIN alert_totals v ON v.authorityId=a.id
        WHERE {where} ORDER BY {'a.name' if by_cost else sort_order},a.id {'' if by_cost else 'LIMIT ? OFFSET ?'}''',
        args if by_cost else [*args, size, offset])
    for item in items:
        cost = monthly.get(item['id'])
        item['custoMensal'] = cost['cents'] / 100 if cost else None
        item['custoMeses'] = cost['months'] if cost else None
    cost_averages = _cost_averages(db, monthly)
    if by_cost:
        house = {'deputado': 0, 'senador': 1}
        # Sem custo identificado: no fim da Casa, pela cota (sem cota, por último).
        items.sort(key=lambda item: (house.get(item['role'], 2), item['custoMensal'] is None, -(item['custoMensal'] or 0),
                                     item['gastoMensal'] is None, -(item['gastoMensal'] or 0), item['name']))
        items = items[offset:offset + size]
    return {'itens': items, 'total': total, 'page': page, 'pageSize': size,
            'cobertura': {**_politician_coverage(db), 'custo': {role: value['n'] for role, value in cost_averages.items()}},
            'medias': _averages(db), 'custoMedias': cost_averages,
            'snapshotAt': _snapshot(db)}


def _cost_averages(db, monthly):
    """Custo médio mensal por Casa, entre quem está na lista atual e tem custo identificado (para "acima da média")."""
    out = {}
    for role in ROLES:
        values = [monthly[i]['cents'] for (i,) in db.execute('SELECT authorityId FROM roster WHERE sourceId=?', (CURRENT[role],)) if i in monthly]
        out[role] = {'media': sum(values) / len(values) / 100 if values else None, 'n': len(values)}
    return out


def politician(db, identifier):
    """Ficha leve de qualquer deputado(a) ou senador(a) da base."""
    people = _people(db, [identifier])
    if identifier not in people:
        return None
    person = people[identifier]
    # Notas detalhadas do ano corrente mais as notas dos anos anteriores do mandato.
    person_months = '''(SELECT year,month,category,kind,amountCents,1 count FROM expenses INDEXED BY expense_authority WHERE authorityId=:id
        UNION ALL SELECT year,month,category,kind,amountCents,1 FROM quota_history WHERE authorityId=:id)'''
    monthly_totals = rows(db, f"SELECT year,month,SUM(amountCents)/100.0 valor FROM {person_months} WHERE kind='reembolso' GROUP BY year,month ORDER BY year,month", {'id': identifier})
    categories = {}
    for r in rows(db, f"SELECT category,SUM(amountCents)/100.0 v FROM {person_months} WHERE kind='reembolso' GROUP BY category", {'id': identifier}):
        name = category_name(r['category']); categories[name] = categories.get(name, 0) + r['v']
    expense_count = db.execute(f"SELECT COALESCE(SUM(count),0) FROM {person_months} WHERE kind='reembolso'", {'id': identifier}).fetchone()[0]
    has_expense_data = expense_count > 0
    total = sum(categories.values()) if has_expense_data else None
    suppliers = rows(db, '''SELECT s.name,s.cnpj,SUM(x.cents)/100.0 valor,SUM(x.n) notas FROM (
            SELECT supplierKey,amountCents cents,1 n FROM expenses INDEXED BY expense_authority WHERE authorityId=:id AND kind='reembolso'
            UNION ALL SELECT supplierKey,amountCents,1 FROM quota_history WHERE authorityId=:id AND kind='reembolso') x
        JOIN suppliers s ON s.key=x.supplierKey GROUP BY x.supplierKey ORDER BY valor DESC,s.name LIMIT 5''', {'id': identifier})
    largest_expenses = rows(db, '''SELECT * FROM (
            SELECT e.date,e.year,e.month,e.category,e.amountCents/100.0 valor,e.documentUrl,s.name fornecedor FROM expenses e INDEXED BY expense_authority
            LEFT JOIN suppliers s ON s.key=e.supplierKey WHERE e.authorityId=:id AND e.kind='reembolso'
            UNION ALL SELECT h.date,h.year,h.month,h.category,h.amountCents/100.0,h.documentUrl,s.name FROM quota_history h
            LEFT JOIN suppliers s ON s.key=h.supplierKey WHERE h.authorityId=:id AND h.kind='reembolso')
        ORDER BY valor DESC LIMIT 5''', {'id': identifier})
    for m in largest_expenses:
        m['categoria'] = category_name(m.pop('category'))
        m['documentUrl'] = store.safe_url(m['documentUrl']) if m.get('documentUrl') else None
        m['fornecedor'] = (m['fornecedor'] or '').strip() or None
    signals = rows(db, "SELECT s.*,? authorityName FROM signals s WHERE s.authorityId=? AND s.type IN ('pico','fornecedor') ORDER BY s.period DESC,s.amountCents DESC", (person['name'], identifier))
    # Complemento de moradia da CEAP: fora da cota, mostrado à parte com o sinal publicado.
    complement = db.execute(f'''SELECT SUM(amountCents),SUM(count),GROUP_CONCAT(DISTINCT year||'-'||printf('%02d',month)) FROM {person_months}
        WHERE kind=:kind''', {'id': identifier, 'kind': HOUSING_COMPLEMENT_KIND}).fetchone()
    cache = {}
    averages = _averages(db)
    span = db.execute(f"SELECT t.periodStart,t.periodEnd,{MONTH_COUNT} FROM authority_totals t WHERE t.authorityId=? AND t.kind='reembolso'",
                      (identifier,)).fetchone()
    return {'pessoa': person, 'total': total, 'hasExpenseData': has_expense_data,
            'mediaMensal': total / span[2] if has_expense_data and span else None,
            'periodo': {'inicio': span[0], 'fim': span[1], 'meses': span[2]} if has_expense_data and span else None,
            'expenseCount': expense_count, 'meses': monthly_totals,
            'categorias': [{'nome': k, 'valor': v} for k, v in sorted(categories.items(), key=lambda kv: -kv[1])],
            'fornecedores': suppliers, 'maiores': largest_expenses, 'alertas': [_alert(db, signal, people, cache) for signal in signals],
            'coberturaAlertas': alert_coverage(db, identifier),
            'media': averages.get(person.get('role'), {}).get('media'), 'snapshotAt': _snapshot(db),
            'complementoMoradia': {'valor': complement[0] / 100, 'notas': complement[1],
                                   'meses': sorted(set(complement[2].split(',')))} if complement[1] else None}


def month_notes(db, identifier, period):
    """Notas da cota de um mês, para conferir o valor da ficha (ano corrente e anos anteriores do mandato).

    A soma das notas de reembolso é o valor da cota do mês; o complemento de moradia vem à parte.
    Mês sem nota devolve None.
    """
    match = re.fullmatch(r'(\d{4})-(\d{2})', period or '')
    person = db.execute("SELECT id,name FROM authorities WHERE id=? AND role IN ('deputado','senador')", (identifier,)).fetchone()
    if not match or not person or not 1 <= int(match[2]) <= 12:
        return None
    year, month = int(match[1]), int(match[2])
    notes = rows(db, '''SELECT e.date data,e.category,e.amountCents,e.kind,e.documentUrl,s.name fornecedor,s.cnpj,
            src.label fonte,src.url fonteUrl,src.fetchedAt coletadoEm
        FROM (SELECT date,category,amountCents,kind,documentUrl,supplierKey,sourceId,id FROM expenses INDEXED BY expense_authority
                WHERE authorityId=:id AND year=:year AND month=:month
              UNION ALL SELECT date,category,amountCents,kind,documentUrl,supplierKey,sourceId,seq FROM quota_history
                WHERE authorityId=:id AND year=:year AND month=:month) e
        LEFT JOIN suppliers s ON s.key=e.supplierKey LEFT JOIN sources src ON src.id=e.sourceId
        ORDER BY e.amountCents DESC,e.date,e.id''', {'id': identifier, 'year': year, 'month': month})
    if not notes:
        return None
    reimbursements = [n for n in notes if n['kind'] == 'reembolso']
    complement = [n for n in notes if n['kind'] == HOUSING_COMPLEMENT_KIND]
    first = notes[0]

    def public(note):
        return {'data': note['data'], 'categoria': category_name(note['category']), 'valor': note['amountCents'] / 100,
                'fornecedor': (note['fornecedor'] or '').strip() or None, 'cnpj': note['cnpj'],
                'documentUrl': store.safe_url(note['documentUrl'])}
    return {'pessoa': {'id': person[0], 'name': person[1]}, 'periodo': f'{year:04d}-{month:02d}',
            'notas': [public(n) for n in reimbursements],
            'total': sum(n['amountCents'] for n in reimbursements) / 100,
            'complemento': {'valor': sum(n['amountCents'] for n in complement) / 100, 'notas': len(complement)} if complement else None,
            'fonte': {'label': first['fonte'], 'url': store.safe_url(first['fonteUrl']), 'coletadoEm': first['coletadoEm']}}


CSV_COLUMNS = ['Parlamentar', 'Competência', 'Data de emissão', 'Categoria', 'Valor (R$)', 'Fornecedor', 'CNPJ',
               'Documento', 'Link do documento', 'Fonte', 'Link da fonte', 'Data da coleta']


def _csv_safe_text(value):
    # Planilhas executam células que começam com =, +, - ou @; o apóstrofo transforma em texto.
    value = '' if value is None else str(value)
    return "'" + value if re.match(r'^[\s\x00-\x1f]*[=+@-]', value) else value


def expenses_csv(db, identifier):
    """Todas as notas da cota de um(a) parlamentar, para conferir em planilha (CSV com ';').

    Devolve (nome do arquivo, gerador de linhas) ou None se a pessoa não for deputado(a) ou senador(a) da base.
    """
    person_row = db.execute("SELECT id,name FROM authorities WHERE id=? AND role IN ('deputado','senador')", (identifier,)).fetchone()
    if not person_row:
        return None
    name = person_row[1]

    def lines():
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=';')

        def line(values):
            writer.writerow(values)
            text = buffer.getvalue()
            buffer.seek(0); buffer.truncate(0)
            return text
        yield '\ufeff' + line(CSV_COLUMNS)
        # Notas do ano corrente e dos anos anteriores do mandato; estas não guardam o número do documento.
        for e in db.execute('''SELECT e.year,e.month,e.date,e.category,e.amountCents,s.name,s.cnpj,e.documentId,e.documentUrl,
                src.label,src.url,src.fetchedAt FROM (
                    SELECT year,month,date,category,amountCents,supplierKey,documentId,documentUrl,sourceId,kind,id
                    FROM expenses INDEXED BY expense_authority WHERE authorityId=:id
                    UNION ALL SELECT year,month,date,category,amountCents,supplierKey,NULL,documentUrl,sourceId,kind,seq
                    FROM quota_history WHERE authorityId=:id) e
                JOIN sources src ON src.id=e.sourceId LEFT JOIN suppliers s ON s.key=e.supplierKey
                WHERE e.kind IN ('reembolso',:kind) ORDER BY e.year,e.month,e.date,e.id''', {'id': identifier, 'kind': HOUSING_COMPLEMENT_KIND}):
            year, month, date, category, cents, supplier, cnpj, document, document_url, source, source_url, fetched = tuple(e)
            amount_text = f'{"-" if cents < 0 else ""}{abs(cents) // 100},{abs(cents) % 100:02d}'
            yield line([_csv_safe_text(name), f'{year:04d}-{month:02d}', date or '', _csv_safe_text(category), amount_text,
                         _csv_safe_text(supplier), cnpj or '', _csv_safe_text(document), store.safe_url(document_url) or '',
                         _csv_safe_text(source), store.safe_url(source_url) or '', fetched or ''])
    slug = re.sub(r'[^a-z0-9]+', '-', store.fold(name)).strip('-') or 'parlamentar'
    return f'gastos-cota-{slug}.csv', lines()


def parties(db):
    """Resumo por partido dos(as) parlamentares em exercício: bancada, cota observada, alertas e quem mais gastou.

    Gasto e média só contam quem tem notas importadas; sem nenhuma nota, o gasto fica nulo (ausência não é zero).
    """
    condition = '((a.role=? AND a.id IN (SELECT authorityId FROM roster WHERE sourceId=?)) OR (a.role=? AND a.id IN (SELECT authorityId FROM roster WHERE sourceId=?)))'
    args = ('deputado', CURRENT['deputado'], 'senador', CURRENT['senador'])
    lines = rows(db, f'''SELECT a.party sigla, a.role,
            COUNT(*) membros,
            SUM(CASE WHEN t.authorityId IS NOT NULL THEN 1 ELSE 0 END) comDados,
            SUM(t.amountCents)/100.0 gasto,AVG({MONTHLY})/100.0 media,
            SUM((SELECT COUNT(*) FROM signals s WHERE s.authorityId=a.id AND s.type IN ('pico','fornecedor'))) alertas
        FROM authorities a LEFT JOIN authority_totals t ON t.authorityId=a.id AND t.kind='reembolso'
        WHERE {condition} AND TRIM(COALESCE(a.party,''))<>''
        GROUP BY a.party, a.role''', args)
    top_rows = rows(db, f'''SELECT sigla, id, name, role, gasto, gastoMensal FROM (
            SELECT a.party sigla, a.id, a.name, a.role, t.amountCents/100.0 gasto, {MONTHLY}/100.0 gastoMensal,
                ROW_NUMBER() OVER (PARTITION BY a.party ORDER BY {MONTHLY} DESC, a.id) n
            FROM authorities a JOIN authority_totals t ON t.authorityId=a.id AND t.kind='reembolso'
            WHERE {condition} AND TRIM(COALESCE(a.party,''))<>'')
        WHERE n<=3 ORDER BY sigla, n''', args)
    out = {}
    for r in lines:
        person = out.setdefault(r['sigla'], {'sigla': r['sigla'], 'membros': 0, 'deputado': None, 'senador': None, 'top': []})
        # Média por pessoa do gasto médio mensal; sem notas, nula (ausência não é zero).
        person[r['role']] = {'membros': r['membros'], 'comDados': r['comDados'], 'gasto': r['gasto'],
                        'media': r['media'] if r['comDados'] else None, 'alertas': r['alertas'] or 0}
        person['membros'] += r['membros']
    for r in top_rows:
        out[r['sigla']]['top'].append({k: r[k] for k in ('id', 'name', 'role', 'gasto', 'gastoMensal')})
    items = sorted(out.values(), key=lambda person: (-person['membros'], person['sigla']))
    return {'itens': items, 'medias': _averages(db), 'snapshotAt': _snapshot(db)}
