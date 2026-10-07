import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from ingest import cities


CANDIDATE_HEADER = [
    "DT_GERACAO", "NR_TURNO", "CD_TIPO_ELEICAO", "NM_TIPO_ELEICAO", "DT_ELEICAO",
    "SG_UF", "SG_UE", "NM_UE", "DS_CARGO",
    "SQ_CANDIDATO", "NM_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "DS_SIT_TOT_TURNO",
    "NR_CPF_CANDIDATO", "NR_TITULO_ELEITORAL_CANDIDATO", "DT_NASCIMENTO", "DS_EMAIL",
]


def candidate_row(
    identifier,
    name,
    office,
    status,
    turn="1",
    uf="SP",
    ue="3550308",
    ballot=None,
    election_type="2",
    election_name="ELEIÇÃO ORDINÁRIA",
    election_date="06/10/2024",
):
    return {
        "DT_GERACAO": "07/10/2026",
        "NR_TURNO": turn,
        "CD_TIPO_ELEICAO": election_type,
        "NM_TIPO_ELEICAO": election_name,
        "DT_ELEICAO": election_date,
        "SG_UF": uf,
        "SG_UE": ue,
        "NM_UE": "SAO PAULO",
        "DS_CARGO": office,
        "SQ_CANDIDATO": identifier,
        "NM_CANDIDATO": name,
        "NM_URNA_CANDIDATO": ballot or name,
        "SG_PARTIDO": "AAA",
        "DS_SIT_TOT_TURNO": status,
        "NR_CPF_CANDIDATO": "01234567890",
        "NR_TITULO_ELEITORAL_CANDIDATO": "123456789123",
        "DT_NASCIMENTO": "01/01/1980",
        "DS_EMAIL": "secret@example.test",
    }


