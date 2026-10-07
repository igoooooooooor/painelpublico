import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from ingest import senado_activity


def api_votes():
    return [
        {
            "casaSessao": "SF",
            "codigoSessao": 550469,
            "sequencialVotacao": 1,
            "codigoSessaoVotacao": 7047,
            "dataSessao": "2026-02-24",
            "descricaoVotacao": "Votação nominal da PEC 22/2025",
            "identificacao": "PEC 22/2025",
            "votacaoSecreta": "N",
            "votos": [
                {
                    "codigoParlamentar": 5672,
                    "nomeParlamentar": "Alan Rick",
                    "siglaPartidoParlamentar": "REPUBLICANOS",
                    "siglaUFParlamentar": "AC",
                    "siglaVotoParlamentar": "Sim",
                },
                {
                    "codigoParlamentar": 6358,
                    "nomeParlamentar": "Ana Paula Lobato",
                    "siglaPartidoParlamentar": "PDT",
                    "siglaUFParlamentar": "MA",
                    "siglaVotoParlamentar": "AP",
                    "descricaoVotoParlamentar": "Atividade parlamentar",
                },
                {
                    "codigoParlamentar": 5998,
                    "nomeParlamentar": "Daniella Ribeiro",
                    "siglaPartidoParlamentar": "PP",
                    "siglaUFParlamentar": "PB",
                    "siglaVotoParlamentar": "P-NRV",
                    "descricaoVotoParlamentar": "Presente – Não registrou voto",
                },
                {
                    "codigoParlamentar": 3830,
                    "nomeParlamentar": "Davi Alcolumbre",
                    "siglaPartidoParlamentar": "UNIÃO",
                    "siglaUFParlamentar": "AP",
                    "siglaVotoParlamentar": "Presidente (art. 51 RISF)",
                },
            ],
        },
        {
            "casaSessao": "SF",
            "codigoSessao": 550469,
            "sequencialVotacao": 2,
            "dataSessao": "2026-02-24",
            "descricaoVotacao": "Votação secreta da indicação",
            "identificacao": "MSF 1/2026",
            "votacaoSecreta": "S",
            "votos": [],
        },
        {
            "casaSessao": "CN",
            "codigoSessao": 550469,
            "sequencialVotacao": 3,
            "dataSessao": "2026-02-24",
            "descricaoVotacao": "Votação em sessão conjunta",
            "votacaoSecreta": "N",
            "votos": [],
        },
        {
            "casaSessao": "SF",
            "codigoSessao": 550468,
            "sequencialVotacao": 4,
            "dataSessao": "2025-12-18",
            "descricaoVotacao": "Votação fora do recorte",
            "votacaoSecreta": "N",
            "votos": [],
        },
    ]


