import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from ingest import profiles


def senate_xml():
    root = ET.Element('ListaParlamentarEmExercicio')
    ET.SubElement(ET.SubElement(root, 'Metadados'), 'Versao').text = '07/10/2026'
    people = ET.SubElement(root, 'Parlamentares')
    person = ET.SubElement(people, 'Parlamentar')
    identity = ET.SubElement(person, 'IdentificacaoParlamentar')
    for key, value in (
        ('CodigoParlamentar', '6358'), ('NomeParlamentar', 'Senadora Exemplo'),
        ('UfParlamentar', 'MA'), ('EmailParlamentar', 'exemplo@senado.leg.br'),
        ('UrlFotoParlamentar', 'https://www.senado.leg.br/foto.jpg'),
        ('UrlPaginaParlamentar', 'https://www25.senado.leg.br/web/senadores/senador/-/perfil/6358'),
    ):
        ET.SubElement(identity, key).text = value
    mandate = ET.SubElement(person, 'Mandato')
    ET.SubElement(mandate, 'DescricaoParticipacao').text = '1ª Suplente'
    ET.SubElement(mandate, 'UfParlamentar').text = 'MA'
    exercises = ET.SubElement(mandate, 'Exercicios')
    exercise = ET.SubElement(exercises, 'Exercicio')
    ET.SubElement(exercise, 'DataInicio').text = '2026-08-05'
    ET.SubElement(exercise, 'DataFim').text = '2026-10-06'
    ET.SubElement(exercise, 'DescricaoCausaAfastamento').text = 'Retorno do titular'
    phones = ET.SubElement(person, 'Telefones')
    ET.SubElement(phones, 'NumeroTelefone').text = '(61) 3303-0000'
    return ET.tostring(root, encoding='utf-8')


