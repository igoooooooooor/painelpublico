import json
from pathlib import Path
import tempfile
import unittest

from backend import amendments


class AmendmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'amendments.json'
        self.db = self.root / 'missing.sqlite3'

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding='utf-8')

    def test_unavailable_and_no_records_never_become_zero(self):
        missing = amendments.detail('3550308', self.db, self.path)
        self.assertEqual(missing['status'], 'unavailable')
        self.assertIsNone(missing['totals']['paidCents'])
        self.write({'source': {'status': 'unavailable'}, 'municipalities': {
            '3550308': {'status': 'unavailable', 'recordCount': 0}}})
        self.assertEqual(amendments.detail('3550308', self.db, self.path)['status'], 'unavailable')
        self.write({'year': 2026, 'municipalities': {}})
        empty = amendments.detail('3550308', self.db, self.path)
        self.assertEqual(empty['status'], 'no_records')
        self.assertIsNone(empty['totals']['committedCents'])
        self.assertIn('não significa', empty['message'])

    def test_links_use_national_uniqueness_not_destination_state(self):
        roster = [{'id': 'camara:1', 'name': 'Ana Silva', 'uf': 'SP'},
                  {'id': 'senado:2', 'name': 'Pedro Souza', 'uf': 'MG'}]
        data = {'municipalities': {'3304557': {'authors': [{'id': '1001', 'name': 'ANA SILVA'}]},
                                   '3550308': {'authors': [{'id': '1001', 'name': 'Ana Silva'}]}}}
        self.assertEqual(amendments.author_links(data, roster), {'1001': 'camara:1'})
        data['municipalities']['3550308']['authors'].append({'id': '1002', 'name': 'Ana Silva'})
        self.assertEqual(amendments.author_links(data, roster), {})

    def test_conflicting_names_profiles_and_collective_authors_stay_unlinked(self):
        data = {'municipalities': {'1': {'authors': [{'id': '1', 'name': 'Ana'}, {'id': '2', 'name': 'Bancada SP'}]},
                                   '2': {'authors': [{'id': '1', 'name': 'Bia'}]}}}
        roster = [{'id': 'camara:1', 'name': 'Ana'}, {'id': 'camara:2', 'name': 'Bancada SP'}]
        self.assertEqual(amendments.author_links(data, roster), {})
        data['municipalities'].pop('2')
        roster.append({'id': 'senado:3', 'name': 'Ana'})
        self.assertEqual(amendments.author_links(data, roster), {})

    def test_national_catalog_blocks_conflicts_outside_identified_destinations(self):
        roster = [{'id': 'camara:1', 'name': 'Ana Silva'}]
        data = {'authors': [{'id': '1', 'nameVariants': ['Ana Silva', 'Outra Pessoa'],
                             'types': ['Emenda Individual - Transferências Especiais']}],
                'municipalities': {'1': {'authors': [{'id': '1', 'name': 'Ana Silva'}]}}}
        self.assertEqual(amendments.author_links(data, roster), {})
        data['authors'][0]['nameVariants'] = ['ANA SILVA', 'Ana Silva']
        self.assertEqual(amendments.author_links(data, roster), {'1': 'camara:1'})
        data['authors'][0]['types'] = ['Emenda de Bancada']
        self.assertEqual(amendments.author_links(data, roster), {})

    def test_values_source_and_stale_status_survive_without_database(self):
        self.write({'year': 2026, 'source': {'status': 'stale', 'fetchedAt': '2026-10-01'},
                    'municipalities': {'3550308': {'recordCount': 2, 'status': 'available',
                        'authors': [{'id': '1', 'name': 'Nome original', 'profileId': 'camara:1'}],
                        'totals': {'committedCents': 12345, 'paidCents': 0, 'restosPaidCents': None}}}})
        result = amendments.detail('3550308', self.db, self.path)
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['totals']['paidCents'], 0)
        self.assertIsNone(result['totals']['restosPaidCents'])
        self.assertEqual(result['source']['fetchedAt'], '2026-10-01')
        self.assertNotIn('profileId', result['authors'][0])
        self.assertEqual(result['authors'][0]['name'], 'Nome original')
