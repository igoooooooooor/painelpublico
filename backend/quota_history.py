"""Importa os agregados da cota de anos anteriores do mandato, Câmara e Senado (esquema v4).

Lê ``data/imports-history/{camara-ceap,senado-ceaps}-{ano}.json`` (gerados por
``ingest/quota_history.py``). Cada arquivo substitui só as linhas da sua
fonte (``camara_ceap_{ano}`` ou ``senado_ceaps_{ano}``), numa transação; as notas
detalhadas de 2026 e os alertas não são tocados. Cadastros que já existem não são alterados.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH, ROOT
from .database import fold, migrate
from .public_store import connect, rebuild_aggregates, safe_url

HISTORY_DIR = ROOT / 'data' / 'imports-history'
AUTHORITY_COLUMNS = ('id', 'name', 'role', 'branch', 'sphere', 'institution', 'uf', 'party', 'sourceId',
                     'sourceUrl', 'position', 'employmentStatus', 'positions', 'searchText')


def _validate(payload):
    source = payload.get('source') or {}
    year = payload.get('year')
    if source.get('id') not in (f'camara_ceap_{year}', f'senado_ceaps_{year}'):
        raise ValueError('Arquivo de histórico sem fonte camara_ceap_<ano> ou senado_ceaps_<ano>')
    if not source.get('label') or source.get('status') != 'imported':
        raise ValueError(f'Fonte {source.get("id")} sem nome ou incompleta')
    for row in payload.get('months', []):
        if not 1 <= int(row['month']) <= 12 or row['kind'] not in ('reembolso', 'complemento_moradia'):
            raise ValueError('Linha mensal inválida')
    return source, int(year)


def import_history(paths, db_path=DB_PATH):
    db = connect(db_path)
    migrate(db)
    counts = {'sources': 0, 'authorities': 0, 'months': 0, 'suppliers': 0, 'largest': 0}
    try:
        with db:
            for path in paths:
                payload = json.loads(Path(path).read_text(encoding='utf-8'))
                source, year = _validate(payload)
                sid = source['id']
                db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                           'label=excluded.label,url=excluded.url,scope=excluded.scope,period=excluded.period,'
                           'status=excluded.status,detail=excluded.detail,fetchedAt=excluded.fetchedAt',
                           (sid, source['label'], safe_url(source.get('url')), source.get('scope'), source.get('period'),
                            source['status'], source.get('detail'), source.get('fetchedAt')))
                counts['sources'] += 1
                for a in payload.get('authorities', []):
                    # Só cadastra quem ainda não existe (ex.: quem saiu antes de 2026); não muda cadastros atuais.
                    values = [a.get(key) for key in AUTHORITY_COLUMNS[:8]] + [sid, safe_url(a.get('sourceUrl')),
                              a.get('position'), a.get('employmentStatus'), '[]',
                              fold(a['name'] + ' ' + (a.get('institution') or ''))]
                    counts['authorities'] += db.execute(
                        f'INSERT OR IGNORE INTO authorities ({",".join(AUTHORITY_COLUMNS)}) VALUES({",".join("?" * len(AUTHORITY_COLUMNS))})',
                        values).rowcount
                for table in ('quota_history_months', 'quota_history_suppliers', 'quota_history_largest'):
                    db.execute(f'DELETE FROM {table} WHERE sourceId=?', (sid,))
                db.executemany('INSERT INTO quota_history_months VALUES(?,?,?,?,?,?,?,?)', [
                    (r['authorityId'], sid, year, int(r['month']), r['category'], r['kind'], int(r['amountCents']), int(r['count']))
                    for r in payload.get('months', [])])
                # Nome e CNPJ ficam na tabela de fornecedores; um nome já conhecido não é trocado.
                db.executemany('INSERT OR IGNORE INTO suppliers VALUES(?,?,?)', {
                    (r['supplierKey'], r['name'], r.get('cnpj')) for r in payload.get('suppliers', [])})
                db.executemany('INSERT INTO quota_history_suppliers VALUES(?,?,?,?,?)', [
                    (r['authorityId'], sid, r['supplierKey'], int(r['amountCents']), int(r['count']))
                    for r in payload.get('suppliers', [])])
                db.executemany('INSERT INTO quota_history_largest VALUES(?,?,?,?,?,?,?,?,?,?)', [
                    (r['authorityId'], sid, int(r['rank']), r.get('date'), year, int(r['month']), r.get('category'),
                     int(r['amountCents']), safe_url(r.get('documentUrl')), r.get('supplierName'))
                    for r in payload.get('largest', [])])
                counts['months'] += len(payload.get('months', []))
                counts['suppliers'] += len(payload.get('suppliers', []))
                counts['largest'] += len(payload.get('largest', []))
            rebuild_aggregates(db)
            db.execute("INSERT OR REPLACE INTO meta VALUES('historyImportedAt',?)",
                       (datetime.now(timezone.utc).isoformat(timespec='seconds'),))
        return counts
    finally:
        db.close()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Importa os agregados da cota da Câmara de anos anteriores do mandato')
    parser.add_argument('files', nargs='*', type=Path)
    parser.add_argument('--db', type=Path, default=DB_PATH)
    args = parser.parse_args(argv)
    paths = args.files or sorted([*HISTORY_DIR.glob('camara-ceap-*.json'), *HISTORY_DIR.glob('senado-ceaps-*.json')])
    if not paths:
        parser.error(f'Nenhum arquivo em {HISTORY_DIR}; rode ingest/quota_history.py antes.')
    print(json.dumps(import_history(paths, args.db), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
