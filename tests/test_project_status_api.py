import json
import os
from pathlib import Path
import tempfile
import unittest

from backend import profiles


class ProjectStatusProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / 'perfis.json'
        self.statuses = self.root / 'projetos-situacao.json'
        self.write(self.base, {'profiles': {
            'camara:1': {'name': 'Pessoa A', 'projetos': {'status': 'imported', 'total': 2,
                'items': [{'id': '10', 'titulo': 'PL 1/2026', 'situacao': None}, {'id': '11'}]}},
            'camara:2': {'name': 'Coautoria', 'projetos': {'total': 1, 'items': [{'id': '10'}]}},
            'senado:1': {'name': 'Pessoa B', 'contato': {'email': 'exemplo@senado.leg.br'}},
        }})
        self.write(self.root / 'senado-projetos.json', {'profiles': {
            'senado:1': {'projetos': {'total': 1, 'items': [{'id': '10', 'titulo': 'PEC 1/2026'}]}},
            'senado:2': {'projetos': {'total': 1, 'items': [{'id': '10'}]}},
        }})

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, content):
        old = path.stat().st_mtime_ns if path.exists() else None
        path.write_text(json.dumps(content), encoding='utf-8')
        if old is not None:
            os.utime(path, ns=(old + 1_000_000, old + 1_000_000))

    def test_current_status_is_joined_by_house_and_project_without_changing_authorship(self):
        chamber = {'grupo': 'lei', 'descricao': 'Transformado em norma jurídica',
                   'consultadoEm': '2026-10-07T18:00:00Z', 'status': 'imported',
                   'normas': [{'tipo': 'Lei', 'numero': '10', 'ano': 2026}]}
        senate = {'grupo': 'tramitando', 'descricao': 'Em tramitação',
                  'consultadoEm': '2026-10-07T18:05:00Z', 'status': 'imported'}
        self.write(self.statuses, {'projects': {'camara:10': chamber, 'senado:10': senate,
                                              'camara:999': {'grupo': 'arquivado'}}})
        first = profiles.profile('camara:1', self.base)
        self.assertEqual(first['projetos']['total'], 2)
        self.assertEqual(first['projetos']['items'][0]['situacaoAtual'], chamber)
        self.assertIsNone(first['projetos']['items'][0]['situacao'])
        self.assertNotIn('situacaoAtual', first['projetos']['items'][1])
        first['projetos']['items'][0]['situacaoAtual']['grupo'] = 'arquivado'
        first['projetos']['items'][0]['situacaoAtual']['normas'][0]['numero'] = 'alterado'
        self.assertEqual(profiles.profile('camara:1', self.base)['projetos']['items'][0]['situacaoAtual'], chamber)
        self.assertEqual(profiles._load(self.statuses)['projects']['camara:10'], chamber)
        self.assertEqual(profiles.profile('camara:2', self.base)['projetos']['items'][0]['situacaoAtual'], chamber)
        for person in ('senado:1', 'senado:2'):
            self.assertEqual(profiles.profile(person, self.base)['projetos']['items'][0]['situacaoAtual'], senate)
        self.assertEqual(profiles.profile('senado:1', self.base)['contato']['email'], 'exemplo@senado.leg.br')
        self.assertNotIn('camara:999', json.dumps(first))
        self.assertNotIn('situacaoAtual', json.dumps(profiles._load(self.base)))

    def test_status_update_or_removal_does_not_leave_an_old_join_in_the_base_cache(self):
        self.write(self.statuses, {'projects': {'camara:10': {'grupo': 'tramitando'}}})
        self.assertEqual(profiles.profile('camara:1', self.base)['projetos']['items'][0]['situacaoAtual']['grupo'], 'tramitando')
        self.write(self.statuses, {'projects': {'camara:10': {'grupo': 'arquivado'}}})
        self.assertEqual(profiles.profile('camara:1', self.base)['projetos']['items'][0]['situacaoAtual']['grupo'], 'arquivado')
        self.statuses.unlink()
        self.assertNotIn('situacaoAtual', profiles.profile('camara:1', self.base)['projetos']['items'][0])

    def test_missing_or_malformed_status_keeps_projects_and_absence(self):
        for value in ({'projects': []}, {'projects': {'camara:10': None}}, {'projects': {}}):
            self.write(self.statuses, value)
            profile = profiles.profile('camara:1', self.base)
            self.assertEqual(profile['projetos']['total'], 2)
            self.assertNotIn('situacaoAtual', profile['projetos']['items'][0])
        self.statuses.write_text('{invalid', encoding='utf-8')
        self.assertEqual(profiles.profile('senado:2', self.base)['projetos']['total'], 1)


if __name__ == '__main__':
    unittest.main()
