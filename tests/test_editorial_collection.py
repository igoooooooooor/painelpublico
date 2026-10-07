import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EDITORIAL_DIR = ROOT / "ingest" / "editorial"
if str(EDITORIAL_DIR) not in sys.path:
    sys.path.insert(0, str(EDITORIAL_DIR))
collection = importlib.import_module("coleta")


class EditorialCollectionTests(unittest.TestCase):
    def test_deputy_roster_follows_every_official_next_page(self):
        first = collection.DEPUTIES_URL
        second = "https://dadosabertos.camara.leg.br/api/v2/deputados?pagina=2"
        responses = {
            first: {"dados": [{"id": 1}], "links": [{"rel": "next", "href": second}]},
            second: {"dados": [{"id": 2}], "links": []},
        }
        requests = []

        def fetch(url, filename, js=False):
            requests.append((url, filename, js))
            return responses[url]

        result = collection.paged(first, "test-deps", fetch=fetch)

        self.assertEqual([row["id"] for row in result["dados"]], [1, 2])
        self.assertEqual([request[0] for request in requests], [first, second])
        self.assertTrue(all(request[2] for request in requests))

    def test_votes_use_the_versioned_metadata_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "votacoes.json"
            output = root / "votos.json"
            metadata.write_text(json.dumps([{"id": "123-4"}]), encoding="utf-8")
            requested = []

            def fetch(url, filename, js=False):
                requested.append(url)
                return {"dados": [{
                    "deputado_": {"id": 42, "nome": "Pessoa", "siglaPartido": "PT", "siglaUf": "SP"},
                    "tipoVoto": "Sim",
                }, {
                    "deputado_": {"id": 43, "nome": "Voto secreto", "siglaPartido": "PV", "siglaUf": "RJ"},
                    "tipoVoto": None,
                }, {
                    "deputado_": {"nome": "Sem ID", "siglaPartido": "PT", "siglaUf": "SP"},
                    "tipoVoto": "Não",
                }]}

            result = collection.collect_votes(fetch=fetch, output=output, metadata_path=metadata)

            self.assertEqual(list(result), ["123-4"])
            self.assertIn("/votacoes/123-4/votos", requested[0])
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {
                "123-4": [
                    [42, "Pessoa", "PT", "SP", "Sim"],
                    [43, "Voto secreto", "PV", "RJ", None],
                ],
            })


if __name__ == "__main__":
    unittest.main()
