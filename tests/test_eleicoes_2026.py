import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ingest import eleicoes_2026 as el

HEADER = ['DT_GERACAO', 'HH_GERACAO', 'NR_TURNO', 'DT_ELEICAO', 'SG_UF', 'NM_UE', 'DS_CARGO', 'SQ_CANDIDATO',
          'NR_CANDIDATO', 'NM_CANDIDATO', 'NM_URNA_CANDIDATO', 'NR_CPF_CANDIDATO', 'SG_PARTIDO', 'DT_NASCIMENTO',
          'DS_SIT_TOT_TURNO']


def cand(sq, nome, urna, nasc, cargo='DEPUTADO FEDERAL', uf='SP', sit='ELEITO POR QP', turno='1'):
    return {'DT_GERACAO': '07/10/2026', 'HH_GERACAO': '16:30:39', 'NR_TURNO': turno,
            'DT_ELEICAO': '04/10/2026' if turno == '1' else '25/10/2026', 'SG_UF': uf, 'NM_UE': 'ESTADO',
            'DS_CARGO': cargo, 'SQ_CANDIDATO': sq, 'NR_CANDIDATO': '1234', 'NM_CANDIDATO': nome,
            'NM_URNA_CANDIDATO': urna, 'NR_CPF_CANDIDATO': '12345678901', 'SG_PARTIDO': 'AAA',
            'DT_NASCIMENTO': nasc, 'DS_SIT_TOT_TURNO': sit}


def person(identifier, name, uf='SP'):
    source = 'senado_senators_current' if identifier.startswith('senado:') else 'camara_deputies_current'
    return {'id': identifier, 'name': name, 'uf': uf, 'sourceId': source}


ROSTER = [
    person('camara:1', 'Ana Silva'),
    person('camara:2', 'Bruno Turno'),
    person('camara:3', 'Pedro Campos', 'PE'),
    person('camara:4', 'Erika Hilton'),
    person('camara:5', 'Outra Urna'),
    person('senado:6', 'Jader Barbalho', 'PA'),
    person('camara:7', 'João Pereira'),
    person('camara:8', 'Sem Identidade'),
    person('camara:9', 'Sem Candidatura'),
]
IDENTITIES = {
    'camara:1': {'nomeCivil': 'Ana Maria da Silva', 'nascimento': '1980-01-02'},
    'camara:2': {'nomeCivil': 'BRUNO SEGUNDO TURNO', 'nascimento': '1975-03-04'},
    'camara:3': {'nomeCivil': 'PEDRO HENRIQUE DE A. L. C. CAMPOS', 'nascimento': '1995-10-28'},
    'camara:4': {'nomeCivil': 'ERIKA SANTOS SILVA', 'nascimento': '1992-12-09'},
    'camara:5': {'nomeCivil': 'MARIA OUTRA', 'nascimento': '1990-06-06'},
    'senado:6': {'nomeCivil': 'Jader Fontenelle Barbalho', 'nascimento': '1944-10-27'},
    'camara:7': {'nomeCivil': 'JOÃO PEREIRA', 'nascimento': '1970-05-05'},
    'camara:9': {'nomeCivil': 'NINGUEM CANDIDATO', 'nascimento': '1960-01-01'},
}
CANDIDATES = [
    cand('1', 'ANA MARIA DA SÍLVA', 'ANA SILVA', '02/01/1980'),
    cand('2', 'BRUNO SEGUNDO TURNO', 'BRUNO', '04/03/1975', 'GOVERNADOR', sit='2º TURNO'),
    cand('2', 'BRUNO SEGUNDO TURNO', 'BRUNO', '04/03/1975', 'GOVERNADOR', sit='ELEITO', turno='2'),
    cand('3', 'PEDRO HENRIQUE DE ANDRADE LIMA CARNEIRO CAMPOS', 'PEDRO CAMPOS', '28/10/1995', uf='PE'),
    cand('4', 'ERIKA HILTON', 'ERIKA HILTON', '09/12/1992'),
    cand('5', 'CARLA DE TAL', 'OUTRA URNA', '06/06/1990', uf='RJ'),
    cand('6', 'JADER FONTENELLE BARBALHO', 'JADER BARBALHO', '27/10/1945', '1º SUPLENTE', 'PA', 'ELEITO'),
    cand('7', 'JOAO PEREIRA', 'JOAO', '05/05/1970'),
    cand('70', 'JOAO PEREIRA', 'JOAO P', '05/05/1970', sit='NÃO ELEITO'),
]


