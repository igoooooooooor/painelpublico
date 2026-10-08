"""SQLite schema migrations and local database maintenance commands."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .config import (DB_PATH, HOUSING_COMPLEMENT_CATEGORY, HOUSING_COMPLEMENT_KIND, HOUSING_COMPLEMENT_SOURCE,
                     ROOT, ROSTER_SOURCES, SCHEMA_PATH, SCHEMA_VERSION)


def fold(value):
    return ''.join(
        char for char in unicodedata.normalize('NFKD', str(value or '')).casefold()
        if not unicodedata.combining(char)
    )


def _schema_statements(schema):
    """Yield complete SQLite statements while respecting quoted semicolons."""
    pending = ''
    for line in schema.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                yield statement
            pending = ''
    if pending.strip():
        raise ValueError('Declaração incompleta em backend/schema.sql')


def migrate(db):
    """Create the current schema and upgrade legacy authority columns atomically."""
    db.create_function('fold', 1, fold, deterministic=True)
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f'Banco na versão {version}; esta versão do backend suporta até {SCHEMA_VERSION}.'
        )

    try:
        db.execute('BEGIN IMMEDIATE')
        for statement in _schema_statements(SCHEMA_PATH.read_text(encoding='utf-8')):
            db.execute(statement)

        authority_columns = {
            row[1] for row in db.execute('PRAGMA table_info(authorities)')
        }
        additions = (
            ('position', 'TEXT'),
            ('employmentStatus', 'TEXT'),
            ('positionCount', 'INTEGER DEFAULT 1'),
            ('positions', 'TEXT'),
            ('searchText', 'TEXT'),
        )
        added_search_text = False
        for column, definition in additions:
            if column not in authority_columns:
                db.execute(f'ALTER TABLE authorities ADD COLUMN {column} {definition}')
                added_search_text = added_search_text or column == 'searchText'
        if added_search_text:
            db.execute(
                "UPDATE authorities SET searchText=fold(name||' '||COALESCE(institution,''))"
            )

        if version < 2:
            # v2: o pertencimento às listas oficiais sai de authorities.sourceId para a tabela roster.
            marks = ','.join('?' * len(ROSTER_SOURCES))
            db.execute(f'INSERT OR IGNORE INTO roster(sourceId,authorityId) SELECT sourceId,id FROM authorities '
                       f'WHERE sourceId IN ({marks})', ROSTER_SOURCES)

        # v5: as notas de anos anteriores substituem os agregados da v4 (mês, fornecedor e maiores notas).
        dropped = False
        for table in ('quota_history_months', 'quota_history_suppliers', 'quota_history_largest'):
            dropped = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() or dropped
            db.execute(f'DROP TABLE IF EXISTS {table}')

        # v7: companhia aérea citada nas passagens (evidência de intermediação por agência).
        for table in ('expenses', 'quota_history_notes'):
            if 'airline' not in {row[1] for row in db.execute(f'PRAGMA table_info({table})')}:
                db.execute(f'ALTER TABLE {table} ADD COLUMN airline TEXT')
        db.execute('DROP VIEW IF EXISTS quota_history')
        for statement in _schema_statements(SCHEMA_PATH.read_text(encoding='utf-8')):
            if statement.startswith('CREATE VIEW'):
                db.execute(statement)

        # v7: data da última coleta que forneceu as notas, separada da última tentativa (prazos dos alertas).
        if 'dataFetchedAt' not in {row[1] for row in db.execute('PRAGMA table_info(sources)')}:
            db.execute('ALTER TABLE sources ADD COLUMN dataFetchedAt TEXT')
            # Sem histórico de tentativas, a melhor evidência é a data das fontes que estão importadas.
            db.execute("UPDATE sources SET dataFetchedAt=fetchedAt WHERE status IN ('imported','partial')")
            dropped = True

        # v6: o resultado de cada alerta fica gravado; refaz os sinais com a regra em backend/alert_rules.py.
        if 'detail' not in {row[1] for row in db.execute('PRAGMA table_info(signals)')}:
            db.execute('ALTER TABLE signals ADD COLUMN detail TEXT')
            dropped = True

        # v4: meses com notas por pessoa, denominador da média mensal da cota.
        if 'monthCount' not in {row[1] for row in db.execute('PRAGMA table_info(authority_totals)')}:
            db.execute('ALTER TABLE authority_totals ADD COLUMN monthCount INTEGER')
            dropped = True
        if dropped:
            from .public_store import rebuild_aggregates
            rebuild_aggregates(db)

        if version < 3:
            # v3: o complemento de moradia da CEAP deixa de ser reembolso e não reduz mais a cota.
            changed = db.execute(
                "UPDATE expenses SET kind=? WHERE sourceId=? AND kind='reembolso' AND category=?",
                (HOUSING_COMPLEMENT_KIND, HOUSING_COMPLEMENT_SOURCE, HOUSING_COMPLEMENT_CATEGORY)).rowcount
            if changed:
                from .public_store import rebuild_aggregates
                rebuild_aggregates(db)

        db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        db.commit()
    except Exception:
        db.rollback()
        raise
    return SCHEMA_VERSION



def ensure_schema(path):
    """Atualiza o esquema de um banco existente antes de servi-lo; não cria banco novo."""
    path = Path(path)
    if not path.is_file():
        return None
    db = sqlite3.connect(path, timeout=30)
    try:
        if db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION:
            return SCHEMA_VERSION
        db.execute('PRAGMA foreign_keys=ON')
        return migrate(db)
    finally:
        db.close()


def _connect_read_only(path):
    uri = f'{Path(path).resolve().as_uri()}?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def check_database(path):
    """Inspect an existing database without creating or changing it."""
    path = Path(path)
    if not path.is_file():
        return {'database': str(path), 'status': 'missing', 'ok': False}

    expected_tables = ('sources', 'authorities', 'expenses', 'suppliers', 'signals', 'roster')
    db = _connect_read_only(path)
    try:
        quick_check = [row[0] for row in db.execute('PRAGMA quick_check')]
        foreign_key_errors = [dict(row) for row in db.execute('PRAGMA foreign_key_check')]
        version = db.execute('PRAGMA user_version').fetchone()[0]
        existing = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing_tables = [table for table in expected_tables if table not in existing]
        counts = {
            table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in expected_tables if table in existing
        }
        snapshot = None
        if 'meta' in existing:
            row = db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone()
            snapshot = row[0] if row else None
    finally:
        db.close()

    ok = (
        quick_check == ['ok']
        and not foreign_key_errors
        and version == SCHEMA_VERSION
        and not missing_tables
    )
    return {
        'database': str(path),
        'status': 'ok' if ok else 'needs_attention',
        'ok': ok,
        'schemaVersion': version,
        'expectedSchemaVersion': SCHEMA_VERSION,
        'quickCheck': quick_check,
        'foreignKeyErrors': foreign_key_errors,
        'missingTables': missing_tables,
        'counts': counts,
        'snapshotAt': snapshot,
    }


def _reserve_backup_path(path):
    """Create an empty destination exclusively so backups never overwrite files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    return path