class ProfileIngestTests(unittest.TestCase):
    def test_only_current_roster_source_ids_are_included(self):
        payload = {'authorities': [
            {'id': 'camara:2', 'name': 'Deputado', 'role': 'deputado', 'sourceId': 'camara_deputies_current'},
            {'id': 'senado:3', 'name': 'Senadora', 'role': 'senador', 'sourceId': 'senado_senators_current'},
            {'id': 'camara:4', 'name': 'Histórico', 'role': 'deputado', 'sourceId': 'camara_ceap'},
            {'id': 'senado:5', 'name': 'Suplente antigo', 'role': 'senador', 'sourceId': 'senado_ceaps'},
            {'id': 'camara:x', 'name': 'ID inválido', 'role': 'deputado', 'sourceId': 'camara_deputies_current'},
        ]}
        self.assertEqual([row['id'] for row in profiles._current_roster(payload)], ['camara:2', 'senado:3'])

    def test_senate_xml_exposes_only_whitelisted_contact_and_last_exercise(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / 'senadores-atual.xml'
            xml_path.write_bytes(senate_xml())
            extracted = profiles._senate_xml_profiles(
                {'senado_senators_current': {'fetchedAt': '2026-10-07T10:00:00+00:00'}}, xml_path
            )['senado:6358']
            self.assertEqual(extracted['mandato']['participacao'], '1ª Suplente')
            self.assertEqual(extracted['mandato']['exercicio'],
                             'Exercício de 05/08/2026 a 06/10/2026 — Retorno do titular')
            self.assertEqual(extracted['contact']['email'], 'exemplo@senado.leg.br')
            self.assertEqual(extracted['contact']['telefones'], ['(61) 3303-0000'])
            self.assertIsNone(extracted['contact']['endereco'])

    def test_chamber_detail_and_cache_drop_personal_fields_and_public_json_uses_contact(self):
        detail = {
            'dados': {
                'nomeCivil': 'Nome Civil de Teste', 'cpf': '00000000000', 'dataNascimento': '1900-01-01',
                'email': 'deputado@camara.leg.br', 'redeSocial': ['https://x.com/exemplo'],
                'ultimoStatus': {'situacao': 'Titular', 'condicaoEleitoral': 'Eleito',
                    'urlFoto': 'https://www.camara.leg.br/foto.jpg',
                    'gabinete': {'telefone': '0000', 'predio': 'IV', 'andar': '3', 'sala': '301'}},
            }
        }
        parsed = profiles.parse_chamber_detail(detail, 'camara:204379', '2026-10-07T10:00:00+00:00')
        with tempfile.TemporaryDirectory() as tmp:
            raw_root = Path(tmp)
            profiles._write_profile_cache('camara:204379', {
                'contact': parsed['contact'], 'mandato': parsed['mandato'], 'photo': parsed['photo'],
                'projetos': profiles._empty_projects('https://dadosabertos.camara.leg.br/api/v2/proposicoes'),
            }, raw_root)
            cache_text = (raw_root / 'camara-204379.json').read_text(encoding='utf-8')
            self.assertNotIn('00000000000', cache_text)
            self.assertNotIn('Nome Civil de Teste', cache_text)
            self.assertNotIn('dataNascimento', cache_text)
            roster = {'id': 'camara:204379', 'name': 'Nome Público', 'role': 'deputado', 'sourceId': 'camara_deputies_current'}
            profile = profiles.build_profile(roster, {}, {}, {}, raw_root=raw_root)
            self.assertIn('contato', profile)
            self.assertNotIn('contact', profile)
            self.assertEqual(profile['contato']['email'], 'deputado@camara.leg.br')
            self.assertEqual(profile['mandato']['participacao'], 'Eleito')

    def test_project_pagination_distinguishes_complete_zero_and_partial(self):
        first = profiles._project_list_url('camara:204379')
        page_two = first + '&pagina=2'
        pages = {
            first: {'dados': [{'id': 7, 'siglaTipo': 'PL', 'numero': '9', 'ano': 2024,
                               'ementa': 'Resumo público', 'uri': 'https://www.camara.leg.br/proposicoes/7'}],
                    'links': [{'rel': 'next', 'href': page_two}]},
            page_two: {'dados': [], 'links': []},
        }
        result = profiles.fetch_chamber_projects('camara:204379', lambda url: pages[url])
        self.assertEqual((result['status'], result['total']), ('imported', 1))
        self.assertIsNone(result['items'][0]['situacao'])

        zero = profiles.fetch_chamber_projects('camara:204379', lambda url: {'dados': [], 'links': []})
        self.assertEqual((zero['status'], zero['total']), ('imported', 0))

        def fail_second(url):
            if url == first:
                return pages[first]
            raise OSError('offline')
        partial = profiles.fetch_chamber_projects('camara:204379', fail_second)
        self.assertEqual(partial['status'], 'partial')
        self.assertIsNone(partial['total'])
        self.assertEqual(len(partial['items']), 1)

    def test_refresh_failure_keeps_successful_cache_and_missing_total_is_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_root = Path(tmp)
            previous = {'id': 'camara:204379', 'contact': {
                'email': 'antigo@camara.leg.br', 'telefones': [], 'endereco': None, 'redes': [],
                'sourceUrl': 'https://dadosabertos.camara.leg.br/api/v2/deputados/204379',
                'fetchedAt': '2026-09-01', 'status': 'imported',
            }, 'projetos': {'status': 'partial', 'period': 'desde 2023-02-01', 'sourceUrl': None,
                'fetchedAt': '2026-09-01', 'total': None, 'items': []}}
            path = raw_root / 'camara-204379.json'
            path.write_text(json.dumps(previous), encoding='utf-8')
            self.assertIsNone(profiles._read_profile_cache('camara:204379', raw_root)['projetos']['total'])
            self.assertEqual(json.loads(path.read_text())['contact']['email'], 'antigo@camara.leg.br')

    def test_refresh_failure_preserves_complete_projects_and_retries_partial_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_root = Path(tmp)
            authority = {'id': 'camara:204379', 'name': 'Deputada Exemplo', 'role': 'deputado',
                         'sourceId': 'camara_deputies_current'}
            contact = {'email': 'exemplo@camara.leg.br', 'telefones': [], 'endereco': None,
                       'redes': [], 'sourceUrl': 'https://dadosabertos.camara.leg.br/api/v2/deputados/204379',
                       'fetchedAt': '2026-09-01', 'status': 'imported'}
            mandate = {'participacao': 'Titular', 'exercicio': 'Titular', 'sourceUrl': contact['sourceUrl'],
                       'fetchedAt': '2026-09-01'}
            complete = {'status': 'imported', 'period': profiles.CHAMBER_PROJECTS_PERIOD,
                        'sourceUrl': 'https://dadosabertos.camara.leg.br/api/v2/proposicoes',
                        'fetchedAt': '2026-09-01', 'total': 1,
                        'items': [{'id': '7', 'titulo': 'PL 9/2024', 'ementa': 'Ementa',
                                   'situacao': None, 'url': 'https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=7'}]}
            profiles._write_profile_cache('camara:204379', {
                'contact': contact, 'mandato': mandate, 'projetos': complete,
            }, raw_root)
            failed = {'status': 'unavailable', 'period': profiles.CHAMBER_PROJECTS_PERIOD,
                      'sourceUrl': complete['sourceUrl'], 'fetchedAt': '2026-10-07', 'total': None,
                      'items': [], 'detail': 'Falha na página 1 de proposições (RuntimeError); resultado incompleto.'}
            with patch.object(profiles, '_request_json', side_effect=OSError('offline')), \
                    patch.object(profiles, '_office_section', return_value={'status': 'unavailable'}), \
                    patch.object(profiles, 'fetch_chamber_projects', return_value=failed) as fetch:
                result = profiles.build_profile(authority, {}, {}, {}, raw_root=raw_root,
                                                 collect=True, refresh=True)
            fetch.assert_called_once_with('camara:204379')
            self.assertEqual(result['projetos']['status'], 'imported')
            self.assertEqual(result['projetos']['total'], 1)
            self.assertEqual(result['projetos']['fetchedAt'], '2026-09-01')
            self.assertTrue(result['projetos']['stale'])
            self.assertIn('Falha na página 1', result['projetos']['detail'])

            partial = dict(complete, status='partial', total=None)
            partial['detail'] = 'Página anterior incompleta.'
            profiles._write_profile_cache('camara:204379', {
                'contact': contact, 'mandato': mandate, 'projetos': partial,
            }, raw_root)
            refreshed = dict(complete, fetchedAt='2026-10-07')
            with patch.object(profiles, '_office_section', return_value={'status': 'unavailable'}), \
                    patch.object(profiles, 'fetch_chamber_projects', return_value=refreshed) as fetch:
                result = profiles.build_profile(authority, {}, {}, {}, raw_root=raw_root, collect=True)
            fetch.assert_called_once_with('camara:204379')
            self.assertEqual(result['projetos']['status'], 'imported')
            self.assertEqual(result['projetos']['total'], 1)


if __name__ == '__main__':
    unittest.main()
