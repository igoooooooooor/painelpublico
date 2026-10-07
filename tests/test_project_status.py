import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from ingest import project_status


def encoded(value):
    return json.dumps(value).encode()


class ProjectStatusCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshots = self.root / 'data' / 'snapshots'
        self.snapshots.mkdir(parents=True)
        self.write('perfis.json', {'profiles': {
            'camara:1': {'projetos': {'items': [{'id': '10', 'titulo': 'PL 1/2026'}, {'id': '11', 'titulo': 'PL 2/2026'}]}},
            'camara:2': {'projetos': {'items': [{'id': '10', 'titulo': 'PL 1/2026'}]}},
        }})
        self.write('senado-projetos.json', {'profiles': {
            'senado:1': {'projetos': {'items': [{'id': '10', 'titulo': 'PEC 1/2026'}]}},
        }})

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, value):
        (self.snapshots / name).write_bytes(encoded(value))

    def request(self, url):
        if '/arquivos/' in url:
            return encoded({'dados': [
                {'id': 10, 'siglaTipo': 'PL', 'ultimoStatus': {'data': '2026-10-01', 'descricaoSituacao': 'Arquivada'}},
                {'id': 11, 'siglaTipo': 'PL', 'ultimoStatus': {'data': '2026-10-01', 'descricaoSituacao': None}},
                {'id': 999, 'siglaTipo': 'PL', 'ultimoStatus': {'descricaoSituacao': 'Arquivada'}},
            ]})
        if '/processo?' in url:
            return encoded([{'id': 10, 'identificacao': 'PEC 1/2026', 'tramitando': 'Sim',
                             'situacaoAtual': 'AGUARDANDO DESPACHO', 'dataSituacaoAtual': '2026-10-01'}])
        raise AssertionError(f'Consulta inesperada: {url}')

    def test_deduplicates_authors_and_keeps_house_identity_and_unknown_status(self):
        calls = []
        def request(url):
            calls.append(url)
            return self.request(url)
        snapshot = project_status.build_snapshot(root=self.root, collect=True, request=request)
        self.assertEqual(set(snapshot['projects']), {'camara:10', 'camara:11', 'senado:10'})
        self.assertEqual(snapshot['projects']['camara:10']['grupo'], 'arquivado')
        self.assertEqual(snapshot['projects']['senado:10']['grupo'], 'tramitando')
        self.assertIsNone(snapshot['projects']['camara:11']['grupo'])
        self.assertIsNotNone(snapshot['projects']['camara:11']['consultadoEm'])
        self.assertEqual(snapshot['summary']['camara']['semConfirmacao'], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(parse_qs(urlsplit(calls[1]).query)['idProcesso'], ['10'])
        offline = project_status.build_snapshot(root=self.root, request=lambda _: self.fail('offline fez rede'))
        self.assertEqual(offline['projects'], snapshot['projects'])

    def test_refresh_failure_preserves_previous_observation_date_and_raw_bytes(self):
        first = project_status.build_snapshot(root=self.root, collect=True, request=self.request)
        raw = self.root / 'data' / 'raw' / 'projetos-situacao' / 'camara' / 'proposicoes-2026.json'
        before = raw.read_bytes()
        def failed(_):
            raise OSError('indisponível')
        second = project_status.build_snapshot(root=self.root, collect=True, refresh=True, request=failed)
        for key in first['projects']:
            self.assertEqual(second['projects'][key]['consultadoEm'], first['projects'][key]['consultadoEm'])
            self.assertEqual(second['projects'][key]['grupo'], first['projects'][key]['grupo'])
            self.assertEqual(second['projects'][key]['status'], 'partial')
        self.assertEqual(raw.read_bytes(), before)

    def test_invalid_response_is_not_cached_and_cannot_erase_snapshot(self):
        first = project_status.build_snapshot(root=self.root, collect=True, request=self.request)
        output = self.snapshots / 'projetos-situacao.json'
        raw_root = self.root / 'data' / 'raw' / 'projetos-situacao'
        for path in raw_root.rglob('*.json'):
            path.unlink()
        second = project_status.build_snapshot(root=self.root, collect=True, refresh=True, request=lambda _: b'{invalid')
        self.assertEqual(set(second['projects']), set(first['projects']))
        self.assertEqual(second['projects']['camara:10']['grupo'], 'arquivado')
        self.assertEqual(second['projects']['camara:10']['status'], 'partial')
        self.assertTrue(output.exists())
        self.assertFalse(list(raw_root.rglob('*.json')))

    def test_offline_without_observations_does_not_write_fake_zero_coverage(self):
        with self.assertRaisesRegex(ValueError, 'Nenhuma situação consultada'):
            project_status.build_snapshot(root=self.root, request=lambda _: self.fail('offline fez rede'))
        self.assertFalse((self.snapshots / 'projetos-situacao.json').exists())

    def test_senate_duplicate_or_omitted_id_stays_unknown(self):
        def request(url):
            if '/processo?' in url:
                row = {'id': 10, 'tramitando': 'Sim', 'situacaoAtual': 'AGUARDANDO DESPACHO'}
                return encoded([row, row])
            return self.request(url)
        snapshot = project_status.build_snapshot(root=self.root, collect=True, request=request)
        record = snapshot['projects']['senado:10']
        self.assertIsNone(record['grupo'])
        self.assertIsNone(record['consultadoEm'])
        self.assertEqual(record['status'], 'unavailable')

    def test_cache_checksum_rejects_partial_file_write(self):
        project_status.build_snapshot(root=self.root, collect=True, request=self.request)
        raw = self.root / 'data' / 'raw' / 'projetos-situacao' / 'camara' / 'proposicoes-2026.json'
        raw.write_bytes(encoded({'dados': []}))
        url = project_status.CAMARA + '/arquivos/proposicoes/json/proposicoes-2026.json'
        payload, meta, error = project_status.cached_json(url, raw)
        self.assertIsNone(payload)
        self.assertIsNone(meta)
        self.assertIsNotNone(error)

    def test_camara_detail_failure_keeps_annual_consultation_and_marks_partial(self):
        self.write('perfis.json', {'profiles': {'camara:1': {'projetos': {'items': [
            {'id': '10', 'titulo': 'PL 1/2026'},
        ]}}}})
        (self.snapshots / 'senado-projetos.json').unlink()

        def request(url):
            if '/arquivos/' in url:
                return encoded({'dados': [{'id': 10, 'siglaTipo': 'PL', 'ultimoStatus': {
                    'data': '2026-10-01', 'descricaoSituacao': 'Em tramitação',
                }}]})
            if '/api/v2/proposicoes/10' in url:
                raise OSError('detalhe indisponível')
            raise AssertionError(f'Consulta inesperada: {url}')

        with patch.object(project_status.project_status_camara, 'needs_detail', return_value=True):
            snapshot = project_status.build_snapshot(root=self.root, collect=True, request=request)

        record = snapshot['projects']['camara:10']
        annual_url = project_status.CAMARA + '/arquivos/proposicoes/json/proposicoes-2026.json'
        self.assertEqual(record['status'], 'partial')
        self.assertEqual(record['consultaUrl'], annual_url)
        self.assertEqual(record['consultadoEm'], snapshot['sources'][0]['consultadoEm'])
        self.assertEqual(record['sourceUrl'], project_status.CAMARA + '/api/v2/proposicoes/10')
        self.assertIn('Falha na consulta (OSError)', record['detail'])
        self.assertIn('A situação e a data do arquivo anual foram preservadas.', record['detail'])


if __name__ == '__main__':
    unittest.main()