class SenateActivityTests(unittest.TestCase):
    def test_normalizes_senate_nominal_votes_and_preserves_source_labels(self):
        rows = senado_activity.normalize_votes(api_votes())
        self.assertEqual(len(rows), 1)
        nominal = rows[0]
        self.assertEqual(nominal["id"], "senado:550469:1")
        self.assertEqual(nominal["titulo"], "Votação nominal da PEC 22/2025")
        self.assertEqual(nominal["data"], "2026-02-24")
        self.assertEqual(nominal["proposicao"], "PEC 22/2025")
        self.assertEqual(nominal["sourceUrl"],
                         "https://legis.senado.leg.br/dadosabertos/votacao?codigoSessao=550469")
        self.assertEqual(nominal["rows"], [
            ["senado:5672", "Alan Rick", "REPUBLICANOS", "AC", "Sim"],
            ["senado:6358", "Ana Paula Lobato", "PDT", "MA", "Atividade parlamentar"],
            ["senado:5998", "Daniella Ribeiro", "PP", "PB", "Presente – Não registrou voto"],
            ["senado:3830", "Davi Alcolumbre", "UNIÃO", "AP", "Presidente (art. 51 RISF)"],
        ])
        self.assertFalse(nominal["secreta"])
        _items, counts = senado_activity._normalized_vote_payload(api_votes())
        self.assertEqual(counts["secret"], 1)

    def test_presence_section_is_explicitly_unavailable_without_zero_counts(self):
        section = senado_activity._attendance_section(2026)
        self.assertEqual(section["status"], "unavailable")
        self.assertEqual(section["unit"], "sessoes")
        self.assertEqual(section["period"], "2026")
        self.assertEqual(section["items"], [])
        self.assertNotIn("dias", section)
        self.assertNotIn("presente", section)
        self.assertIn("Diário do Senado Federal", section["detail"])
        self.assertIsNone(section["fetchedAt"])

    def test_offline_build_uses_raw_cache_and_keeps_attendance_unknown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = senado_activity._cache_path(root, 2026)
            cache = {
                "sourceUrl": senado_activity.votes_url(2026),
                "fetchedAt": "2026-10-07T13:00:00+00:00",
                "data": api_votes(),
            }
            senado_activity._atomic_json(cache_path, cache)
            output = root / "data" / "snapshots" / "senado-atividade.json"

            snapshot, stats = senado_activity.build_snapshot(root=root, output=output)

            self.assertEqual(snapshot["year"], 2026)
            self.assertEqual(snapshot["presenca"]["status"], "unavailable")
            self.assertEqual(snapshot["presenca"]["items"], [])
            self.assertEqual(snapshot["votacoes"]["status"], "imported")
            self.assertEqual(snapshot["votacoes"]["fetchedAt"], cache["fetchedAt"])
            self.assertEqual(len(snapshot["votacoes"]["items"]), 1)
            self.assertEqual(snapshot["votacoes"]["secretCount"], 1)
            self.assertEqual(snapshot["votacoes"]["period"], senado_activity._source_period(
                cache["sourceUrl"], 2026, cache["fetchedAt"],
            ))
            self.assertEqual(stats["votes"], 1)
            self.assertEqual(stats["secretVotes"], 1)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), snapshot)

    def test_collect_requests_calendar_year_and_writes_cache_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seen = []

            def request(url):
                seen.append(url)
                return api_votes(), "2026-10-07T13:00:00+00:00"

            snapshot, _ = senado_activity.build_snapshot(
                root=root, collect=True, request=request,
            )

            parsed = urlparse(seen[0])
            self.assertEqual(parsed.path, "/dadosabertos/votacao")
            self.assertEqual(parse_qs(parsed.query), {
                "dataInicio": ["2026-01-01"],
                "dataFim": [min(date.today(), date(2026, 12, 31)).isoformat()],
            })
            cache = json.loads(senado_activity._cache_path(root, 2026).read_text(encoding="utf-8"))
            self.assertEqual(cache["fetchedAt"], "2026-10-07T13:00:00+00:00")
            self.assertEqual(cache["data"], api_votes())
            self.assertEqual(snapshot["votacoes"]["status"], "imported")
            self.assertEqual(snapshot["votacoes"]["secretCount"], 1)

    def test_refresh_failure_preserves_previous_cache_and_marks_snapshot_partial(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            previous = {
                "sourceUrl": senado_activity.votes_url(2026),
                "fetchedAt": "2026-09-01T10:00:00+00:00",
                "data": api_votes(),
            }
            cache_path = senado_activity._cache_path(root, 2026)
            senado_activity._atomic_json(cache_path, previous)

            def fail(_url):
                raise OSError("offline")

            snapshot, _ = senado_activity.build_snapshot(
                root=root, collect=True, refresh=True, request=fail,
            )

            self.assertEqual(snapshot["votacoes"]["status"], "partial")
            self.assertEqual(snapshot["votacoes"]["fetchedAt"], previous["fetchedAt"])
            self.assertIn("Falha ao atualizar", snapshot["votacoes"]["detail"])
            self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8")), previous)
            self.assertEqual(len(snapshot["votacoes"]["items"]), 1)

    def test_empty_or_failed_first_collection_does_not_write_zero_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "data" / "snapshots" / "senado-atividade.json"

            with self.assertRaises(senado_activity.SourceError):
                senado_activity.build_snapshot(
                    root=root,
                    output=output,
                    collect=True,
                    request=lambda _url: ([], "2026-10-07T13:00:00+00:00"),
                )

            self.assertFalse(output.exists())
            self.assertFalse(senado_activity._cache_path(root, 2026).exists())

    def test_offline_build_without_cache_does_not_write_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "data" / "snapshots" / "senado-atividade.json"
            with self.assertRaises(senado_activity.SourceError):
                senado_activity.build_snapshot(root=root, output=output)
            self.assertFalse(output.exists())

    def test_malformed_nominal_record_makes_the_section_partial(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            malformed = dict(api_votes()[0])
            malformed["codigoSessao"] = 550470
            malformed["sequencialVotacao"] = 10
            malformed["votos"] = []
            payload = [api_votes()[0], malformed]
            cache_path = senado_activity._cache_path(root, 2026)
            senado_activity._atomic_json(cache_path, {
                "sourceUrl": senado_activity.votes_url(2026),
                "fetchedAt": "2026-10-07T13:00:00+00:00",
                "data": payload,
            })

            snapshot, stats = senado_activity.build_snapshot(root=root)

            self.assertEqual(snapshot["votacoes"]["status"], "partial")
            self.assertEqual(len(snapshot["votacoes"]["items"]), 1)
            self.assertEqual(stats["malformedRows"], 1)
            self.assertIn("malformada", snapshot["votacoes"]["detail"])

    def test_activity_snapshot_reuses_the_matching_attendance_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            attendance = {
                "generatedAt": "2026-10-07T13:00:00+00:00",
                "year": 2026,
                "presenca": {
                    "status": "partial",
                    "unit": "sessoes",
                    "period": "2026-02-03 a 2026-10-06",
                    "sourceUrl": "https://legis.senado.leg.br/dadosabertos/plenario/agenda/mes/20261001",
                    "fetchedAt": "2026-10-07T12:00:00+00:00",
                    "detail": "Presenças registradas no DSF.",
                    "items": [{"id": "senado:5672", "nome": "Alan Rick", "presente": 2, "dias": None}],
                },
            }
            path = root / "data" / "snapshots" / "senado-presenca.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(attendance), encoding="utf-8")

            self.assertEqual(senado_activity._attendance_from_snapshot(root, 2026), attendance["presenca"])
            self.assertEqual(senado_activity._attendance_from_snapshot(root, 2025)["status"], "unavailable")

    def test_collector_refuses_years_outside_authorized_scope(self):
        with self.assertRaisesRegex(ValueError, "2026"):
            senado_activity.build_snapshot(year=2025)


if __name__ == "__main__":
    unittest.main()
