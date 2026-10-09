import csv
import gzip
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import citizen, public_store as store
from backend.config import SCHEMA_VERSION
from backend.database import backup_database, check_database, ensure_schema, migrate


class PublicStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'test.sqlite3'
        self.payload = {
            'sources': [{'id': 'test', 'label': 'Fonte oficial de teste', 'status': 'imported', 'url': 'https://example.gov.br', 'period': '2026', 'scope': 'fixture',
                         'fetchedAt': '2026-09-01T12:00:00+00:00'}],
            'authorities': [{'id': f'p:{i}', 'name': f'José {i}', 'role': 'deputado', 'sphere': 'federal', 'branch': 'legislativo',
                             'institution': 'Câmara', 'uf': 'SP', 'sourceId': 'test'} for i in range(7)],
            'expenses': []}
        for i in range(7):
            for month in range(1, 6):
                self.payload['expenses'].append({'id': f'e:{i}:{month}', 'authorityId': f'p:{i}', 'sourceId': 'test',
                    'year': 2026, 'month': month, 'date': f'2026-{month:02d}-15', 'category': 'Escritório', 'kind': 'reembolso',
                    'amount': 40000 if i == 0 and month == 4 else 10000 + i,
                    'documentId': 'SAME-DOCUMENT', 'supplier': {'key': 'x', 'name': 'Empresa', 'cnpj': '12345678000199'}})
        self.import_data()

    def tearDown(self):
        self.temp.cleanup()

    def import_data(self):
        path = self.root / 'input.json'
        path.write_text(json.dumps(self.payload))
        store.import_documents([path], self.db_path)

    def test_search_text_is_accent_insensitive_and_literal(self):
        with closing(store.connect(self.db_path)) as db, db:
            count = lambda q: db.execute("SELECT COUNT(*) FROM authorities WHERE searchText LIKE ? ESCAPE '\\'",
                                         (store.query_text({'q': q}),)).fetchone()[0]
            self.assertEqual(count('jose'), 7)
            self.assertEqual(count('JOSÉ 3'), 1)
            self.assertEqual(count("%' OR 1=1 --"), 0)
            self.assertEqual(count('_'), 0)

    def test_exact_money_and_signed_refunds_no_document_deduplication(self):
        self.payload['expenses'].append({**self.payload['expenses'][0], 'id': 'refund', 'amount': -0.01})
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            count, cents = db.execute("SELECT COUNT(*),SUM(amountCents) FROM expenses WHERE authorityId='p:0'").fetchone()
            self.assertEqual((count, cents), (6, 7999999))
            supplier = db.execute("SELECT authorityCount FROM supplier_totals WHERE supplierKey='cnpj:12345678000199'").fetchone()[0]
            self.assertEqual(supplier, 7)

    def test_idempotence_and_failed_transaction_preserve_previous_data(self):
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            stamp = db.execute('SELECT firstSeen FROM expenses LIMIT 1').fetchone()[0]
            self.assertEqual(db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0], 35)
        self.payload['expenses'][0]['supplier']['cnpj'] = '12345678900'
        with self.assertRaises(ValueError):
            self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0], 35)
            self.assertEqual(db.execute('SELECT firstSeen FROM expenses LIMIT 1').fetchone()[0], stamp)

    def test_changes_since_tracks_document_period_and_public_metadata(self):
        def changed_since(db, stamp):
            return {row[0] for row in db.execute('SELECT id FROM expenses WHERE lastChanged>?', (stamp,))}
        with closing(store.connect(self.db_path)) as db, db:
            initial = db.execute('SELECT MAX(lastChanged) FROM expenses').fetchone()[0]
        self.payload['expenses'][0]['documentUrl'] = 'https://example.gov.br/corrected'
        self.payload['expenses'][1]['month'] = 7
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(changed_since(db, initial), {'e:0:1', 'e:0:2'})
            initial = db.execute('SELECT MAX(lastChanged) FROM expenses').fetchone()[0]
        for e in self.payload['expenses']:
            e['supplier']['name'] = 'Empresa corrigida'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(len(changed_since(db, initial)), 35)

    def test_ambiguous_personal_document_reference_is_omitted(self):
        self.payload['expenses'][0]['documentId'] = '000.000.000-00'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT documentId FROM expenses WHERE id='e:0:1'").fetchone()[0], '')

    def test_peak_signal_uses_closed_months_only(self):
        # A referência é a mediana dos 12 meses anteriores: 2025 completo para todos.
        for i in range(7):
            for month in range(1, 13):
                self.payload['expenses'].append({**self.payload['expenses'][0], 'id': f'h:{i}:{month}', 'authorityId': f'p:{i}',
                                                 'year': 2025, 'month': month, 'date': f'2025-{month:02d}-15', 'amount': 10000 + i})
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            peaks = [row[0] for row in db.execute("SELECT period FROM signals WHERE authorityId='p:0' AND type='pico'")]
            self.assertEqual(peaks, ['2026-04'])
        # Coleta antes de 90 dias depois de abril: o mês ainda não pode ser avaliado.
        self.payload['sources'][0]['fetchedAt'] = '2026-07-15T12:00:00+00:00'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM signals WHERE type='pico'").fetchone()[0], 0)
            coverage = json.loads(db.execute("SELECT detail FROM alert_coverage WHERE authorityId='p:0' AND rule='pico' AND year=2026").fetchone()[0])
            self.assertEqual(coverage['notEvaluated']['prazo_aberto'], [4, 5])
            self.assertEqual(coverage['evaluated'], [1, 2, 3])

    def test_failed_collection_does_not_move_the_eligibility_date(self):
        self.payload['sources'][0]['fetchedAt'] = '2026-07-15T12:00:00+00:00'  # abril ainda aberto
        self.import_data()
        self.payload['sources'][0].update(status='unavailable', fetchedAt='2026-10-06T12:00:00+00:00')
        self.import_data()  # mesmas notas; só a tentativa é mais recente
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM signals WHERE type='pico'").fetchone()[0], 0)
            row = db.execute("SELECT status,fetchedAt,dataFetchedAt FROM sources WHERE id='test'").fetchone()
            self.assertEqual(tuple(row), ('unavailable', '2026-10-06T12:00:00+00:00', '2026-07-15T12:00:00+00:00'))

    def test_salary_not_added_to_reimbursements_and_missing_not_zero(self):
        salary = {**self.payload['expenses'][0], 'id': 'pay', 'kind': 'remuneracao', 'amount': 0, 'supplier': None}
        self.payload['expenses'].append(salary)
        self.payload['authorities'].append({**self.payload['authorities'][0], 'id': 'no-pay', 'name': 'Sem remuneração importada'})
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            kinds = dict(db.execute("SELECT kind,amountCents FROM authority_totals WHERE authorityId='p:0'").fetchall())
            self.assertEqual(kinds, {'reembolso': 8000000, 'remuneracao': 0})
            self.assertEqual(db.execute("SELECT COUNT(*) FROM authority_totals WHERE authorityId='no-pay'").fetchone()[0], 0)

    def test_profile_csv_exports_every_note_and_escapes_formulas(self):
        self.payload['authorities'][0]['name'] = '  =HYPERLINK("x")'
        self.payload['expenses'].append({**self.payload['expenses'][0], 'id': 'refund', 'amount': -0.01, 'category': '=1+1'})
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            filename, chunks = citizen.expenses_csv(db, 'p:0')
            data = list(csv.reader(io.StringIO(''.join(chunks).lstrip('﻿')), delimiter=';'))
            self.assertEqual(filename, 'gastos-cota-hyperlink-x.csv')
            self.assertEqual(data[0][:5], ['Parlamentar', 'Competência', 'Data de emissão', 'Categoria', 'Valor (R$)'])
            self.assertEqual(len(data), 7)
            self.assertTrue(data[1][0].startswith("'  ="))
            self.assertIn('-0,01', [row[4] for row in data[1:]])
            self.assertIn("'=1+1", [row[3] for row in data[1:]])
            self.assertIsNone(citizen.expenses_csv(db, 'inexistente'))

    def test_streaming_gzip_import(self):
        path = self.root / 'stream.jsonl.gz'
        with gzip.open(path, 'wt', encoding='utf-8') as output:
            for kind, key in [('source', 'sources'), ('authority', 'authorities'), ('expense', 'expenses')]:
                for item in self.payload[key]:
                    output.write(json.dumps({'type': kind, 'data': item}) + '\n')
        store.import_documents([path], self.db_path)
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0], 35)

    def test_complete_roster_replaces_membership_and_keeps_history(self):
        self.payload['sources'].append({'id': 'camara_deputies_current', 'label': 'Lista atual', 'status': 'imported'})
        for authority in self.payload['authorities'][:3]:
            authority['sourceId'] = 'camara_deputies_current'
        self.import_data()

        def roster(db):
            return {row[0] for row in db.execute("SELECT authorityId FROM roster WHERE sourceId='camara_deputies_current'")}
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(roster(db), {'p:0', 'p:1', 'p:2'})

        # p:0 sai da lista nova e continua só no arquivo de despesas: deixa de ser atual, sem perder nada.
        self.payload['authorities'][0]['sourceId'] = 'test'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(roster(db), {'p:1', 'p:2'})
            self.assertEqual(db.execute("SELECT sourceId FROM authorities WHERE id='p:0'").fetchone()[0], 'test')
            self.assertEqual(db.execute("SELECT COUNT(*) FROM expenses WHERE authorityId='p:0'").fetchone()[0], 5)

        # Uma coleta indisponível não esvazia nem altera a lista anterior.
        self.payload['sources'][-1]['status'] = 'unavailable'
        self.payload['authorities'][1]['sourceId'] = 'test'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(roster(db), {'p:1', 'p:2'})

        # Quem volta à lista volta a ser atual.
        self.payload['sources'][-1]['status'] = 'imported'
        for authority in self.payload['authorities'][:3]:
            authority['sourceId'] = 'camara_deputies_current'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(roster(db), {'p:0', 'p:1', 'p:2'})

    def test_version_one_database_gains_roster_from_current_lists(self):
        self.payload['sources'].append({'id': 'senado_senators_current', 'label': 'Lista atual', 'status': 'imported'})
        self.payload['authorities'][0]['sourceId'] = 'senado_senators_current'
        self.import_data()
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('DROP TABLE roster')
            db.execute('PRAGMA user_version = 1')
            db.commit()
        self.assertEqual(ensure_schema(self.db_path), SCHEMA_VERSION)
        self.assertEqual(ensure_schema(self.db_path), SCHEMA_VERSION)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute('SELECT sourceId,authorityId FROM roster').fetchall(), [('senado_senators_current', 'p:0')])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
        self.assertIsNone(ensure_schema(self.root / 'absent.sqlite3'))
        self.assertFalse((self.root / 'absent.sqlite3').exists())

    def test_version_two_moves_housing_complement_out_of_the_quota(self):
        self.payload['sources'].append({'id': 'camara_ceap', 'label': 'CEAP', 'status': 'imported', 'url': 'https://www.camara.leg.br/cotas/Ano-2026.csv.zip'})
        self.payload['expenses'].append({'id': 'complement', 'authorityId': 'p:0', 'sourceId': 'camara_ceap', 'year': 2026, 'month': 3,
            'date': '2026-03-10', 'category': 'COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA', 'kind': 'reembolso', 'amount': -1747})
        self.import_data()
        with closing(sqlite3.connect(self.db_path)) as db:
            before = db.execute("SELECT amountCents FROM authority_totals WHERE authorityId='p:0' AND kind='reembolso'").fetchone()[0]
            db.execute('PRAGMA user_version = 2')
            db.commit()
        self.assertEqual(ensure_schema(self.db_path), SCHEMA_VERSION)
        with closing(store.connect(self.db_path)) as db, db:
            kind, cents = db.execute("SELECT kind,amountCents FROM expenses WHERE id='complement'").fetchone()
            self.assertEqual((kind, cents), ('complemento_moradia', -174700))
            after = db.execute("SELECT amountCents FROM authority_totals WHERE authorityId='p:0' AND kind='reembolso'").fetchone()[0]
            self.assertEqual(after - before, 174700)
            profile = citizen.politician(db, 'p:0')
            self.assertEqual(profile['total'] * 100, after)
            self.assertEqual(profile['complementoMoradia'], {'valor': -1747.0, 'notas': 1, 'meses': ['2026-03']})
            self.assertNotIn('COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA', [c['nome'] for c in profile['categorias']])
            self.assertIsNone(citizen.politician(db, 'p:1')['complementoMoradia'])

    def test_importer_kind_for_housing_complement_is_accepted(self):
        self.payload['expenses'][0]['kind'] = 'complemento_moradia'
        self.import_data()
        with closing(store.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT kind FROM expenses WHERE id='e:0:1'").fetchone()[0], 'complemento_moradia')

    def test_legacy_schema_migrates_once_and_preserves_data(self):
        db = sqlite3.connect(self.root / 'legacy.sqlite3')
        db.execute('''CREATE TABLE authorities (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT, branch TEXT, sphere TEXT,
            institution TEXT, uf TEXT, party TEXT, sourceId TEXT, sourceUrl TEXT)''')
        db.execute('''INSERT INTO authorities
            (id,name,institution) VALUES (?,?,?)''', ('old:1', 'José da Silva', 'Câmara'))
        db.commit()
        self.assertEqual(migrate(db), SCHEMA_VERSION)
        self.assertEqual(migrate(db), SCHEMA_VERSION)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
        row = db.execute('SELECT id,name,searchText,positionCount FROM authorities').fetchone()
        self.assertEqual(row, ('old:1', 'José da Silva', 'jose da silva camara', 1))
        db.close()

    def test_failed_migration_rolls_back_schema_and_version(self):
        db = sqlite3.connect(self.root / 'rollback.sqlite3')
        db.execute('CREATE TABLE authorities (legacy_id TEXT)')
        db.commit()
        with self.assertRaises(sqlite3.OperationalError):
            migrate(db)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {row[1] for row in db.execute('PRAGMA table_info(authorities)')}
        self.assertEqual(tables, {'authorities'})
        self.assertEqual(columns, {'legacy_id'})
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
        db.close()

    def test_check_missing_database_is_read_only(self):
        missing = self.root / 'absent.sqlite3'
        result = check_database(missing)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'missing')
        self.assertFalse(missing.exists())

    def test_importer_reports_missing_or_empty_import_directory_without_creating_db(self):
        for import_dir, expected in (
            (self.root / 'missing-imports', 'Pasta de importação não encontrada'),
            (self.root / 'empty-imports', 'Nenhum arquivo JSON ou JSONL para importar'),
        ):
            with self.subTest(import_dir=import_dir):
                if import_dir.name == 'empty-imports':
                    import_dir.mkdir()
                database_path = self.root / f'{import_dir.name}.sqlite3'
                error_output = io.StringIO()
                with redirect_stderr(error_output):
                    with self.assertRaises(SystemExit) as error:
                        store.main(['--db', str(database_path)], import_dir=import_dir)
                self.assertEqual(error.exception.code, 2)
                self.assertIn(expected, error_output.getvalue())
                self.assertFalse(database_path.exists())

    def test_online_backup_copies_database_and_never_overwrites(self):
        output = self.root / 'backup.sqlite3'
        self.assertEqual(backup_database(self.db_path, output), output)
        backup = sqlite3.connect(output)
        try:
            self.assertEqual(backup.execute('SELECT COUNT(*) FROM expenses').fetchone()[0], 35)
        finally:
            backup.close()

        protected = self.root / 'protected.sqlite3'
        protected.write_bytes(b'keep me')
        with self.assertRaises(FileExistsError):
            backup_database(self.db_path, protected)
        self.assertEqual(protected.read_bytes(), b'keep me')


if __name__ == '__main__':
    unittest.main()
