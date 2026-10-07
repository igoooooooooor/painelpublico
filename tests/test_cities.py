import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import cities, public_store


class CityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(cities, 'SNAPSHOTS_PATH', self.root)
        self.patch.start()
        self.db = self.root / 'missing.sqlite3'
        self.data = {'municipalities': [
            {'id': '3550308', 'name': 'São Paulo', 'uf': 'SP', 'population': None},
            {'id': '5300108', 'name': 'Brasília', 'uf': 'DF'},
            {'id': '2605459', 'name': 'Fernando de Noronha', 'uf': 'PE'}],
            'stateElected': {'SP': [self.candidate('1')]}}
        self.write()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def candidate(self, identifier, name='Ana Silva'):
        return {'id': identifier, 'name': name, 'ballotName': name, 'office': 'DEPUTADO FEDERAL', 'uf': 'SP', 'year': 2026}

    def write(self):
        (self.root / 'cities.json').write_text(json.dumps(self.data), encoding='utf-8')

    def test_search_is_accent_case_insensitive_and_allows_state(self):
        result = cities.search('sAO paULO sp')
        self.assertEqual([row['id'] for row in result['items']], ['3550308'])
        self.assertIsNone(result['items'][0]['population'])
        self.assertEqual(cities.search('cidade inexistente')['items'], [])
        self.assertEqual(len(cities.search('', limit=2)['items']), 2)

    def test_missing_snapshot_is_explicit_and_reload_works(self):
        (self.root / 'cities.json').unlink()
        self.assertFalse(cities.search()['available'])
        self.assertIsNone(cities.detail('3550308', self.db))
        self.write()
        self.assertTrue(cities.search()['available'])
        (self.root / 'cities.json').write_text('{bad')
        self.assertFalse(cities.search()['available'])

    def test_city_survives_missing_database_and_election_data(self):
        detail = cities.detail('3550308', self.db)
        self.assertEqual(detail['municipalElected'], [])
        self.assertIn('Ausência', detail['messages']['municipalElection'])
        self.assertTrue(detail['messages']['currentFederal'])
        self.assertEqual(detail['topFederalVotes'], [])
        self.assertIsNone(detail['municipality']['population'])
        self.assertIsNone(cities.detail('../../etc/passwd', self.db))
        self.assertIsNone(cities.detail('9999999', self.db))

    def test_special_territories_explain_local_government(self):
        self.assertIn('não elege prefeito', cities.detail('5300108', self.db)['messages']['municipalElection'])
        self.assertIn('distrito estadual', cities.detail('2605459', self.db)['messages']['municipalElection'])

    def test_link_requires_unique_both_directions_uf_and_office(self):
        roster = [{'id': 'camara:1', 'name': 'ANA SILVA', 'uf': 'SP', 'role': 'deputado'}]
        self.assertEqual(cities._links([self.candidate('1')], roster), {'1': 'camara:1'})
        self.assertEqual(cities._links([self.candidate('1'), self.candidate('2')], roster), {})
        self.assertEqual(cities._links([self.candidate('1')], roster + [{**roster[0], 'id': 'camara:2'}]), {})
        self.assertEqual(cities._links([{**self.candidate('1'), 'uf': 'RJ'}], roster), {})
        self.assertEqual(cities._links([{**self.candidate('1'), 'office': 'SENADOR'}], roster), {})

    def test_only_current_roster_links_and_sources_are_preserved(self):
        doc = self.root / 'input.json'
        doc.write_text(json.dumps({'sources': [{'id': 'camara_deputies_current', 'label': 'Câmara', 'status': 'imported',
                                               'url': 'https://example.org', 'period': '2026', 'fetchedAt': '2026-10-07'}],
                                  'authorities': [{'id': 'camara:1', 'name': 'Ana Silva', 'role': 'deputado', 'uf': 'SP',
                                                   'sourceId': 'camara_deputies_current'}], 'expenses': []}))
        public_store.import_documents([doc], self.db)
        result = cities.detail('3550308', self.db)
        self.assertEqual(result['stateElected'][0]['profileId'], 'camara:1')
        self.assertEqual(result['currentFederal'][0]['sourcePeriod'], '2026')
        self.assertEqual(result['currentFederal'][0]['fetchedAt'], '2026-10-07')
        with public_store.connect(self.db) as db:
            db.execute("UPDATE sources SET status='unavailable'")
        stale = cities.detail('3550308', self.db)
        self.assertEqual(stale['sources']['currentFederal']['camara']['status'], 'unavailable')
        self.assertIn('lista anterior', stale['sources']['currentFederal']['camara']['note'])
        self.assertEqual(len(stale['currentFederal']), 1)
        with public_store.connect(self.db) as db:
            db.execute('DELETE FROM roster')
        self.assertNotIn('profileId', cities.detail('3550308', self.db)['stateElected'][0])