class Eleicoes2026Tests(unittest.TestCase):
    def test_names_and_dates_normalize(self):
        self.assertEqual(el.name_key('José  da Silva-Júnior'), 'jose da silva junior')
        self.assertEqual(el.birth_key('09/12/1992'), '1992-12-09')
        self.assertEqual(el.birth_key('1992-12-09T00:00:00'), '1992-12-09')
        self.assertIsNone(el.birth_key(''))

    def test_similar_names_accept_initials_and_extra_surnames_only(self):
        self.assertTrue(el.similar_names('PEDRO HENRIQUE DE A. L. C. CAMPOS', 'PEDRO HENRIQUE DE ANDRADE LIMA CARNEIRO CAMPOS'))
        self.assertTrue(el.similar_names('MARIA LEAL ARRAES DE ALENCAR', 'MARIA LEAL ARRAES DE ALENCAR FORTALEZA'))
        self.assertTrue(el.similar_names('Omar José Abdel Aziz', 'OMAR JOSE ABDELAZIZ'))
        self.assertFalse(el.similar_names('ERIKA SANTOS SILVA', 'ERIKA HILTON'))
        self.assertFalse(el.similar_names('JOSE SILVA', 'JOAO SILVA'))
        self.assertFalse(el.similar_names('ANA', 'ANA MARIA'))

    def test_rules_run_in_order_and_never_guess(self):
        out = el.match(ROSTER, IDENTITIES, CANDIDATES)
        self.assertEqual(out['camara:1']['criterio'], 'nome')
        self.assertEqual((out['camara:2']['situacao'], out['camara:2']['turno'], out['camara:2']['dataEleicao']), ('ELEITO', 2, '2026-10-25'))
        self.assertEqual(out['camara:3']['criterio'], 'nome-parecido')
        self.assertEqual(out['camara:4']['criterio'], 'nome-de-urna')
        self.assertEqual(out['camara:5'], {'status': 'sem-correspondencia'})  # nome de urna exige a mesma UF
        self.assertEqual((out['senado:6']['criterio'], out['senado:6']['cargo']), ('ano-divergente', '1º SUPLENTE'))
        self.assertEqual(out['camara:7'], {'status': 'ambiguo'})
        self.assertEqual(out['camara:8'], {'status': 'indisponivel'})
        self.assertEqual(out['camara:9'], {'status': 'sem-correspondencia'})

    def test_offline_snapshot_keeps_personal_data_out(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            where = el.paths(root)
            where['imports'].parent.mkdir(parents=True)
            where['imports'].write_text(json.dumps({'sources': [], 'authorities': ROSTER}), encoding='utf-8')
            where['identities'].parent.mkdir(parents=True)
            where['identities'].write_text(json.dumps(IDENTITIES), encoding='utf-8')
            table = io.StringIO()
            writer = csv.DictWriter(table, HEADER, delimiter=';')
            writer.writeheader(); writer.writerows(CANDIDATES)
            with zipfile.ZipFile(where['zip'], 'w') as archive:
                archive.writestr('leiame.pdf', b'')
                archive.writestr('consulta_cand_2026_BRASIL.csv', table.getvalue().encode('latin-1'))
            snapshot = el.build_snapshot(root)
            text = where['output'].read_text(encoding='utf-8')
        self.assertEqual(snapshot['cobertura'], {'lista': 9, 'encontrada': 5, 'sem-correspondencia': 2, 'ambiguo': 1, 'indisponivel': 1})
        self.assertEqual(snapshot['fonte']['geradoNoTse'], '07/10/2026 16:30:39')
        self.assertEqual(set(snapshot['criterios']), {'nome', 'nome-parecido', 'nome-de-urna', 'ano-divergente'})
        for private in ('12345678901', 'Ana Maria da Silva', '1980-01-02', '02/01/1980', '"nomeCivil"', '"nascimento"'):
            self.assertNotIn(private, text)

    def test_identity_comes_from_official_apis_and_failures_keep_the_cache(self):
        camara = {'dados': {'nomeCivil': ' ANA MARIA ', 'dataNascimento': '1980-01-02'}}
        senado = {'DetalheParlamentar': {'Parlamentar': {'IdentificacaoParlamentar': {'NomeCompletoParlamentar': 'Dora Senadora'},
                                                          'DadosBasicosParlamentar': {'DataNascimento': '1960-02-03'}}}}
        found = el.fetch_identity('camara:1', lambda url: camara)
        self.assertEqual((found['nomeCivil'], found['nascimento']), ('ANA MARIA', '1980-01-02'))
        self.assertEqual(el.fetch_identity('senado:2', lambda url: senado)['nascimento'], '1960-02-03')
        self.assertIsNone(el.fetch_identity('camara:3', lambda url: {'dados': {'nomeCivil': 'SEM DATA'}}))

        def failing(identifier):
            raise RuntimeError('fora do ar')
        cache = {'camara:1': {'nomeCivil': 'ANTIGO', 'nascimento': '1980-01-02'}}
        self.assertEqual(el.collect_identities([{'id': 'camara:1'}, {'id': 'camara:2'}], cache, refresh=True, fetch=failing), 2)
        self.assertEqual(cache, {'camara:1': {'nomeCivil': 'ANTIGO', 'nascimento': '1980-01-02'}})


if __name__ == '__main__':
    unittest.main()
