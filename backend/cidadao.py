"""Camada do cidadão: traduz a base e os sinais do radar em linguagem simples.

Não recalcula nem altera os sinais de public_store.py. Só reúne o que cada alerta
precisa para ser entendido sem conhecimento técnico: quem, quanto, comparado com o quê,
e onde conferir. Rotas no server.py: /api/c/resumo, /api/c/radar, /api/c/politicos, /api/c/politico/<id>.
"""
import re
from statistics import median

from . import public_store as store

ROLES = ('deputado', 'senador')
CARGO_PL = {'deputado': 'deputados(as)', 'senador': 'senadores(as)'}
CURRENT = {'deputado': 'camara_deputies_current', 'senador': 'senado_senators_current'}
MESES = ['', 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto',
         'setembro', 'outubro', 'novembro', 'dezembro']

# Nomes curtos para as categorias da Câmara e do Senado (que usam textos diferentes).
CATEGORIAS = [
    (r'divulga', 'Divulgação'),
    (r'passagem a[ée]rea|a[ée]reas?$', 'Passagens aéreas'),
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


def categoria(nome):
    texto = (nome or '').lower()
    for padrao, curto in CATEGORIAS:
        if re.search(padrao, texto):
            return curto
    return (nome or 'Outros').strip().rstrip('.').capitalize()


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


def _pessoas(db, ids):
    """Nome, cargo, partido, UF e metadados da fotografia oficial.

    Registros que só existem no arquivo de despesas (sem partido) herdam partido/UF
    do cadastro atual de mesmo nome, quando existe.
    """
    ids = list(dict.fromkeys(i for i in ids if i))
    if not ids:
        return {}
    marks = ','.join('?' * len(ids))
    out = {r['id']: r for r in rows(db, f'SELECT id,name,role,party,uf,sourceId,sourceUrl,position,employmentStatus FROM authorities WHERE id IN ({marks})', ids)}
    faltando = [r for r in out.values() if not r.get('party')]
    if faltando:
        atuais = {}
        for r in rows(db, f"SELECT name,role,party,uf FROM authorities WHERE role IN ('deputado','senador') AND party IS NOT NULL"):
            atuais[(r['role'], store.fold(r['name']))] = r
        for r in faltando:
            par = atuais.get((r['role'], store.fold(r['name'])))
            if par:
                r['party'], r['uf'] = par['party'], par['uf']
                r['name'] = par['name']
            else:
                r['foraDaLista'] = True
    for r in out.values():
        r['current'] = r.get('sourceId') == CURRENT.get(r.get('role')) or bool(r.get('party'))
    return out


def _serie(db, authority, source, year):
    rs = rows(db, '''SELECT month, SUM(amountCents) c FROM expenses INDEXED BY expense_authority WHERE authorityId=? AND sourceId=? AND year=? AND kind='reembolso'
        GROUP BY month ORDER BY month''', (authority, source, year))
    return {r['month']: r['c'] / 100 for r in rs}


def _contexto(db, p, authority, source, year, cache, total=None):
    """Escala do ano: um alerta de quem gasta pouco não pode parecer igual ao de quem gasta muito."""
    if '__medias' not in cache:
        cache['__medias'] = _medias(db)
    media = (cache['__medias'].get(p.get('role')) or {}).get('media')
    if total is None:
        total = sum(_serie(db, authority, source, int(year)).values())
    if not media or not total:
        return None
    dif = total / media - 1
    grupo = CARGO_PL.get(p.get('role'), 'parlamentares')
    if abs(dif) < 0.1:
        comp = f'parecido com a média dos(as) {grupo}'
    else:
        comp = f'{round(abs(dif) * 100)}% {"mais" if dif > 0 else "menos"} que a média dos(as) {grupo} ({store_money(media)})'
    return {'total': total, 'media': media, 'diferenca': dif,
            'frase': f'No ano, gastou {store_money(total)} na cota, {comp}.'}


def _alerta(db, s, pessoas, totais_cache):
    """Um sinal do radar em linguagem simples. Mantém o texto técnico original em `criterio`."""
    p = pessoas.get(s['authorityId'], {'name': s.get('authorityName')})
    base = {'id': s['id'], 'tipo': s['type'], 'valor': s['amountCents'] / 100, 'periodo': s['period'],
            'pessoa': {k: p.get(k) for k in ('id', 'name', 'role', 'party', 'uf', 'foraDaLista')}, 'criterio': s['description']}
    if s['type'] == 'pico':
        # O id do parlamentar pode ter mais de um ':' (contas de liderança: camara:group:N); lê das colunas.
        authority, source = s['authorityId'], s['sourceId']
        year, month = (int(x) for x in s['period'].split('-'))
        serie = _serie(db, authority, source, year)
        antes = [serie.get(m, 0) for m in range(1, month)]
        ref = median(antes) if antes else 0
        vezes = base['valor'] / ref if ref else None
        # Meses seguidos acima do normal formam um único alerta (mudança de patamar).
        seguidos = []
        m = month + 1
        while ref and serie.get(m) is not None and serie[m] >= ref * 1.75 and m < max(serie):
            seguidos.append(m); m += 1
        titulo = (f'Passou a gastar mais a partir de {MESES[month]}' if seguidos
                  else f'Gastou {vezes:.1f}× o normal em {MESES[month]}'.replace('.', ',') if vezes else 'Gasto fora do normal')
        frase = f'Em {MESES[month]}, a cota custou {store_money(base["valor"])}. Nos meses anteriores, o normal era {store_money(ref)} por mês.'
        if seguidos:
            frase += ' Depois continuou alta: ' + ', '.join(f'{MESES[x]} {store_money(serie[x])}' for x in seguidos) + '.'
        base.update({'referencia': ref, 'vezes': vezes, 'mes': month, 'seguidos': seguidos,
                     'contexto': _contexto(db, p, authority, source, year, totais_cache),
                     'serie': [{'mes': m, 'valor': serie.get(m)} for m in range(1, max(serie) + 1)] if serie else [],
                     'nivel': 'alto' if vezes and vezes >= 3 else 'medio',
                     'titulo': titulo,
                     'frase': frase,
                     'fonte': p.get('sourceUrl')})
    elif s['type'] == 'fornecedor':
        authority, source, year = s['authorityId'], s['sourceId'], s['period']
        prefix = f'fornecedor:{authority}:{source}:{year}'
        key = s['id'][len(prefix) + 1:]
        forn = rows(db, 'SELECT name,cnpj FROM suppliers WHERE key=?', (key,))
        tk = (authority, source, year, key)
        if tk not in totais_cache:
            # Uma consulta só, pelo índice do parlamentar (o índice de fornecedor é lento para isso).
            r = db.execute('''SELECT SUM(amountCents), SUM(CASE WHEN supplierKey=? THEN 1 ELSE 0 END) FROM expenses INDEXED BY expense_authority
                WHERE authorityId=? AND sourceId=? AND year=? AND kind=\'reembolso\'''', (key, authority, source, int(year))).fetchone()
            c = rows(db, '''SELECT category FROM expenses INDEXED BY expense_authority WHERE authorityId=? AND supplierKey=?
                GROUP BY category ORDER BY SUM(amountCents) DESC LIMIT 1''', (authority, key))
            totais_cache[tk] = ((r[0] or 0) / 100, r[1] or 0, c)
        total, notas, cat = totais_cache[tk]
        share = base['valor'] / total if total else None
        nome_forn = (forn[0]['name'] if forn else 'um único fornecedor').strip()
        base.update({'fornecedor': nome_forn, 'cnpj': forn[0]['cnpj'] if forn else None, 'total': total, 'parte': share,
                     'notas': notas, 'categoria': categoria(cat[0]['category']) if cat else None,
                     'nivel': 'alto' if share and share >= 0.8 else 'medio',
                     'titulo': f'{round(share * 100)}% do dinheiro foi para uma empresa só' if share else 'Dinheiro concentrado em uma empresa',
                     'frase': f'Das notas da cota em {year}, que somam {store_money(total)}, {store_money(base["valor"])} foram para {nome_forn} ({notas} notas).',
                     'fornecedorKey': key, 'contexto': _contexto(db, p, authority, source, year, totais_cache, total)})
    else:  # nota
        e = rows(db, '''SELECT e.date,e.category,e.documentUrl,s.name supplier FROM expenses e LEFT JOIN suppliers s ON s.key=e.supplierKey
            WHERE e.id=?''', (s['id'][len('nota:'):],))
        e = e[0] if e else {}
        base.update({'fornecedor': (e.get('supplier') or '').strip() or None, 'categoria': categoria(e.get('category')),
                     'data': e.get('date'), 'documento': store.safe_url(e.get('documentUrl')) if e.get('documentUrl') else None,
                     'nivel': 'info', 'titulo': f'Nota de {store_money(base["valor"])}',
                     'frase': f'Uma única nota de {categoria(e.get("category")).lower()}' + (f', paga a {e.get("supplier").strip()}.' if e.get('supplier') else '.')})
    return base


def store_money(v):
    return ('R$ ' + f'{v:,.0f}').replace(',', '.')


def radar(db, params):
    """Feed do cidadão. Por padrão só picos e concentração em fornecedor: notas altas sozinhas
    (aluguel de carro de R$ 10 mil, por exemplo) são comuns e viram ruído para quem não é do ramo."""
    tipos = [t for t in (params.get('tipo') or 'pico,fornecedor').split(',') if t in ('pico', 'fornecedor', 'nota')]
    # Só parlamentares: contas institucionais (lideranças) ficam na busca avançada.
    clauses, args = [f"s.type IN ({','.join('?' * len(tipos))})", "a.role IN ('deputado','senador')"], list(tipos)
    if params.get('cargo') in ROLES:
        clauses.append('a.role=?'); args.append(params['cargo'])
    if params.get('id'):
        clauses.append('s.authorityId=?'); args.append(params['id'])
    page, size, offset = store.page_args(params)
    where = ' AND '.join(clauses)
    total = db.execute(f'SELECT COUNT(*) FROM signals s JOIN authorities a ON a.id=s.authorityId WHERE {where}', args).fetchone()[0]
    # Intercala os tipos (maior pico, maior concentração, 2º pico...) para o feed não virar uma lista de um tipo só.
    sinais = rows(db, f'''SELECT * FROM (SELECT s.*,a.name authorityName,
            ROW_NUMBER() OVER (PARTITION BY s.type ORDER BY s.amountCents DESC,s.id) ordem
            FROM signals s JOIN authorities a ON a.id=s.authorityId WHERE {where})
        ORDER BY ordem, CASE type WHEN 'pico' THEN 0 WHEN 'fornecedor' THEN 1 ELSE 2 END LIMIT ? OFFSET ?''', [*args, size, offset])
    pessoas = _pessoas(db, [s['authorityId'] for s in sinais])
    cache = {}
    itens = [_alerta(db, s, pessoas, cache) for s in sinais]
    contagem = {r['type']: r['n'] for r in rows(db, f'''SELECT s.type,COUNT(*) n FROM signals s JOIN authorities a ON a.id=s.authorityId
        WHERE a.role IN ('deputado','senador') {"AND a.role=?" if params.get("cargo") in ROLES else ""} GROUP BY s.type''', [params['cargo']] if params.get('cargo') in ROLES else [])}
    return {'itens': itens, 'total': total, 'page': page, 'pageSize': size, 'contagem': contagem, 'snapshotAt': _snapshot(db)}


def _snapshot(db):
    r = db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone()
    return r[0] if r else None


def _medias(db):
    out = {}
    for role in ROLES:
        r = db.execute('''SELECT AVG(t.amountCents)/100.0, COUNT(*) FROM authority_totals t JOIN authorities a ON a.id=t.authorityId
            WHERE t.kind='reembolso' AND a.role=? AND a.sourceId=?''', (role, CURRENT[role])).fetchone()
        out[role] = {'media': r[0] or 0, 'n': r[1]}
    return out


def _cobertura_politicos(db):
    """Counts current roster records and members with observed reimbursements."""
    by_role = {role: {'count': 0, 'withExpenses': 0} for role in ROLES}
    counts = rows(db, '''SELECT a.role, COUNT(*) count,
            SUM(CASE WHEN t.authorityId IS NOT NULL THEN 1 ELSE 0 END) withExpenses
        FROM authorities a
        LEFT JOIN authority_totals t ON t.authorityId=a.id AND t.kind='reembolso'
        WHERE (a.role=? AND a.sourceId=?) OR (a.role=? AND a.sourceId=?)
        GROUP BY a.role''',
        ('deputado', CURRENT['deputado'], 'senador', CURRENT['senador']))
    for row in counts:
        by_role[row['role']] = {
            'count': row['count'],
            'withExpenses': row['withExpenses'] or 0,
        }
    return by_role


def resumo(db):
    """Resumo da página inicial, calculado sobre o roster atual e todos os reembolsos observados.

    Médias usam somente parlamentares com registros; sem registros, total e média ficam nulos.
    O ranking inclui todos os membros atuais da Câmara com registros, sem limitar a uma amostra.
    """
    aggregates = rows(db, '''SELECT a.role,COUNT(*) total,COUNT(t.authorityId) comReembolsos,
            SUM(t.amountCents) cents,AVG(t.amountCents) mediaCents,
            MIN(t.periodStart) inicio,MAX(t.periodEnd) fim
        FROM authorities a LEFT JOIN authority_totals t
            ON t.authorityId=a.id AND t.kind='reembolso'
        WHERE (a.role=? AND a.sourceId=?) OR (a.role=? AND a.sourceId=?)
        GROUP BY a.role''',
        ('deputado', CURRENT['deputado'], 'senador', CURRENT['senador']))
    by_role = {role: {
        'total': 0, 'comReembolsos': 0, 'cents': None, 'mediaCents': None,
        'inicio': None, 'fim': None,
    } for role in ROLES}
    for row in aggregates:
        by_role[row['role']] = row

    parlamentares, reembolsos = {}, {}
    for role, row in by_role.items():
        com_registros = row['comReembolsos']
        parlamentares[role] = {'total': row['total'], 'comReembolsos': com_registros}
        reembolsos[role] = {
            'total': row['cents'] / 100 if com_registros else None,
            'media': row['mediaCents'] / 100 if com_registros else None,
            'comRegistros': com_registros,
            'periodo': {'inicio': row['inicio'], 'fim': row['fim']},
        }

    category_rows = rows(db, '''SELECT e.category,SUM(e.amountCents) cents
        FROM authorities a JOIN expenses e ON e.authorityId=a.id
        WHERE a.role='deputado' AND a.sourceId=? AND e.kind='reembolso'
        GROUP BY e.category''', (CURRENT['deputado'],))
    categories = {}
    for row in category_rows:
        name = categoria(row['category'])
        categories[name] = categories.get(name, 0) + row['cents'] / 100

    top = rows(db, '''SELECT a.id,a.name nome,a.party partido,a.uf,t.amountCents/100.0 gasto
        FROM authorities a JOIN authority_totals t ON t.authorityId=a.id AND t.kind='reembolso'
        WHERE a.role='deputado' AND a.sourceId=?
        ORDER BY t.amountCents DESC,a.name,a.id''', (CURRENT['deputado'],))
    return {
        'parlamentares': parlamentares,
        'reembolsos': reembolsos,
        'categoriasCamara': [
            {'nome': name, 'valor': value}
            for name, value in sorted(categories.items(), key=lambda item: (-item[1], item[0]))
        ],
        'topCamara': top,
        'snapshotAt': _snapshot(db),
    }


def politicos(db, params):
    """Lista simples de deputados(as) e senadores(as) em exercício, com gasto de 2026 e nº de alertas."""
    clauses, args = ["a.role IN ('deputado','senador')", "a.sourceId IN (?,?)"], [CURRENT['deputado'], CURRENT['senador']]
    if params.get('cargo') in ROLES:
        clauses.append('a.role=?'); args.append(params['cargo'])
    if params.get('q'):
        clauses.append("(a.searchText LIKE ? ESCAPE '\\' OR UPPER(COALESCE(a.party,'')) = ? OR UPPER(COALESCE(a.uf,'')) = ?)")
        q = params['q'].strip()
        args += [store.query_text(params), q.upper(), q.upper()]
    ordem = {
        'gasto': 'CASE WHEN t.authorityId IS NULL THEN 1 ELSE 0 END,gasto DESC',
        # Pelo peso: valor envolvido nos alertas, não a contagem (vários alertas pequenos não passam à frente de um enorme).
        'alertas': 'valorAlertas DESC,alertas DESC,CASE WHEN t.authorityId IS NULL THEN 1 ELSE 0 END,gasto DESC',
    }.get(params.get('ordem'), 'a.name')
    page, size, offset = store.page_args(params)
    where = ' AND '.join(clauses)
    total = db.execute(f'SELECT COUNT(*) FROM authorities a WHERE {where}', args).fetchone()[0]
    itens = rows(db, f'''SELECT a.id,a.name,a.role,a.party,a.uf,a.position,a.employmentStatus,a.sourceUrl,
        CASE WHEN t.authorityId IS NULL THEN NULL ELSE t.amountCents/100.0 END gasto,
        (t.authorityId IS NOT NULL) hasExpenseData,COALESCE(t.count,0) expenseCount,
        (SELECT COUNT(*) FROM signals s WHERE s.authorityId=a.id AND s.type IN ('pico','fornecedor')) alertas,
        (SELECT COALESCE(SUM(s.amountCents),0)/100.0 FROM signals s WHERE s.authorityId=a.id AND s.type IN ('pico','fornecedor')) valorAlertas
        FROM authorities a LEFT JOIN authority_totals t ON t.authorityId=a.id AND t.kind='reembolso'
        WHERE {where} ORDER BY {ordem},a.id LIMIT ? OFFSET ?''', [*args, size, offset])
    return {'itens': itens, 'total': total, 'page': page, 'pageSize': size,
            'cobertura': _cobertura_politicos(db), 'medias': _medias(db), 'snapshotAt': _snapshot(db)}


def politico(db, identifier):
    """Ficha leve de qualquer deputado(a) ou senador(a) da base."""
    pessoas = _pessoas(db, [identifier])
    if identifier not in pessoas:
        return None
    p = pessoas[identifier]
    meses = rows(db, "SELECT year,month,SUM(amountCents)/100.0 valor FROM expenses INDEXED BY expense_authority WHERE authorityId=? AND kind='reembolso' GROUP BY year,month ORDER BY year,month", (identifier,))
    cats = {}
    for r in rows(db, "SELECT category,SUM(amountCents)/100.0 v FROM expenses INDEXED BY expense_authority WHERE authorityId=? AND kind='reembolso' GROUP BY category", (identifier,)):
        nome = categoria(r['category']); cats[nome] = cats.get(nome, 0) + r['v']
    expense_count = db.execute("SELECT COUNT(*) FROM expenses WHERE authorityId=? AND kind='reembolso'", (identifier,)).fetchone()[0]
    has_expense_data = expense_count > 0
    total = sum(cats.values()) if has_expense_data else None
    forns = rows(db, '''SELECT s.name,s.cnpj,SUM(e.amountCents)/100.0 valor,COUNT(*) notas FROM expenses e INDEXED BY expense_authority JOIN suppliers s ON s.key=e.supplierKey
        WHERE e.authorityId=? AND e.kind='reembolso' GROUP BY e.supplierKey ORDER BY valor DESC LIMIT 5''', (identifier,))
    maiores = rows(db, '''SELECT e.date,e.year,e.month,e.category,e.amountCents/100.0 valor,e.documentUrl,s.name fornecedor FROM expenses e INDEXED BY expense_authority
        LEFT JOIN suppliers s ON s.key=e.supplierKey WHERE e.authorityId=? AND e.kind='reembolso' ORDER BY e.amountCents DESC LIMIT 5''', (identifier,))
    for m in maiores:
        m['categoria'] = categoria(m.pop('category'))
        m['documentUrl'] = store.safe_url(m['documentUrl']) if m.get('documentUrl') else None
        m['fornecedor'] = (m['fornecedor'] or '').strip() or None
    sinais = rows(db, "SELECT s.*,? authorityName FROM signals s WHERE s.authorityId=? AND s.type IN ('pico','fornecedor') ORDER BY s.amountCents DESC", (p['name'], identifier))
    cache = {}
    medias = _medias(db)
    return {'pessoa': p, 'total': total, 'hasExpenseData': has_expense_data,
            'expenseCount': expense_count, 'meses': meses,
            'categorias': [{'nome': k, 'valor': v} for k, v in sorted(cats.items(), key=lambda kv: -kv[1])],
            'fornecedores': forns, 'maiores': maiores, 'alertas': [_alerta(db, s, pessoas, cache) for s in sinais],
            'media': medias.get(p.get('role'), {}).get('media'), 'snapshotAt': _snapshot(db)}


def partidos(db):
    """Resumo por partido dos(as) parlamentares em exercício: bancada, cota observada, alertas e quem mais gastou.

    Gasto e média só contam quem tem notas importadas; sem nenhuma nota, o gasto fica nulo (ausência não é zero).
    """
    filtro = '((a.role=? AND a.sourceId=?) OR (a.role=? AND a.sourceId=?))'
    args = ('deputado', CURRENT['deputado'], 'senador', CURRENT['senador'])
    linhas = rows(db, f'''SELECT a.party sigla, a.role,
            COUNT(*) membros,
            SUM(CASE WHEN t.authorityId IS NOT NULL THEN 1 ELSE 0 END) comDados,
            SUM(t.amountCents)/100.0 gasto,
            SUM((SELECT COUNT(*) FROM signals s WHERE s.authorityId=a.id AND s.type IN ('pico','fornecedor'))) alertas
        FROM authorities a LEFT JOIN authority_totals t ON t.authorityId=a.id AND t.kind='reembolso'
        WHERE {filtro} AND TRIM(COALESCE(a.party,''))<>''
        GROUP BY a.party, a.role''', args)
    topo = rows(db, f'''SELECT sigla, id, name, role, gasto FROM (
            SELECT a.party sigla, a.id, a.name, a.role, t.amountCents/100.0 gasto,
                ROW_NUMBER() OVER (PARTITION BY a.party ORDER BY t.amountCents DESC, a.id) n
            FROM authorities a JOIN authority_totals t ON t.authorityId=a.id AND t.kind='reembolso'
            WHERE {filtro} AND TRIM(COALESCE(a.party,''))<>'')
        WHERE n<=3 ORDER BY sigla, n''', args)
    out = {}
    for r in linhas:
        p = out.setdefault(r['sigla'], {'sigla': r['sigla'], 'membros': 0, 'deputado': None, 'senador': None, 'top': []})
        media = r['gasto'] / r['comDados'] if r['comDados'] else None
        p[r['role']] = {'membros': r['membros'], 'comDados': r['comDados'], 'gasto': r['gasto'],
                        'media': media, 'alertas': r['alertas'] or 0}
        p['membros'] += r['membros']
    for r in topo:
        out[r['sigla']]['top'].append({k: r[k] for k in ('id', 'name', 'role', 'gasto')})
    itens = sorted(out.values(), key=lambda p: (-p['membros'], p['sigla']))
    return {'itens': itens, 'medias': _medias(db), 'snapshotAt': _snapshot(db)}