def backup_database(source_path, output_path=None):
    """Create a consistent online backup at a path that does not already exist."""
    source_path = Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(f'Banco de origem não encontrado: {source_path}')

    if output_path is None:
        backup_dir = ROOT / 'data' / 'backups'
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output_path = backup_dir / f'na-lupa-{stamp}.sqlite3'
        suffix = 1
        while output_path.exists():
            output_path = backup_dir / f'na-lupa-{stamp}-{suffix}.sqlite3'
            suffix += 1
    else:
        output_path = Path(output_path)

    if source_path.resolve() == output_path.resolve():
        raise ValueError('O arquivo de backup precisa ser diferente do banco de origem.')
    _reserve_backup_path(output_path)

    try:
        source = _connect_read_only(source_path)
        destination = sqlite3.connect(output_path, timeout=30)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return output_path


def _build_parser():
    parser = argparse.ArgumentParser(description='Administra o banco SQLite local')
    commands = parser.add_subparsers(dest='command', required=True)
    for name, help_text in (
        ('init', 'Cria o esquema ou atualiza a versão do banco'),
        ('check', 'Verifica um banco existente sem alterá-lo'),
        ('backup', 'Cria uma cópia online e consistente do banco'),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument('--db', type=Path, default=DB_PATH)
        if name == 'backup':
            command.add_argument('--output', type=Path)
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try:
        if args.command == 'init':
            from . import public_store

            args.db.parent.mkdir(parents=True, exist_ok=True)
            db = public_store.connect(args.db)
            try:
                version = migrate(db)
            finally:
                db.close()
            result = {'database': str(args.db), 'status': 'initialized', 'schemaVersion': version}
            exit_code = 0
        elif args.command == 'check':
            result = check_database(args.db)
            exit_code = 0 if result['ok'] else 1
        else:
            destination = backup_database(args.db, args.output)
            result = {'source': str(args.db), 'backup': str(destination), 'status': 'ok'}
            exit_code = 0
        print(json.dumps(result, ensure_ascii=False))
        return exit_code
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
