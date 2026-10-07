"""Banco local de dados públicos normalizados, com valores em centavos."""
from __future__ import annotations

import csv
import io
import gzip
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from .config import DB_PATH, ROOT
from .database import fold, migrate


def connect(path=DB_PATH):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.create_function('fold', 1, fold, deterministic=True)
    return db


def money(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('Valor monetário ausente/inválido')
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Valor monetário não finito')
    return int((number * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def safe_url(url):
    from urllib.parse import urlsplit
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    return url if parts.scheme in ('http', 'https') and parts.hostname and not parts.username and not parts.password else None


def public_document_id(value):
    """Keep invoice references, but do not expose ambiguous CPF-shaped identifiers."""
    value = str(value or '')
    digits = re.sub(r'\D', '', value)
    return '' if len(digits) == 11 and re.fullmatch(r'[\d.\-/\s]+', value) else value


def read_import(path):
    """JSON pequeno ou JSON Lines comprimido para milhões de registros."""
    path = Path(path)
    if '.jsonl' not in path.name:
        return json.loads(path.read_text())
    def records(kind):
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                item = json.loads(line)
                if item['type'] == kind:
                    yield item['data']
                elif kind == 'source' and item['type'] != 'source':
                    break
                elif kind == 'authority' and item['type'] == 'expense':
                    break
    return {'sources': list(records('source')), 'authorities': records('authority'), 'expenses': records('expense')}


def import_documents(paths, db_path=DB_PATH):
    """Importação transacional e idempotente; uma falha mantém a versão anterior."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = connect(db_path)
    migrate(db)
    stamp = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    counts = {'authorities': 0, 'expenses': 0, 'sources': 0}
    try:
        with db:
            db.execute('CREATE TEMP TABLE original_suppliers AS SELECT key,name,cnpj FROM suppliers')
            for path in paths:
                payload = read_import(path)
                sources = payload.get('sources', [])
                source_ids = {s['id'] for s in sources}
                replace_ids = {s['id'] for s in sources if s.get('status') in ('imported', 'partial')}
                db.execute('CREATE TEMP TABLE IF NOT EXISTS received_expenses(id TEXT PRIMARY KEY)')
                db.execute('DELETE FROM received_expenses')
                for s in sources:
                    if not s.get('id') or not s.get('label'):
                        raise ValueError('Fonte sem identificador ou nome')
                    columns = ('id', 'label', 'url', 'scope', 'period', 'status', 'detail', 'fetchedAt')
                    values = [s.get(k) for k in columns]
                    values[2] = safe_url(s.get('url'))
                    for i in (3, 4, 6):
                        if isinstance(values[i], (dict, list)):
                            values[i] = json.dumps(values[i], ensure_ascii=False)
                    db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                               'label=excluded.label,url=excluded.url,scope=excluded.scope,period=excluded.period,'
                               'status=excluded.status,detail=excluded.detail,fetchedAt=excluded.fetchedAt', values)
                    counts['sources'] += 1
                for a in payload.get('authorities', []):
                    if not a.get('id') or not a.get('name') or a.get('sourceId') not in source_ids:
                        raise ValueError(f'Autoridade sem identidade/fonte: {a.get("id")}')
                    columns = ('id', 'name', 'role', 'branch', 'sphere', 'institution', 'uf', 'party', 'sourceId', 'sourceUrl', 'position', 'employmentStatus')
                    values = [a.get(k) for k in columns]
                    values[9] = safe_url(a.get('sourceUrl'))
                    db.execute('''UPDATE expenses SET lastChanged=? WHERE authorityId=? AND EXISTS
                        (SELECT 1 FROM authorities WHERE id=? AND (name IS NOT ? OR role IS NOT ? OR institution IS NOT ?))''',
                        (stamp, a['id'], a['id'], a['name'], a.get('role'), a.get('institution')))
                    positions = a.get('positions') or []
                    values += [max(1, len(positions)), json.dumps(positions, ensure_ascii=False), fold(a['name'] + ' ' + (a.get('institution') or ''))]
                    all_columns = (*columns, 'positionCount', 'positions', 'searchText')
                    db.execute('INSERT INTO authorities (' + ','.join(all_columns) + ') VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                               + ','.join(f'{k}=excluded.{k}' for k in all_columns[1:]), values)
                    counts['authorities'] += 1
                for e in payload.get('expenses', []):
                    if e.get('sourceId') not in source_ids or not e.get('id'):
                        raise ValueError('Despesa sem identidade/fonte')
                    if e.get('kind') not in ('reembolso', 'remuneracao'):
                        raise ValueError('Natureza da despesa desconhecida')
                    year, month = int(e['year']), int(e['month'])
                    if year < 1900 or year > 2100 or not 1 <= month <= 12:
                        raise ValueError('Competência inválida')
                    supplier = e.get('supplier')
                    key = None
                    if supplier:
                        cnpj = supplier.get('cnpj')
                        if cnpj is not None and not re.fullmatch(r'\d{14}', str(cnpj)):
                            raise ValueError('Identificador público de fornecedor deve ser CNPJ de 14 dígitos; CPF não é aceito')
                        key = 'cnpj:' + cnpj if cnpj else supplier.get('key')
                        if not key or not supplier.get('name'):
                            raise ValueError('Fornecedor sem identidade/nome')
                        db.execute('INSERT INTO suppliers VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET '
                                   'name=excluded.name,cnpj=excluded.cnpj', (key, supplier['name'], cnpj))
                    values = (e['id'], e['authorityId'], e['sourceId'], e.get('date'), year, month,
                              e.get('category') or 'Não informada', money(e['amount']), public_document_id(e.get('documentId')),
                              safe_url(e.get('documentUrl')), key, e['kind'], stamp, stamp)
                    db.execute('''INSERT INTO expenses VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        authorityId=excluded.authorityId,sourceId=excluded.sourceId,date=excluded.date,
                        year=excluded.year,month=excluded.month,category=excluded.category,
                        amountCents=excluded.amountCents,documentId=excluded.documentId,documentUrl=excluded.documentUrl,
                        supplierKey=excluded.supplierKey,kind=excluded.kind,
                        lastChanged=CASE WHEN expenses.amountCents!=excluded.amountCents OR expenses.category!=excluded.category
                         OR expenses.supplierKey IS NOT excluded.supplierKey OR expenses.authorityId IS NOT excluded.authorityId
                         OR expenses.sourceId IS NOT excluded.sourceId OR expenses.date IS NOT excluded.date
                         OR expenses.year IS NOT excluded.year OR expenses.month IS NOT excluded.month
                         OR expenses.documentId IS NOT excluded.documentId OR expenses.documentUrl IS NOT excluded.documentUrl
                         OR expenses.kind IS NOT excluded.kind THEN excluded.lastChanged ELSE expenses.lastChanged END''', values)
                    db.execute('INSERT INTO received_expenses VALUES(?)', (e['id'],))
                    counts['expenses'] += 1
                # Only a successful snapshot replaces records, never an unavailable source.
                for sid in replace_ids:
                    db.execute('DELETE FROM expenses WHERE sourceId=? AND id NOT IN (SELECT id FROM received_expenses)', (sid,))
            db.execute('''UPDATE expenses SET lastChanged=? WHERE supplierKey IN
                (SELECT s.key FROM suppliers s JOIN original_suppliers o ON o.key=s.key
                 WHERE s.name IS NOT o.name OR s.cnpj IS NOT o.cnpj)''', (stamp,))
            db.execute('DELETE FROM suppliers WHERE key NOT IN (SELECT supplierKey FROM expenses WHERE supplierKey IS NOT NULL)')
            db.execute('DELETE FROM authority_totals')
            db.execute("""INSERT INTO authority_totals SELECT authorityId,kind,SUM(amountCents),COUNT(*),
                MIN(printf('%04d-%02d',year,month)),MAX(printf('%04d-%02d',year,month)) FROM expenses GROUP BY authorityId,kind""")
            db.execute('DELETE FROM supplier_totals')
            db.execute('''INSERT INTO supplier_totals SELECT supplierKey,SUM(amountCents),COUNT(*),COUNT(DISTINCT authorityId)
                FROM expenses WHERE supplierKey IS NOT NULL AND kind='reembolso' GROUP BY supplierKey''')
            rebuild_signals(db)
            db.execute("INSERT OR REPLACE INTO meta VALUES('snapshotAt',?)", (stamp,))
        return counts
    finally:
        db.close()


def rows(db, sql, args=()):
    return [dict(row) for row in db.execute(sql, args)]


def amount_rows(items):
    for item in items:
        if 'amountCents' in item:
            item['amount'] = item.pop('amountCents') / 100
    return items


def rebuild_signals(db):
    """Triagem exploratória em reembolsos; não classifica remuneração como fraude."""
    from statistics import median
    db.execute('DELETE FROM signals')
    def add(identifier, authority, source, kind, title, cents, text, period):
        db.execute('INSERT INTO signals VALUES(?,?,?,?,?,?,?,?)', (identifier, authority, source, kind, title, cents, text, period))
    def currency(cents):
        return ('R$ ' + f'{cents / 100:,.2f}').replace(',', 'X').replace('.', ',').replace('X', '.')
    for e in db.execute("SELECT id,authorityId,sourceId,amountCents,year,month FROM expenses WHERE kind='reembolso' AND amountCents>=1000000"):
        add('nota:' + e['id'], e['authorityId'], e['sourceId'], 'nota', 'Lançamento de valor alto', e['amountCents'],
            'Registro de pelo menos R$ 10.000 no arquivo importado. É um corte para conferência, não uma avaliação de preço ou legalidade. Créditos e estornos devem ser verificados no contexto do documento.', f'{e["year"]}-{e["month"]:02d}')
    # A fornecedor is identified by a stable identifier, not a coinciding name.
    groups = rows(db, '''SELECT e.authorityId,e.sourceId,e.supplierKey,e.year,SUM(e.amountCents) cents,s.name
        FROM expenses e JOIN suppliers s ON s.key=e.supplierKey WHERE e.kind='reembolso'
        GROUP BY e.authorityId,e.sourceId,e.supplierKey,e.year HAVING cents>=3000000''')
    totals = {(r['authorityId'], r['sourceId'], r['year']): r['cents'] for r in rows(db,
        "SELECT authorityId,sourceId,year,SUM(amountCents) cents FROM expenses WHERE kind='reembolso' GROUP BY authorityId,sourceId,year")}
    for e in groups:
        total = totals.get((e['authorityId'], e['sourceId'], e['year']), 0)
        if total <= 0 or e['cents'] / total < .5:
            continue
        description = f'{e["name"]}: {currency(e["cents"])} de {currency(total)} em reembolsos líquidos importados ({e["cents"] / total * 100:.1f}%). Critério: pelo menos 50% e R$ 30.000. Contratos recorrentes podem explicar a concentração; confira documentos e serviço.'
        add(f'fornecedor:{e["authorityId"]}:{e["sourceId"]}:{e["year"]}:{e["supplierKey"]}', e['authorityId'], e['sourceId'], 'fornecedor', 'Concentração em fornecedor', e['cents'], description, str(e['year']))
    series = {}
    last_month = {}
    for r in rows(db, "SELECT authorityId,sourceId,year,month,SUM(amountCents) cents FROM expenses WHERE kind='reembolso' GROUP BY authorityId,sourceId,year,month"):
        key = (r['authorityId'], r['sourceId'], r['year'])
        series.setdefault(key, {})[r['month']] = r['cents']
        skey = (r['sourceId'], r['year'])
        last_month[skey] = max(last_month.get(skey, 0), r['month'])
    for (authority, source, year), months in series.items():
        for month, value in months.items():
            # Latest observed month is omitted to reduce partial-period effects.
            if month < 4 or month >= last_month[(source, year)]:
                continue
            before = [months.get(m) for m in range(1, month)]
            if any(v is None or v < 0 for v in before):
                continue
            base = median(before)
            if base <= 0 or value < base * 1.75 or value - base < 1000000:
                continue
            add(f'pico:{authority}:{source}:{year}:{month}', authority, source, 'pico', 'Pico no reembolso mensal', value,
                f'{currency(value)}: {value / base:.2f} vezes a mediana de {currency(base)} entre janeiro e o mês anterior. Critério: 1,75 vez e diferença de R$ 10.000, com ao menos 3 meses anteriores sem lacunas. O último mês da fonte é excluído; meses anteriores ainda podem receber ajustes.', f'{year}-{month:02d}')


def signals(db, params):
    clauses, args = ['1=1'], []
    for field in ('type', 'authorityId', 'sourceId'):
        if params.get(field):
            clauses.append(f's.{field}=?'); args.append(params[field])
    where = ' AND '.join(clauses)
    page, size, offset = page_args(params)
    total = db.execute(f'SELECT COUNT(*) FROM signals s WHERE {where}', args).fetchone()[0]
    items = amount_rows(rows(db, f'''SELECT s.*,a.name authorityName FROM signals s JOIN authorities a ON a.id=s.authorityId
        WHERE {where} ORDER BY CASE s.type WHEN 'pico' THEN 0 WHEN 'fornecedor' THEN 1 ELSE 2 END,s.amountCents DESC,s.id LIMIT ? OFFSET ?''', [*args, size, offset]))
    return {'items': items, 'total': total, 'page': page, 'pageSize': size}


def page_args(params):
    page = max(1, min(10000000, int(params.get('page', 1))))
    size = max(1, min(100, int(params.get('pageSize', 30))))
    return page, size, (page - 1) * size


def query_text(params):
    # Literal substring search, not user-controlled SQL wildcard patterns.
    return '%' + fold(params.get('q', '')[:200]).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def coverage(db):
    sources = rows(db, '''SELECT s.*,(SELECT COUNT(*) FROM authorities a WHERE a.sourceId=s.id) metadataAuthorityCount,
        (SELECT COUNT(DISTINCT authorityId) FROM expenses e WHERE e.sourceId=s.id) expenseAuthorityCount,
        (SELECT COUNT(*) FROM (SELECT a.id FROM authorities a WHERE a.sourceId=s.id
            UNION SELECT e.authorityId FROM expenses e WHERE e.sourceId=s.id)) authorityCount,
        (SELECT COUNT(*) FROM expenses e WHERE e.sourceId=s.id) expenseCount FROM sources s ORDER BY s.label''')
    return {'sources': sources, 'totals': {
        'authorities': db.execute('SELECT COUNT(*) FROM authorities').fetchone()[0],
        'expenses': db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0],
        'suppliers': db.execute('SELECT COUNT(*) FROM supplier_totals').fetchone()[0]},
        'groups': rows(db, 'SELECT role,COUNT(*) count FROM authorities GROUP BY role'),
        'snapshotAt': (db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone() or [None])[0]}


def authorities(db, params):
    clauses, args = ['1=1'], []
    if params.get('q'):
        clauses.append("a.searchText LIKE ? ESCAPE '\\'")
        args.append(query_text(params))
    for key in ('role', 'sphere', 'uf', 'institution', 'sourceId'):
        if params.get(key):
            clauses.append(f'a.{key}=?')
            args.append(params[key])
    where = ' AND '.join(clauses)
    page, size, offset = page_args(params)
    total = db.execute(f'SELECT COUNT(*) FROM authorities a WHERE {where}', args).fetchone()[0]
    items = rows(db, f'''SELECT a.*,COALESCE(r.amountCents,0)/100.0 expenseTotal,COALESCE(r.count,0) expenseCount,
        COALESCE(s.amountCents,0)/100.0 remunerationTotal,COALESCE(s.count,0) remunerationCount
        FROM authorities a LEFT JOIN authority_totals r ON r.authorityId=a.id AND r.kind='reembolso'
        LEFT JOIN authority_totals s ON s.authorityId=a.id AND s.kind='remuneracao'
        WHERE {where} ORDER BY a.name,a.id LIMIT ? OFFSET ?''', [*args, size, offset])
    return {'items': items, 'total': total, 'page': page, 'pageSize': size}


def expense_query(params):
    clauses, args = ['1=1'], []
    for key in ('authorityId', 'supplierKey', 'sourceId', 'category', 'kind'):
        if params.get(key):
            clauses.append(f'e.{key}=?')
            args.append(params[key])
    if params.get('q'):
        clauses.append("fold(a.name||' '||COALESCE(s.name,'')||' '||e.category||' '||COALESCE(s.cnpj,'')) LIKE ? ESCAPE '\\'")
        args.append(query_text(params))
    for key, op in (('from', '>='), ('to', '<=')):
        value = params.get(key)
        if value:
            if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', value):
                raise ValueError('Período inválido; use AAAA-MM')
            clauses.append(f'(e.year*100+e.month){op}?')
            args.append(int(value[:4]) * 100 + int(value[5:7]))
    if params.get('from') and params.get('to') and params['from'][:7] > params['to'][:7]:
        raise ValueError('O início do período deve vir antes do fim')
    if params.get('minAmount'):
        clauses.append('e.amountCents>=?')
        args.append(money(params['minAmount']))
    if params.get('since'):
        clauses.append('e.lastChanged>?')
        since = datetime.fromisoformat(params['since'].replace('Z', '+00:00'))
        if since.tzinfo is None:
            raise ValueError('A data de acompanhamento precisa informar o fuso horário')
        args.append(since.astimezone(timezone.utc).isoformat(timespec='microseconds'))
    order = 'e.amountCents DESC,e.id' if params.get('sort') == 'amount_desc' else 'e.year DESC,e.month DESC,e.date DESC,e.id'
    joins = 'FROM expenses e JOIN authorities a ON a.id=e.authorityId JOIN sources src ON src.id=e.sourceId LEFT JOIN suppliers s ON s.key=e.supplierKey'
    return joins, ' AND '.join(clauses), args, order


EXPENSE_FIELDS = '''e.id,e.authorityId,a.name authorityName,a.role,a.institution,e.sourceId,e.date,e.year,e.month,
 e.category,e.amountCents,e.documentId,e.documentUrl,e.supplierKey,s.name supplierName,s.cnpj,e.kind,e.firstSeen,e.lastChanged,
 src.url sourceUrl,src.label sourceLabel,src.fetchedAt fetchedAt'''


def expenses(db, params):
    joins, where, args, order = expense_query(params)
    page, size, offset = page_args(params)
    totals = db.execute(f'SELECT COUNT(*),COALESCE(SUM(e.amountCents),0) {joins} WHERE {where}', args).fetchone()
    items = amount_rows(rows(db, f'SELECT {EXPENSE_FIELDS} {joins} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?', [*args, size, offset]))
    # Totals across different financial natures are intentionally not combined.
    kind_totals = amount_rows(rows(db, f'SELECT e.kind,SUM(e.amountCents) amountCents,COUNT(*) count {joins} WHERE {where} GROUP BY e.kind', args))
    return {'items': items, 'total': totals[0], 'page': page, 'pageSize': size,
            'totalAmount': totals[1] / 100 if len(kind_totals) <= 1 else None, 'totalsByKind': kind_totals,
            'snapshotAt': (db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone() or [None])[0]}


def percentile(ordered, fraction):
    at = (len(ordered) - 1) * fraction
    lower = math.floor(at)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (at - lower)


def benchmark(db, authority):
    # Select an observed month shared by peers. Do not infer missing records as zero.
    latest = db.execute('SELECT year,month,kind,sourceId FROM expenses WHERE authorityId=? ORDER BY year DESC,month DESC,kind,sourceId,id LIMIT 1', (authority['id'],)).fetchone()
    if not latest:
        return {'available': False, 'reason': 'Sem valores importados para comparar.'}
    year, month, kind, expense_source = latest
    if kind == 'remuneracao' and (authority.get('positionCount', 1) > 1):
        return {'available': False, 'reason': 'Este cadastro reúne vários cargos/vínculos. A remuneração agregada não pode ser comparada como salário de um único cargo.'}
    if kind == 'remuneracao' and not authority.get('position'):
        return {'available': False, 'reason': 'Sem cargo funcional detalhado para comparar remunerações equivalentes.'}
    clauses = "e.sourceId=? AND a.role=? AND a.institution=? AND COALESCE(a.uf,'')=? AND e.year=? AND e.month=? AND e.kind=?"
    params = (expense_source, authority['role'], authority['institution'], authority.get('uf') or '', year, month, kind)
    # Mandate participation and source exercise dates do not define salary peers
    # for reimbursements. Functional position/status apply only to remuneration.
    if kind == 'remuneracao':
        clauses += " AND COALESCE(a.position,'')=? AND COALESCE(a.employmentStatus,'')=? AND COALESCE(a.positionCount,1)=1"
        params += (authority.get('position') or '', authority.get('employmentStatus') or '')
    group = rows(db, f'''SELECT a.id,SUM(e.amountCents) value FROM authorities a JOIN expenses e ON e.authorityId=a.id
        WHERE {clauses} GROUP BY a.id''', params)
    peers = sorted(r['value'] / 100 for r in group if r['id'] != authority['id'])
    value = next((r['value'] / 100 for r in group if r['id'] == authority['id']), None)
    if len(peers) < 5:
        return {'available': False, 'peerCount': len(peers), 'reason': 'A comparação exige pelo menos 5 outras pessoas com registros na mesma fonte, órgão, cargo, UF, natureza e mês.'}
    scope = 'Mesma fonte, órgão, cargo' + (', situação funcional' if kind == 'remuneracao' else '')
    scope += f' e UF ({authority.get("uf") or "não informada"}). '
    scope += 'Somente pessoas com registros neste mês; o mês pode estar incompleto. Diferença não comprova irregularidade.'
    return {'available': True, 'peerCount': len(peers), 'median': percentile(peers, .5),
            'q1': percentile(peers, .25), 'q3': percentile(peers, .75), 'amount': value,
            'period': f'{year:04d}-{month:02d}', 'kind': kind,
            'scope': scope}


def authority_detail(db, identifier):
    matches = rows(db, 'SELECT * FROM authorities WHERE id=?', (identifier,))
    if not matches:
        return None
    authority = matches[0]
    authority['positions'] = json.loads(authority.get('positions') or '[]')
    return {'authority': authority,
            'summary': amount_rows(rows(db, 'SELECT kind,amountCents,count,periodStart,periodEnd FROM authority_totals WHERE authorityId=?', (identifier,))),
            'categories': amount_rows(rows(db, 'SELECT category,kind,SUM(amountCents) amountCents,COUNT(*) count FROM expenses WHERE authorityId=? GROUP BY category,kind ORDER BY amountCents DESC', (identifier,))),
            'monthly': amount_rows(rows(db, 'SELECT year,month,kind,SUM(amountCents) amountCents FROM expenses WHERE authorityId=? GROUP BY year,month,kind ORDER BY year,month', (identifier,))),
            'signals': signals(db, {'authorityId': identifier, 'pageSize': 10})['items'],
            'signalCount': db.execute('SELECT COUNT(*) FROM signals WHERE authorityId=?', (identifier,)).fetchone()[0],
            'benchmark': benchmark(db, authority)}


def suppliers(db, params):
    where, args = '1=1', []
    if params.get('q'):
        where = "fold(s.name||' '||COALESCE(s.cnpj,'')) LIKE ? ESCAPE '\\'"
        args = [query_text(params)]
    page, size, offset = page_args(params)
    joins = 'FROM suppliers s JOIN supplier_totals t ON t.supplierKey=s.key'
    total = db.execute(f'SELECT COUNT(*) {joins} WHERE {where}', args).fetchone()[0]
    items = rows(db, f'SELECT s.*,t.amountCents/100.0 total,t.count,t.authorityCount {joins} WHERE {where} ORDER BY t.amountCents DESC,s.key LIMIT ? OFFSET ?', [*args, size, offset])
    return {'items': items, 'total': total, 'page': page, 'pageSize': size}


def supplier_detail(db, identifier):
    matches = rows(db, 'SELECT * FROM suppliers WHERE key=?', (identifier,))
    if not matches:
        return None
    summary = amount_rows(rows(db, 'SELECT amountCents,count,authorityCount FROM supplier_totals WHERE supplierKey=?', (identifier,)))
    return {'supplier': matches[0], 'summary': summary[0] if summary else {'amount': 0, 'count': 0, 'authorityCount': 0},
            'authorities': amount_rows(rows(db, 'SELECT a.id,a.name,a.role,SUM(e.amountCents) amountCents,COUNT(*) count FROM expenses e JOIN authorities a ON a.id=e.authorityId WHERE e.supplierKey=? GROUP BY a.id ORDER BY amountCents DESC', (identifier,))),
            'categories': amount_rows(rows(db, 'SELECT category,SUM(amountCents) amountCents,COUNT(*) count FROM expenses WHERE supplierKey=? GROUP BY category ORDER BY amountCents DESC', (identifier,))),
            'monthly': amount_rows(rows(db, 'SELECT year,month,SUM(amountCents) amountCents FROM expenses WHERE supplierKey=? GROUP BY year,month ORDER BY year,month', (identifier,)))}


def csv_chunks(db, params):
    joins, where, args, order = expense_query(params)
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=';')
    def line(values):
        safe = ["'" + str(v) if re.match(r'^[\s\x00-\x1f]*[=+@-]', str(v)) else str(v) for v in values]
        writer.writerow(safe)
        value = stream.getvalue()
        stream.seek(0); stream.truncate(0)
        return value
    yield '\ufeff' + line(['ID', 'Autoridade', 'Cargo', 'Órgão', 'Natureza', 'Competência', 'Emissão', 'Categoria', 'Valor conforme categoria da fonte (R$)', 'Fornecedor', 'CNPJ', 'Documento', 'Link do documento', 'Fonte', 'Link da fonte', 'Data da coleta'])
    for record in db.execute(f'SELECT {EXPENSE_FIELDS} {joins} WHERE {where} ORDER BY {order}', args):
        e = dict(record)
        yield line([e['id'], e['authorityName'], e['role'], e['institution'], e['kind'], f'{e["year"]:04d}-{e["month"]:02d}',
                    e['date'] or '', e['category'], format(Decimal(e['amountCents']) / 100, '.2f').replace('.', ','),
                    e['supplierName'] or '', e['cnpj'] or '', e['documentId'] or '', e['documentUrl'] or '', e['sourceId'], e['sourceUrl'] or '', e['fetchedAt'] or ''])


def _import_paths(files, import_dir):
    if files:
        missing = [path for path in files if not path.is_file()]
        if missing:
            raise ValueError('Arquivo de importação não encontrado: ' + ', '.join(map(str, missing)))
        return files
    if not import_dir.is_dir():
        raise ValueError(
            f'Pasta de importação não encontrada: {import_dir}. Informe arquivos JSON ou JSONL.'
        )
    paths = sorted(
        path for path in import_dir.iterdir()
        if path.is_file() and path.name.endswith(('.json', '.jsonl', '.jsonl.gz'))
    )
    if not paths:
        raise ValueError(
            f'Nenhum arquivo JSON ou JSONL para importar em {import_dir}. Informe os arquivos.'
        )
    return paths


def main(argv=None, import_dir=None):
    import argparse
    parser = argparse.ArgumentParser(description='Importa conjuntos normalizados de dados públicos no banco local')
    parser.add_argument('files', nargs='*', type=Path)
    parser.add_argument('--db', type=Path, default=DB_PATH)
    args = parser.parse_args(argv)
    try:
        paths = _import_paths(args.files, Path(import_dir) if import_dir else ROOT / 'data' / 'imports')
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(import_documents(paths, args.db), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
