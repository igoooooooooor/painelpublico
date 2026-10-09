"""Importação dos dados públicos normalizados e sinais de triagem; valores em centavos."""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from .config import DB_PATH, HOUSING_COMPLEMENT_KIND, ROOT, ROSTER_SOURCES
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
                    db.execute(f'INSERT INTO sources({",".join(columns)}) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                               'label=excluded.label,url=excluded.url,scope=excluded.scope,period=excluded.period,'
                               'status=excluded.status,detail=excluded.detail,fetchedAt=excluded.fetchedAt', values)
                    # Só uma coleta que forneceu as notas muda a data usada nos prazos dos alertas;
                    # uma tentativa indisponível atualiza o status, não essa data.
                    if s.get('status') in ('imported', 'partial'):
                        db.execute('UPDATE sources SET dataFetchedAt=fetchedAt WHERE id=?', (s['id'],))
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
                    if e.get('kind') not in ('reembolso', 'remuneracao', HOUSING_COMPLEMENT_KIND):
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
                              safe_url(e.get('documentUrl')), key, e['kind'], stamp, stamp, e.get('airline'))
                    db.execute('''INSERT INTO expenses(id,authorityId,sourceId,date,year,month,category,amountCents,documentId,
                        documentUrl,supplierKey,kind,firstSeen,lastChanged,airline) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        airline=excluded.airline,
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
            db.execute('''DELETE FROM suppliers WHERE key NOT IN (SELECT supplierKey FROM expenses WHERE supplierKey IS NOT NULL)
                AND key NOT IN (SELECT supplierKey FROM quota_history_notes WHERE supplierKey IS NOT NULL)''')
            rebuild_aggregates(db)
            db.execute("INSERT OR REPLACE INTO meta VALUES('snapshotAt',?)", (stamp,))
        return counts
    finally:
        db.close()


def rows(db, sql, args=()):
    return [dict(row) for row in db.execute(sql, args)]


def rebuild_aggregates(db):
    """Totais por pessoa e fornecedor e sinais, recalculados a partir das despesas."""
    # A migração pode chamar com uma conexão sem row_factory; os sinais leem colunas por nome.
    previous_factory, db.row_factory = db.row_factory, sqlite3.Row
    try:
        _rebuild_aggregates(db)
    finally:
        db.row_factory = previous_factory


def _rebuild_aggregates(db):
    db.execute('DELETE FROM authority_totals')
    # Notas detalhadas do ano corrente mais as notas enxutas dos anos anteriores do mandato.
    db.execute("""INSERT INTO authority_totals(authorityId,kind,amountCents,count,periodStart,periodEnd,monthCount)
        SELECT authorityId,kind,SUM(cents),SUM(n),MIN(period),MAX(period),COUNT(DISTINCT period) FROM (
        SELECT authorityId,kind,amountCents cents,1 n,printf('%04d-%02d',year,month) period FROM expenses
        UNION ALL
        SELECT authorityId,kind,amountCents,1,printf('%04d-%02d',year,month) FROM quota_history
        ) GROUP BY authorityId,kind""")
    db.execute('DELETE FROM supplier_totals')
    db.execute('''INSERT INTO supplier_totals SELECT supplierKey,SUM(amountCents),COUNT(*),COUNT(DISTINCT authorityId)
        FROM expenses WHERE supplierKey IS NOT NULL AND kind='reembolso' GROUP BY supplierKey''')
    rebuild_signals(db)


def alert_inputs(db):
    """Notas de reembolso do mandato (fev/2023 em diante) e data da última coleta com notas de cada fonte.

    Junta as notas detalhadas do ano corrente (expenses) e as dos anos anteriores (visão quota_history),
    com identificadores estáveis para o histórico. É a mesma entrada dos alertas gravados e da simulação.
    """
    from .alert_rules import MANDATE_START
    records = rows(db, '''SELECT e.id,e.authorityId,e.sourceId,e.year,e.month,e.supplierKey,s.name supplierName,e.amountCents,e.airline
          FROM expenses e LEFT JOIN suppliers s ON s.key=e.supplierKey WHERE e.kind='reembolso'
        UNION ALL
        SELECT 'hist:'||h.authorityId||':'||h.year||':'||h.month||':'||h.seq,h.authorityId,h.sourceId,h.year,h.month,
               h.supplierKey,s.name,h.amountCents,h.airline
          FROM quota_history h LEFT JOIN suppliers s ON s.key=h.supplierKey
         WHERE h.kind='reembolso' AND (h.year>? OR (h.year=? AND h.month>=?))''', (MANDATE_START[0], *MANDATE_START))
    records = [r for r in records if (int(r['year']), int(r['month'])) >= MANDATE_START]
    fetched = {r['id']: r['dataFetchedAt'] for r in rows(db, 'SELECT id,dataFetchedAt FROM sources')}
    return records, fetched


def rebuild_signals(db):
    """Triagem exploratória em reembolsos; não classifica remuneração como fraude.

    Picos e concentração vêm de backend/alert_rules.py, que grava o resultado de cada alerta,
    a cobertura por regra e período e o valor das despesas nos alertas sem dupla contagem.
    Avalia as notas do mandato (fev/2023 em diante) com a base publicada (12 meses anteriores completos).
    Lançamentos de valor alto (tipo 'nota') continuam só nas notas detalhadas do ano corrente.
    """
    from . import alert_rules
    for table in ('signals', 'alert_coverage', 'alert_totals'):
        db.execute(f'DELETE FROM {table}')
    def add(identifier, authority, source, kind, title, cents, text, period, detail=None):
        db.execute('INSERT INTO signals VALUES(?,?,?,?,?,?,?,?,?)',
                   (identifier, authority, source, kind, title, cents, text, period,
                    json.dumps(detail, ensure_ascii=False) if detail is not None else None))
    for e in db.execute("SELECT id,authorityId,sourceId,amountCents,year,month FROM expenses WHERE kind='reembolso' AND amountCents>=1000000"):
        add('nota:' + e['id'], e['authorityId'], e['sourceId'], 'nota', 'Lançamento de valor alto', e['amountCents'],
            'Registro de pelo menos R$ 10.000 no arquivo importado. É um corte para conferência, não uma avaliação de preço ou legalidade. Créditos e estornos devem ser verificados no contexto do documento.', f'{e["year"]}-{e["month"]:02d}')
    records, fetched = alert_inputs(db)
    result = alert_rules.evaluate(records, fetched, alert_rules.PUBLISHED_BASELINE)
    for signal in result['signals']:
        add(signal['id'], signal['authorityId'], signal['sourceId'], signal['type'], signal['title'],
            signal['amountCents'], alert_rules.describe(signal), signal['period'], signal['detail'])
    db.executemany('INSERT INTO alert_coverage VALUES(?,?,?,?,?)', [
        (c['authorityId'], c['sourceId'], c['year'], c['rule'], json.dumps(c['detail'], ensure_ascii=False))
        for c in result['coverage']])
    db.executemany('INSERT INTO alert_totals VALUES(?,?,?,?)', [
        (authority, t['amountCents'], t['records'], int(t['partial'])) for authority, t in result['totals'].items()])
    db.execute("INSERT OR REPLACE INTO meta VALUES('alertRuleVersion',?)", (alert_rules.RULE_VERSION,))


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
