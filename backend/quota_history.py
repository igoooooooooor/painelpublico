"""Importa as notas da cota de anos anteriores do mandato, Câmara e Senado (esquema v5).

Lê ``data/imports-history/{camara-ceap,senado-ceaps}-{ano}.json`` (gerados por
``ingest/quota_history.py``). Cada arquivo substitui só as notas da sua Casa e ano
(fonte ``camara_ceap_{ano}`` ou ``senado_ceaps_{ano}``), numa transação; as notas
detalhadas de 2026 não são tocadas. Os alertas são recalculados, porque avaliam o mandato inteiro.
Cadastros que já existem não são alterados.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH, ROOT
from .database import fold, migrate
from .public_store import connect, rebuild_aggregates, safe_url

HISTORY_DIR = ROOT / 'data' / 'imports-history'
AUTHORITY_COLUMNS = ('id', 'name', 'role', 'branch', 'sphere', 'institution', 'uf', 'party', 'sourceId',
                     'sourceUrl', 'position', 'employmentStatus', 'positions', 'searchText')
# Prefixo comum dos links de notas da Câmara; a visão quota_history o devolve.
DOCUMENT_PREFIX = 'https://www.camara.leg.br/cota-parlamentar/'
HOUSE_PREFIX = {'camara': 'camara:', 'senado': 'senado:'}


def _validate(payload):
    source = payload.get('source') or {}
    year, house = payload.get('year'), payload.get('house')
    expected = {'camara': f'camara_ceap_{year}', 'senado': f'senado_ceaps_{year}'}.get(house)
    if not expected or source.get('id') != expected:
        raise ValueError('Arquivo de histórico sem Casa e fonte camara_ceap_<ano> ou senado_ceaps_<ano>')
    if not source.get('label') or source.get('status') != 'imported':
        raise ValueError(f'Fonte {source.get("id")} sem nome ou incompleta')
    for note in payload.get('notes', []):
        if (not 1 <= int(note['month']) <= 12 or note['kind'] not in ('reembolso', 'complemento_moradia')
                or not str(note['authorityId']).startswith(HOUSE_PREFIX[house])):
            raise ValueError('Nota inválida no arquivo de histórico')
        cnpj = (note.get('supplier') or {}).get('cnpj')
        if cnpj is not None and not re.fullmatch(r'\d{14}', str(cnpj)):
            raise ValueError('Fornecedor com identificador que não é CNPJ')
    return source, int(year), house


def _document_path(url):
    url = safe_url(url)
    return url[len(DOCUMENT_PREFIX):] if url and url.startswith(DOCUMENT_PREFIX) else url


def import_history(paths, db_path=DB_PATH):
    db = connect(db_path)
    migrate(db)
    counts = {'sources': 0, 'authorities': 0, 'notes': 0}
    try:
        with db:
            for path in paths:
                payload = json.loads(Path(path).read_text(encoding='utf-8'))
                source, year, house = _validate(payload)
                sid = source['id']
                db.execute('INSERT INTO sources(id,label,url,scope,period,status,detail,fetchedAt,dataFetchedAt) '
                           'VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                           'label=excluded.label,url=excluded.url,scope=excluded.scope,period=excluded.period,'
                           'status=excluded.status,detail=excluded.detail,fetchedAt=excluded.fetchedAt,'
                           'dataFetchedAt=excluded.dataFetchedAt',
                           (sid, source['label'], safe_url(source.get('url')), source.get('scope'), source.get('period'),
                            source['status'], source.get('detail'), source.get('fetchedAt'), source.get('fetchedAt')))
                counts['sources'] += 1
                for a in payload.get('authorities', []):
                    # Só cadastra quem ainda não existe (ex.: quem saiu antes de 2026); não muda cadastros atuais.
                    values = [a.get(key) for key in AUTHORITY_COLUMNS[:8]] + [sid, safe_url(a.get('sourceUrl')),
                              a.get('position'), a.get('employmentStatus'), '[]',
                              fold(a['name'] + ' ' + (a.get('institution') or ''))]
                    counts['authorities'] += db.execute(
                        f'INSERT OR IGNORE INTO authorities ({",".join(AUTHORITY_COLUMNS)}) VALUES({",".join("?" * len(AUTHORITY_COLUMNS))})',
                        values).rowcount
                notes = payload.get('notes', [])
                db.executemany('INSERT OR IGNORE INTO quota_categories(name) VALUES(?)', {(n['category'],) for n in notes})
                categories = dict(db.execute('SELECT name,id FROM quota_categories'))
                # Nome e CNPJ ficam na tabela de fornecedores; um nome já conhecido não é trocado.
                db.executemany('INSERT OR IGNORE INTO suppliers VALUES(?,?,?)', {
                    (n['supplier']['key'], n['supplier']['name'], n['supplier'].get('cnpj')) for n in notes if n.get('supplier')})
                db.execute('DELETE FROM quota_history_notes WHERE year=? AND authorityId LIKE ?', (year, HOUSE_PREFIX[house] + '%'))
                sequence, rows = {}, []
                for n in notes:
                    key = (n['authorityId'], int(n['month']))
                    sequence[key] = sequence.get(key, 0) + 1
                    rows.append((n['authorityId'], year, int(n['month']), sequence[key], n.get('date'), categories[n['category']],
                                 int(n['amountCents']), 1 if n['kind'] == 'complemento_moradia' else 0,
                                 (n.get('supplier') or {}).get('key'), _document_path(n.get('documentUrl')), n.get('airline')))
                db.executemany('INSERT INTO quota_history_notes(authorityId,year,month,seq,date,categoryId,amountCents,'
                               'complement,supplierKey,documentPath,airline) VALUES(?,?,?,?,?,?,?,?,?,?,?)', rows)
                counts['notes'] += len(rows)
            db.execute('DELETE FROM quota_categories WHERE id NOT IN (SELECT categoryId FROM quota_history_notes)')
            rebuild_aggregates(db)
            db.execute("INSERT OR REPLACE INTO meta VALUES('historyImportedAt',?)",
                       (datetime.now(timezone.utc).isoformat(timespec='seconds'),))
        return counts
    finally:
        db.close()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Importa as notas da cota de anos anteriores do mandato')
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
