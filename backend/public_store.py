"""Importação dos dados públicos normalizados e sinais de triagem; valores em centavos."""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from .config import DB_PATH, ROOT, ROSTER_SOURCES
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
                listed = {}
                for a in payload.get('authorities', []):
                    if not a.get('id') or not a.get('name') or a.get('sourceId') not in source_ids:
                        raise ValueError(f'Autoridade sem identidade/fonte: {a.get("id")}')
                    listed.setdefault(a['sourceId'], []).append(a['id'])
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
                # Só uma lista oficial completa troca quem está em exercício. Quem sai deixa de ser atual,
                # mas o cadastro e as despesas ficam; uma coleta indisponível mantém a lista anterior.
                for s in sources:
                    if s['id'] in ROSTER_SOURCES and s.get('status') == 'imported' and listed.get(s['id']):
                        db.execute('DELETE FROM roster WHERE sourceId=?', (s['id'],))
                        db.executemany('INSERT OR IGNORE INTO roster(sourceId,authorityId) VALUES(?,?)',
                                       [(s['id'], authority_id) for authority_id in listed[s['id']]])
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
    # Piso pelos colegas: o "normal" de cada um é só dele, então quem gasta muito pouco disparava alerta
    # com um mês comum. Um pico só conta se o mês também passar do gasto mensal típico (mediana) dos
    # parlamentares da mesma fonte e ano, considerando apenas meses fechados.
    peer_months = {}
    for (authority, source, year), months in series.items():
        for month, value in months.items():
            if month < last_month[(source, year)] and value > 0:
                peer_months.setdefault((source, year), []).append(value)
    peer_floor = {k: median(v) for k, v in peer_months.items() if len(v) >= 5}
    for (authority, source, year), months in series.items():
        floor = peer_floor.get((source, year), 0)
        flagged = {}
        for month, value in months.items():
            # Latest observed month is omitted to reduce partial-period effects.
            if month < 4 or month >= last_month[(source, year)]:
                continue
            before = [months.get(m) for m in range(1, month)]
            if any(v is None or v < 0 for v in before):
                continue
            base = median(before)
            if base <= 0 or value < base * 1.75 or value - base < 1000000 or value < floor:
                continue
            flagged[month] = (value, base)
        # Meses seguidos acima do normal são uma mudança de patamar: viram um alerta só, no primeiro mês.
        for month in sorted(flagged):
            if month - 1 in flagged:
                continue
            value, base = flagged[month]
            run = [month]
            while run[-1] + 1 in flagged:
                run.append(run[-1] + 1)
            seguidos = f' Continuou acima do habitual em {len(run) - 1} mês(es) seguido(s); conta como um único alerta.' if len(run) > 1 else ''
            add(f'pico:{authority}:{source}:{year}:{month}', authority, source, 'pico', 'Pico no reembolso mensal', value,
                f'{currency(value)}: {value / base:.2f} vezes a mediana de {currency(base)} entre janeiro e o mês anterior. Critério: 1,75 vez, diferença de R$ 10.000 e acima do gasto mensal típico dos parlamentares da mesma fonte ({currency(floor)}), com ao menos 3 meses anteriores sem lacunas.{seguidos} O último mês da fonte é excluído; meses anteriores ainda podem receber ajustes.', f'{year}-{month:02d}')


def page_args(params):
    page = max(1, min(10000000, int(params.get('page', 1))))
    size = max(1, min(100, int(params.get('pageSize', 30))))
    return page, size, (page - 1) * size


def query_text(params):
    # Literal substring search, not user-controlled SQL wildcard patterns.
    return '%' + fold(params.get('q', '')[:200]).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


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
