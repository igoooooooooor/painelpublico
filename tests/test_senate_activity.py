import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from ingest import senate_activity


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


def dated_vote(session_date, session_code, secrecy="N"):
    vote = dict(api_votes()[0])
    vote["codigoSessao"] = session_code
    vote["sequencialVotacao"] = 1
    vote["dataSessao"] = session_date
    vote["votacaoSecreta"] = secrecy
    return vote


class SenateActivityTests(unittest.TestCase):
    def test_normalizes_senate_nominal_votes_and_preserves_source_labels(self):
        rows = senate_activity.normalize_votes(api_votes())
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
        _items, counts = senate_activity._normalized_vote_payload(api_votes())
        self.assertEqual(counts["secret"], 1)

    def test_unknown_secrecy_is_not_treated_as_public(self):
        for secrecy in (" ", "n", None):
            with self.subTest(secrecy=secrecy):
                unknown = dated_vote("2026-03-01", 550470, secrecy=secrecy)
                items, counts = senate_activity._normalized_vote_payload([unknown])
                self.assertEqual(items, [])
                self.assertEqual(counts["secret"], 0)
                self.assertEqual(counts["malformed"], 1)

    def test_public_individual_vote_roster_counts_when_description_omits_nominal(self):
        vote = dated_vote("2026-03-01", 550471)
        vote["descricaoVotacao"] = "Votação da PEC nº 1/2026"
        vote["identificacao"] = "PEC nº 1/2026"
        items, counts = senate_activity._normalized_vote_payload([vote])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["titulo"], "Votação da PEC nº 1/2026")
        self.assertEqual(counts["unclassified"], 0)

    def test_presence_only_roster_is_not_classified_as_a_public_roll_call(self):
        vote = dated_vote("2026-03-01", 550472)
        vote["descricaoVotacao"] = "Votação da PEC nº 1/2026"
        for member_vote in vote["votos"]:
            member_vote["siglaVotoParlamentar"] = "AP"
        items, counts = senate_activity._normalized_vote_payload([vote])
        self.assertEqual(items, [])
        self.assertEqual(counts["unclassified"], 1)

    def test_explicit_roll_call_choices_are_recognized(self):
        for choice in ("Sim", "Não", "Abstenção", "Obstrução"):
            with self.subTest(choice=choice):
                vote = dated_vote("2026-03-01", 550473)
                vote["descricaoVotacao"] = "Votação da PEC nº 1/2026"
                for member_vote in vote["votos"]:
                    member_vote["siglaVotoParlamentar"] = "AP"
                vote["votos"][0]["siglaVotoParlamentar"] = choice
                items, counts = senate_activity._normalized_vote_payload([vote])
                self.assertEqual(len(items), 1)
                self.assertEqual(counts["unclassified"], 0)

    def test_presence_section_is_explicitly_unavailable_without_zero_counts(self):
        section = senate_activity._attendance_section(2026)
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
            cache_path = senate_activity._cache_path(root, 2026)
            cache = {
                "sourceUrl": senate_activity.votes_url(2026),
                "fetchedAt": "2026-10-07T13:00:00+00:00",
                "data": api_votes(),
            }
            senate_activity._atomic_json(cache_path, cache)
            output = root / "data" / "snapshots" / "senado-atividade.json"

            snapshot, stats = senate_activity.build_snapshot(root=root, output=output)

            self.assertEqual(snapshot["year"], 2026)
            self.assertEqual(snapshot["presenca"]["status"], "unavailable")
            self.assertEqual(snapshot["presenca"]["items"], [])
            self.assertEqual(snapshot["votacoes"]["status"], "imported")
            self.assertEqual(snapshot["votacoes"]["fetchedAt"], cache["fetchedAt"])
            self.assertEqual(len(snapshot["votacoes"]["items"]), 1)
            self.assertEqual(snapshot["votacoes"]["secretCount"], 1)
            self.assertEqual(snapshot["votacoes"]["period"], senate_activity._source_period(
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

            snapshot, _ = senate_activity.build_snapshot(
                root=root, collect=True, request=request,
            )

            parsed = urlparse(seen[0])
            self.assertEqual(parsed.path, "/dadosabertos/votacao")
            self.assertEqual(parse_qs(parsed.query), {
                "dataInicio": ["2026-01-01"],
                "dataFim": [min(date.today(), date(2026, 12, 31)).isoformat()],
            })
            cache = json.loads(senate_activity._cache_path(root, 2026).read_text(encoding="utf-8"))
            self.assertEqual(cache["fetchedAt"], "2026-10-07T13:00:00+00:00")
            self.assertEqual(cache["data"], api_votes())
            self.assertEqual(snapshot["votacoes"]["status"], "imported")
            self.assertEqual(snapshot["votacoes"]["secretCount"], 1)

    def test_refresh_failure_preserves_previous_cache_and_marks_snapshot_partial(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            previous = {
                "sourceUrl": senate_activity.votes_url(2026),
                "fetchedAt": "2026-09-01T10:00:00+00:00",
                "data": api_votes(),
            }
            cache_path = senate_activity._cache_path(root, 2026)
            senate_activity._atomic_json(cache_path, previous)

            def fail(_url):
                raise OSError("offline")

            snapshot, _ = senate_activity.build_snapshot(
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

            with self.assertRaises(senate_activity.SourceError):
                senate_activity.build_snapshot(
                    root=root,
                    output=output,
                    collect=True,
                    request=lambda _url: ([], "2026-10-07T13:00:00+00:00"),
                )

            self.assertFalse(output.exists())
            self.assertFalse(senate_activity._cache_path(root, 2026).exists())

    def test_offline_build_without_cache_does_not_write_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "data" / "snapshots" / "senado-atividade.json"
            with self.assertRaises(senate_activity.SourceError):
                senate_activity.build_snapshot(root=root, output=output)
            self.assertFalse(output.exists())

    def test_malformed_nominal_record_makes_the_section_partial(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            malformed = dict(api_votes()[0])
            malformed["codigoSessao"] = 550470
            malformed["sequencialVotacao"] = 10
            malformed["votos"] = []
            payload = [api_votes()[0], malformed]
            cache_path = senate_activity._cache_path(root, 2026)
            senate_activity._atomic_json(cache_path, {
                "sourceUrl": senate_activity.votes_url(2026),
                "fetchedAt": "2026-10-07T13:00:00+00:00",
                "data": payload,
            })

            snapshot, stats = senate_activity.build_snapshot(root=root)

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

            self.assertEqual(senate_activity._attendance_from_snapshot(root, 2026), attendance["presenca"])
            self.assertEqual(senate_activity._attendance_from_snapshot(root, 2025)["status"], "unavailable")

    def test_collector_refuses_years_outside_authorized_scope(self):
        with self.assertRaisesRegex(ValueError, "2026"):
            senate_activity.build_snapshot(year=2025)

    def test_mandate_collection_bounds_dates_and_deduplicates_stable_vote_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requested = []

            def request(url):
                params = parse_qs(urlparse(url).query)
                start = date.fromisoformat(params["dataInicio"][0])
                end = date.fromisoformat(params["dataFim"][0])
                requested.append((start, end))
                year = start.year
                if year == 2023:
                    payload = [
                        dated_vote("2023-01-31", 230001),
                        dated_vote("2023-02-01", 230002),
                        dated_vote("2023-02-01", 230002),
                        dated_vote("2023-03-01", 230003, secrecy="S"),
                    ]
                elif year == 2024:
                    payload = [dated_vote("2024-01-01", 240001, secrecy="?")]
                elif year == 2026:
                    payload = [
                        dated_vote("2026-10-09", 260001),
                        dated_vote("2026-10-10", 260002),
                    ]
                else:
                    payload = []
                return payload, f"{year}-10-09T12:00:00+00:00"

            snapshot, stats = senate_activity.build_mandate_snapshot(
                root=root,
                collect=True,
                through=date(2026, 10, 9),
                request=request,
            )

            self.assertEqual(requested[0], (date(2023, 2, 1), date(2023, 12, 31)))
            self.assertEqual(requested[-1], (date(2026, 1, 1), date(2026, 10, 9)))
            votes = snapshot["votacoes"]
            self.assertEqual(snapshot["year"], 2026)
            self.assertEqual(votes["startDate"], "2023-02-01")
            self.assertEqual(votes["endDate"], "2026-10-09")
            self.assertEqual(votes["status"], "partial")
            self.assertEqual([item["data"] for item in votes["items"]], [
                "2026-10-09", "2023-02-01",
            ])
            self.assertEqual([item["id"] for item in votes["items"]], [
                "senado:260001:1", "senado:230002:1",
            ])
            self.assertEqual(votes["secretCount"], 1)
            self.assertEqual(stats["votes"], 2)
            self.assertEqual(stats["missingYears"], 0)
            self.assertEqual([source["year"] for source in votes["sources"]], [2023, 2024, 2025, 2026])
            self.assertEqual(votes["sources"][0]["startDate"], "2023-02-01")
            self.assertEqual(votes["sources"][-1]["endDate"], "2026-10-09")
            self.assertEqual(votes["sources"][2]["status"], "imported")
            self.assertEqual(votes["sources"][1]["status"], "partial")

    def test_mandate_offline_build_marks_missing_years_without_claiming_coverage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            early = dated_vote("2023-02-01", 230002)
            senate_activity._atomic_json(senate_activity._cache_path(root, 2023), {
                "sourceUrl": senate_activity.votes_url(
                    2023, through=date(2023, 12, 31), start=date(2023, 2, 1),
                ),
                "fetchedAt": "2024-01-02T12:00:00+00:00",
                "data": [early],
            })
            current = api_votes()
            senate_activity._atomic_json(senate_activity._cache_path(root, 2026), {
                "sourceUrl": senate_activity.votes_url(2026, through=date(2026, 10, 9)),
                "fetchedAt": "2026-10-09T12:00:00+00:00",
                "data": current,
            })

            snapshot, stats = senate_activity.build_mandate_snapshot(
                root=root, through=date(2026, 10, 9),
            )

            sources = snapshot["votacoes"]["sources"]
            self.assertEqual(snapshot["votacoes"]["status"], "partial")
            self.assertEqual([row["status"] for row in sources], [
                "imported", "missing", "missing", "imported",
            ])
            self.assertEqual(sources[1]["startDate"], None)
            self.assertEqual(sources[1]["endDate"], None)
            self.assertEqual(stats["missingYears"], 2)
            self.assertEqual(snapshot["presenca"]["status"], "unavailable")

    def test_mandate_failed_current_year_refresh_keeps_cache_and_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for year in (2023, 2024, 2025):
                senate_activity._atomic_json(senate_activity._cache_path(root, year), {
                    "sourceUrl": senate_activity.votes_url(
                        year,
                        through=date(year, 12, 31),
                        start=date(year, 2, 1) if year == 2023 else date(year, 1, 1),
                    ),
                    "fetchedAt": f"{year}-12-31T12:00:00+00:00",
                    "data": [dated_vote(f"{year}-02-01", int(f"{year}0001"))],
                })
            current_path = senate_activity._cache_path(root, 2026)
            old_current = {
                "sourceUrl": senate_activity.votes_url(2026, through=date(2026, 6, 30)),
                "fetchedAt": "2026-07-01T12:00:00+00:00",
                "data": [dated_vote("2026-06-30", 260001)],
            }
            senate_activity._atomic_json(current_path, old_current)

            def fail(_url):
                raise OSError("offline")

            snapshot, _stats = senate_activity.build_mandate_snapshot(
                root=root,
                collect=True,
                through=date(2026, 10, 9),
                request=fail,
            )

            current_source = snapshot["votacoes"]["sources"][-1]
            self.assertEqual(current_source["status"], "partial")
            self.assertEqual(snapshot["votacoes"]["sources"][0]["status"], "imported")
            self.assertEqual(current_source["fetchedAt"], old_current["fetchedAt"])
            self.assertEqual(current_source["endDate"], "2026-06-30")
            self.assertIn("Falha ao consultar 2026", current_source["detail"])
            self.assertEqual(json.loads(current_path.read_text(encoding="utf-8")), old_current)
            self.assertIn("senado:260001:1", [item["id"] for item in snapshot["votacoes"]["items"]])

    def test_failed_refresh_uses_broader_previous_snapshot_coverage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def request(url):
                year = date.fromisoformat(parse_qs(urlparse(url).query)["dataInicio"][0]).year
                if year == 2026:
                    payload = [
                        dated_vote("2026-06-30", 260001),
                        dated_vote("2026-10-08", 260002),
                    ]
                else:
                    payload = [dated_vote(f"{year}-02-01", int(f"{year}0001"))]
                return payload, f"{year}-10-09T12:00:00+00:00"

            original, _stats = senate_activity.build_mandate_snapshot(
                root=root,
                collect=True,
                through=date(2026, 10, 9),
                request=request,
            )
            prior_current_source = original["votacoes"]["sources"][-1]
            current_path = senate_activity._cache_path(root, 2026)
            stale_cache = {
                "sourceUrl": senate_activity.votes_url(2026, through=date(2026, 6, 30)),
                "fetchedAt": "2026-07-01T12:00:00+00:00",
                "data": [dated_vote("2026-06-30", 260001)],
            }
            senate_activity._atomic_json(current_path, stale_cache)

            def fail(_url):
                raise OSError("offline")

            rebuilt, _stats = senate_activity.build_mandate_snapshot(
                root=root,
                collect=True,
                through=date(2026, 10, 9),
                request=fail,
            )

            current_source = rebuilt["votacoes"]["sources"][-1]
            current_ids = {item["id"] for item in rebuilt["votacoes"]["items"]}
            self.assertEqual(current_source["status"], "partial")
            self.assertEqual(current_source["endDate"], "2026-10-09")
            self.assertEqual(current_source["fetchedAt"], prior_current_source["fetchedAt"])
            self.assertIn("senado:260002:1", current_ids)
            self.assertEqual(json.loads(current_path.read_text(encoding="utf-8")), stale_cache)

    def test_mandate_offline_build_preserves_previous_year_data_when_caches_are_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def request(url):
                year = date.fromisoformat(parse_qs(urlparse(url).query)["dataInicio"][0]).year
                return [dated_vote(f"{year}-02-01", int(f"{year}0001"))], f"{year}-12-31T12:00:00+00:00"

            original, _stats = senate_activity.build_mandate_snapshot(
                root=root,
                collect=True,
                through=date(2026, 10, 9),
                request=request,
            )
            original_ids = {item["id"] for item in original["votacoes"]["items"]}
            for year in (2023, 2024, 2025):
                senate_activity._cache_path(root, year).unlink()

            rebuilt, _stats = senate_activity.build_mandate_snapshot(
                root=root, through=date(2026, 10, 9),
            )

            rebuilt_ids = {item["id"] for item in rebuilt["votacoes"]["items"]}
            self.assertEqual(rebuilt_ids, original_ids)
            self.assertEqual(rebuilt["votacoes"]["status"], "partial")
            self.assertEqual([row["status"] for row in rebuilt["votacoes"]["sources"]], [
                "partial", "partial", "partial", "imported",
            ])

    def test_legacy_annual_snapshot_fallback_uses_date_range_from_source_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "data" / "snapshots" / "senado-atividade.json"
            old_snapshot = {
                "year": 2026,
                "votacoes": {
                    "status": "imported",
                    "sourceUrl": senate_activity.votes_url(2026, through=date(2026, 10, 7)),
                    "fetchedAt": "2026-10-07T12:00:00+00:00",
                    "items": senate_activity.normalize_votes(api_votes()),
                },
            }
            senate_activity._atomic_json(output, old_snapshot)

            snapshot, _stats = senate_activity.build_mandate_snapshot(
                root=root,
                output=output,
                through=date(2026, 10, 9),
            )

            current_source = snapshot["votacoes"]["sources"][-1]
            self.assertEqual(current_source["status"], "partial")
            self.assertEqual(current_source["endDate"], "2026-10-07")

    def test_mandate_cutoff_never_claims_future_dates(self):
        self.assertEqual(
            senate_activity._mandate_cutoff(date.max),
            date.today(),
        )

    def test_mandate_uses_2026_attendance_snapshot_independent_of_vote_cutoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            senate_activity._atomic_json(senate_activity._cache_path(root, 2023), {
                "sourceUrl": senate_activity.votes_url(
                    2023, through=date(2023, 12, 31), start=date(2023, 2, 1),
                ),
                "fetchedAt": "2024-01-02T12:00:00+00:00",
                "data": [dated_vote("2023-02-01", 230002)],
            })
            attendance = {
                "year": 2026,
                "presenca": {
                    "status": "imported",
                    "unit": "sessoes",
                    "items": [{"id": "senado:5672", "nome": "Alan Rick"}],
                },
            }
            attendance_path = root / "data" / "snapshots" / "senado-presenca.json"
            senate_activity._atomic_json(attendance_path, attendance)

            snapshot, _stats = senate_activity.build_mandate_snapshot(
                root=root, through=date(2023, 2, 1),
            )

            self.assertEqual(snapshot["year"], 2026)
            self.assertEqual(snapshot["votacoes"]["endDate"], "2023-02-01")
            self.assertEqual(snapshot["presenca"], attendance["presenca"])


if __name__ == "__main__":
    unittest.main()
