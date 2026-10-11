import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from ingest import chamber_projects, project_status


def encoded(value):
    return json.dumps(value).encode()


def proposition(identifier, kind='PL', number=1, year=2026, presented='2026-03-01', ementa='Ementa pública'):
    return {'id': identifier, 'siglaTipo': kind, 'numero': number, 'ano': year, 'ementa': ementa,
            'dataApresentacao': presented + 'T10:00', 'ultimoStatus': {'data': presented, 'descricaoSituacao': 'Pronta para pauta'}}


def signature(proposition_id, deputy, proponent=1):
    return {'idProposicao': proposition_id, 'idDeputadoAutor': deputy, 'codTipoAutor': 10000, 'tipoAutor': 'Deputado(a)',
            'nomeAutor': f'Deputado {deputy}', 'ordemAssinatura': 1 if proponent else 2, 'proponente': proponent}


class ChamberProjectsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.today = date(2026, 10, 11)
        self.calls = []
        self.archives = {
            2023: ([proposition(1, number=10, year=2023, presented='2023-01-20'),   # antes do mandato: fora
                    proposition(2, number=11, year=2023, presented='2023-02-01'),
                    proposition(3, kind='REQ', number=12, year=2023, presented='2023-05-01')],  # tipo fora do recorte
                   [signature(1, 100), signature(2, 100), signature(2, 200, proponent=0), signature(3, 100),
                    {'idProposicao': 2, 'idDeputadoAutor': None, 'tipoAutor': 'Comissão'}]),
            2024: ([proposition(4, kind='PEC', number=5, year=2024, presented='2024-04-10')], [signature(4, 200)]),
            2025: ([], []),
            2026: ([proposition(5, kind='PLP', number=7, year=2026, presented='2026-02-02'),
                    proposition(6, number=8, year=2026, presented='2026-09-30')],
                   [signature(5, 100), signature(6, 100), signature(6, 100, proponent=0)]),  # assinatura repetida
        }

    def tearDown(self):
        self.temp.cleanup()

    def request(self, url):
        self.calls.append(url)
        year = int(url.rsplit('-', 1)[1].split('.')[0])
        propositions, signatures = self.archives[year]
        return encoded({'dados': signatures if 'Autores' in url else propositions})

    def load(self, **kwargs):
        return chamber_projects.load_archives(self.root, request=self.request, today=self.today, **kwargs)

    def test_period_type_filter_coauthorship_and_dedup(self):
        archive = self.load(collect=True)
        self.assertTrue(archive['complete'])
        self.assertEqual(set(archive['projects']), {'2', '4', '5', '6'})
        self.assertEqual(archive['signatures'], {'100': {'2': True, '5': True, '6': True}, '200': {'2': False, '4': True}})
        self.assertEqual(len(self.calls), 8)

        section = chamber_projects.projects_section('100', archive)
        self.assertEqual((section['status'], section['total'], section['method']), ('imported', 3, 'arquivos-anuais'))
        self.assertEqual([item['id'] for item in section['items']], ['6', '5', '2'])
        self.assertEqual(section['items'][2], {
            'id': '2', 'titulo': 'PL 11/2023', 'ementa': 'Ementa pública', 'situacao': None,
            'url': 'https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=2',
            'apresentadaEm': '2023-02-01', 'proponente': True})
        coauthor = chamber_projects.projects_section('200', archive)
        self.assertEqual([(item['id'], item['proponente']) for item in coauthor['items']], [('4', True), ('2', False)])
        nobody = chamber_projects.projects_section('300', archive)
        self.assertEqual((nobody['status'], nobody['total'], nobody['items']), ('imported', 0, []))
        summary = chamber_projects.summary(archive)
        self.assertEqual((summary['projetosDistintos'], summary['associacoes'], summary['deputadosComAssinatura']), (4, 5, 2))

    def test_offline_reads_cache_and_only_current_year_expires(self):
        self.load(collect=True)
        self.calls.clear()
        offline = self.load()
        self.assertTrue(offline['complete'])
        self.assertEqual(self.calls, [])
        # Vence só o ano corrente: os anos fechados continuam no cache.
        raw = self.root / 'data' / 'raw' / 'projetos-situacao' / 'camara'
        for name in ('proposicoes-2026', 'proposicoesAutores-2026', 'proposicoes-2024'):
            meta_path = raw / f'{name}.meta.json'
            meta = json.loads(meta_path.read_text())
            meta['consultadoEm'] = (datetime.now(timezone.utc) - timedelta(hours=30)).replace(microsecond=0).isoformat()
            meta_path.write_text(json.dumps(meta))
        self.archives[2026][0].append(proposition(7, number=9, year=2026, presented='2026-10-10'))
        self.archives[2026][1].append(signature(7, 200))
        refreshed = self.load(collect=True, max_age_hours=20)
        self.assertEqual(sorted(self.calls), sorted([chamber_projects.PROPOSITIONS_URL.format(year=2026),
                                                     chamber_projects.AUTHORS_URL.format(year=2026)]))
        self.assertIn('7', refreshed['signatures']['200'])

    def test_missing_year_makes_sections_partial_without_total(self):
        def failing(url):
            if '2024' in url:
                raise OSError('indisponível')
            return self.request(url)
        archive = chamber_projects.load_archives(self.root, collect=True, request=failing, today=self.today)
        self.assertFalse(archive['complete'])
        section = chamber_projects.projects_section('200', archive)
        self.assertEqual((section['status'], section['total']), ('partial', None))
        self.assertIn('2024', section['detail'])
        self.assertEqual([item['id'] for item in section['items']], ['2'])
        empty = chamber_projects.projects_section('300', archive)
        self.assertEqual((empty['status'], empty['total']), ('unavailable', None))

    def test_conditional_get_keeps_cache_on_304_and_records_last_modified(self):
        seen = []
        def fetch(url, headers):
            seen.append((url, headers))
            if headers.get('If-None-Match') == '"v1"':
                return project_status.ArchiveResponse(304, None, None, None)
            return project_status.ArchiveResponse(200, self.request(url), 'Sat, 10 Oct 2026 03:00:00 GMT', '"v1"')
        first = self.load(collect=True, fetch=fetch)
        self.assertEqual(first['years']['2026']['proposicoes']['lastModified'], 'Sat, 10 Oct 2026 03:00:00 GMT')
        self.assertTrue(all(headers == {} for _, headers in seen))
        seen.clear()
        second = self.load(collect=True, refresh=True, fetch=fetch)
        self.assertTrue(all(headers == {'If-None-Match': '"v1"', 'If-Modified-Since': 'Sat, 10 Oct 2026 03:00:00 GMT'}
                            for _, headers in seen))
        self.assertEqual(second['projects'], first['projects'])
        meta = json.loads((self.root / 'data' / 'raw' / 'projetos-situacao' / 'camara' / 'proposicoes-2026.meta.json').read_text())
        self.assertTrue(meta['notModified'])
        self.assertIsNotNone(second['fetchedAt'])

    def test_rows_outside_contract_are_ignored(self):
        self.assertIsNone(chamber_projects.project_row({'id': 'x', 'siglaTipo': 'PL', 'dataApresentacao': '2026-01-01'}))
        self.assertIsNone(chamber_projects.project_row({'id': 9, 'siglaTipo': 'PL', 'dataApresentacao': 'ontem'}))
        self.assertIsNone(chamber_projects.author_row({'idProposicao': 9, 'idDeputadoAutor': True}))
        self.assertEqual(chamber_projects.author_row({'idProposicao': '9', 'idDeputadoAutor': '77', 'proponente': '0'}),
                         ('9', '77', False))
        self.assertEqual(chamber_projects.archive_years(date(2024, 5, 1)), [2023, 2024])


if __name__ == '__main__':
    unittest.main()