def candidate_archive(rows, year=2024):
    table = io.StringIO()
    writer = csv.DictWriter(table, CANDIDATE_HEADER, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("leiame.pdf", b"layout description")
        archive.writestr(f"consulta_cand_{year}_BRASIL.csv", table.getvalue().encode("latin-1"))
    data.seek(0)
    return data


VOTE_HEADER = [
    "NR_TURNO", "CD_MUNICIPIO", "NM_MUNICIPIO", "SG_UF", "DS_CARGO", "SQ_CANDIDATO",
    "QT_VOTOS_NOMINAIS_VALIDOS", "QT_VOTOS_NOMINAIS", "DT_GERACAO",
]


def vote_row(identifier, votes, city_code="100", uf="SP", turn="1", office="DEPUTADO FEDERAL"):
    return [turn, city_code, "SAO PAULO", uf, office, identifier, str(votes), str(votes), "07/10/2026"]


def vote_archive(rows):
    table = io.StringIO()
    writer = csv.writer(table, delimiter=";")
    writer.writerow(VOTE_HEADER)
    writer.writerows(rows)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("votacao_candidato_munzona_2026_SP.csv", table.getvalue().encode("latin-1"))
    return data


class CitiesIngestTests(unittest.TestCase):
    def test_candidate_archive_projects_allowlisted_public_fields_only(self):
        rows = [
            candidate_row("1", "Prefeita Eleita", "PREFEITO", "ELEITO"),
            # Round two is encountered before round one: a later non-elected
            # result must prevent the stale round-one elected row from winning.
            candidate_row("2", "Elected Then Lost", "VEREADOR", "NÃO ELEITO", turn="2"),
            candidate_row("2", "Elected Then Lost", "VEREADOR", "ELEITO POR QP", turn="1"),
            candidate_row("3", "Elected In Runoff", "PREFEITO", "ELEITO", turn="2"),
            candidate_row("4", "Federal Loser", "DEPUTADO FEDERAL", "NÃO ELEITO"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "candidacies_2024_v2.jsonl"
            meta, federal_ids = cities._project_candidate_archive(candidate_archive(rows), cache, 2024)
            cached_text = cache.read_text(encoding="utf-8")
        cached = [json.loads(line) for line in cached_text.splitlines()]
        self.assertEqual({row["id"] for row in cached}, {"1", "3"})
        self.assertEqual(next(row["round"] for row in cached if row["id"] == "3"), 2)
        self.assertEqual(federal_ids, set())
        self.assertEqual(meta["rowsSeen"], len(rows))
        for private_value in ("01234567890", "123456789123", "01/01/1980", "secret@example.test"):
            self.assertNotIn(private_value, cached_text)

    def test_elected_result_requires_an_official_result_status(self):
        self.assertTrue(cities._is_elected("ELEITO"))
        self.assertTrue(cities._is_elected("ELEITO POR QP"))
        self.assertTrue(cities._is_elected("ELEITO POR MÉDIA"))
        self.assertFalse(cities._is_elected("ELEITO APÓS RECONTAGEM"))
        self.assertFalse(cities._is_elected("NÃO ELEITO"))

    def test_candidate_archive_excludes_supplemental_elections(self):
        rows = [
            candidate_row("1", "Ordinary Mayor", "PREFEITO", "ELEITO"),
            candidate_row(
                "2", "Supplemental Mayor", "PREFEITO", "ELEITO",
                election_type="1", election_name="ELEIÇÃO SUPLEMENTAR", election_date="05/10/2025",
            ),
            # A later supplemental result for the same candidate ID must not
            # replace the ordinary-election result.
            candidate_row(
                "1", "Ordinary Mayor", "PREFEITO", "NÃO ELEITO",
                election_type="1", election_name="ELEIÇÃO SUPLEMENTAR", election_date="05/10/2025",
            ),
        ]
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "candidacies_2024_v2.jsonl"
            meta, _federal_ids = cities._project_candidate_archive(candidate_archive(rows), cache, 2024)
            cached_ids = [json.loads(line)["id"] for line in cache.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(cached_ids, ["1"])
        self.assertEqual(meta["projectionVersion"], cities.CANDIDATE_CACHE_VERSION)
        self.assertEqual(meta["electionRowsExcluded"], 2)

    def test_crosswalk_discards_all_conflicting_or_wrong_uf_mappings(self):
        municipalities = [
            {"id": "5300108", "name": "Brasília", "uf": "DF"},
            {"id": "3550308", "name": "São Paulo", "uf": "SP"},
            {"id": "3304557", "name": "Rio de Janeiro", "uf": "RJ"},
        ]
        rows = [
            {"tseCode": "97012", "ibgeId": "5300108", "uf": "DF", "tseName": "BRASILIA"},
            {"tseCode": "100", "ibgeId": "3550308", "uf": "SP", "tseName": "SAO PAULO"},
            {"tseCode": "100", "ibgeId": "3304557", "uf": "RJ", "tseName": "RIO DE JANEIRO"},
            {"tseCode": "101", "ibgeId": "3550308", "uf": "SP", "tseName": "SAO PAULO"},
            {"tseCode": "102", "ibgeId": "3304557", "uf": "SP", "tseName": "RIO DE JANEIRO"},
        ]
        by_tse, by_ibge, invalid = cities._valid_tse_crosswalk(municipalities, rows)
        self.assertEqual(set(by_tse), {"97012"})
        self.assertEqual(set(by_ibge), {"5300108"})
        self.assertEqual(invalid, {"100", "ibge:3550308", "102"})

    def test_vote_totals_use_winners_and_keep_ties_without_zero_rows(self):
        municipalities = [{"id": "3550308", "name": "São Paulo", "uf": "SP"}]
        tse_by_code = {"100": {"tseCode": "100", "ibgeId": "3550308", "uf": "SP"}}
        candidates = {
            identifier: {
                "id": identifier, "name": f"Candidate {identifier}", "ballotName": f"Ballot {identifier}",
                "office": "DEPUTADO FEDERAL", "party": "AAA", "uf": "SP", "year": 2026,
                "round": 1, "result": "ELEITO POR QP", "sourceDate": "2026-10-07",
            }
            for identifier in ("1", "2", "3", "4")
        }
        candidates["4"]["uf"] = "RJ"
        rows = [
            vote_row("1", 300), vote_row("1", 200), vote_row("2", 500), vote_row("3", 400),
            vote_row("4", 300), vote_row("unknown", 250), vote_row("loser", 225),
            vote_row("1", 900, turn="2"), vote_row("1", 0),
        ]
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "votes.zip"
            archive_path.write_bytes(vote_archive(rows).getvalue())
            with patch.object(cities, "TOP_VOTE_LIMIT", 1):
                result, coverage = cities._parse_vote_archive(
                    archive_path,
                    municipalities,
                    tse_by_code,
                    candidates,
                    {"1", "2", "3", "4", "loser"},
                )
        self.assertEqual([row["id"] for row in result["3550308"]], ["1", "2"])
        self.assertEqual([row["votes"] for row in result["3550308"]], [500, 500])
        self.assertEqual(coverage["unknownVoteCandidates"], 1)
        self.assertEqual(coverage["nonElectedVoteCandidates"], 1)
        self.assertEqual(coverage["voteCandidateStateMismatches"], 1)
        self.assertEqual(coverage["voteRowsWithoutValidTotal"], 0)

    def test_invalid_vote_zone_suppresses_partial_candidate_total(self):
        municipalities = [{"id": "3550308", "name": "São Paulo", "uf": "SP"}]
        tse_by_code = {"100": {"tseCode": "100", "ibgeId": "3550308", "uf": "SP"}}
        candidate = {
            "id": "1", "name": "Candidate", "ballotName": "Candidate", "office": "DEPUTADO FEDERAL",
            "party": "AAA", "uf": "SP", "year": 2026, "round": 1, "result": "ELEITO", "sourceDate": None,
        }
        rows = [vote_row("1", 20), vote_row("1", "")]
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "votes.zip"
            archive_path.write_bytes(vote_archive(rows).getvalue())
            result, coverage = cities._parse_vote_archive(archive_path, municipalities, tse_by_code, {"1": candidate}, {"1"})
        self.assertEqual(result, {})
        self.assertEqual(coverage["voteRowsWithoutValidTotal"], 1)

    def test_offline_snapshot_does_not_fetch_and_missing_population_stays_null(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            where = cities.paths(root)
            where["municipalities"].parent.mkdir(parents=True)
            payload = [
                {"id": 5300108, "nome": "Brasília", "microrregiao": {"mesorregiao": {"UF": {"sigla": "DF"}}}},
                {"id": 5101837, "nome": "Boa Esperança do Norte", "microrregiao": {"mesorregiao": {"UF": {"sigla": "MT"}}}},
            ]
            where["municipalities"].write_text(json.dumps(payload), encoding="utf-8")
            where["population"].write_text(json.dumps([
                {"resultados": [{"series": [
                    {"localidade": {"id": "5300108"}, "serie": {"2026": "3094325"}},
                ]}]}
            ]), encoding="utf-8")
            where["crosswalk"].parent.mkdir(parents=True, exist_ok=True)
            where["crosswalk"].write_text(json.dumps([
                {"tseCode": "97012", "ibgeId": "5300108", "uf": "DF", "tseName": "BRASILIA"},
            ]), encoding="utf-8")
            with patch.object(cities, "_fetch_sources", side_effect=AssertionError("offline build attempted network")):
                snapshot = cities.build_snapshot(root)
        by_id = {row["id"]: row for row in snapshot["municipalities"]}
        self.assertEqual(len(snapshot["municipalities"]), 2)
        self.assertEqual(by_id["5300108"]["population"], 3094325)
        self.assertIsNone(by_id["5101837"]["population"])
        self.assertIsNone(by_id["5101837"]["populationYear"])
        self.assertIsNone(by_id["5101837"]["tseCode"])
        self.assertEqual(snapshot["sources"]["municipalities"]["status"], "cached")
        self.assertEqual(snapshot["sources"]["votes"]["status"], "unavailable")

    def test_source_period_normalizes_legacy_current_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "municipalities.json"
            meta = Path(temp) / "municipalities.meta.json"
            cache.write_text("[]", encoding="utf-8")
            meta.write_text(json.dumps({"period": "current", "status": "available"}), encoding="utf-8")
            source = cities._source(
                "IBGE municipalities", "https://example.test", "cadastro vigente na consulta",
                cache, meta, {}, "municipalities",
            )
        self.assertEqual(source["period"], "cadastro vigente na consulta")

    def test_invalid_ibge_refresh_preserves_existing_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "municipalities.json"
            destination.write_text('[{"preserved":true}]')
            class Response(io.BytesIO):
                headers = {}
            with patch.object(cities, "_request", return_value=Response(b"[]")):
                with self.assertRaises(ValueError):
                    cities._fetch_json("https://example.test", destination)
            self.assertEqual(destination.read_text(), '[{"preserved":true}]')

    def test_population_failure_does_not_downgrade_newer_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            where = cities.paths(Path(temp))
            where["population_meta"].parent.mkdir(parents=True)
            where["population_meta"].write_text(json.dumps({"period": 2026}))
            with patch.object(cities, "_fetch_json", side_effect=OSError("unavailable")) as request:
                with self.assertRaises(OSError):
                    cities._fetch_population(where)
            self.assertEqual(request.call_count, 1)
            self.assertIn("2026", request.call_args.args[0])

    def test_missing_cache_does_not_erase_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            where = cities.paths(root)
            where["output"].parent.mkdir(parents=True)
            original = json.dumps({"municipalities": [{"id": "3550308", "name": "São Paulo"}]})
            where["output"].write_text(original)
            with self.assertRaisesRegex(RuntimeError, "Refusing to replace"):
                cities.build_snapshot(root)
            self.assertEqual(where["output"].read_text(), original)

    def test_empty_offline_build_writes_an_empty_snapshot_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(cities, "_fetch_sources", side_effect=AssertionError("offline build attempted network")):
                snapshot = cities.build_snapshot(Path(temp))
            self.assertEqual(snapshot["municipalities"], [])
            self.assertEqual(snapshot["sources"]["municipalities"]["status"], "unavailable")
            self.assertEqual(snapshot["coverage"]["populationAvailable"], 0)


if __name__ == "__main__":
    unittest.main()
