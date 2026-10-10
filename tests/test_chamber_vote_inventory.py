import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from ingest import chamber_vote_inventory as inventory


START = date(2026, 1, 1)
THROUGH = date(2026, 10, 9)
VOTE_DESCRIPTION = (
    "Aprovado o Projeto de Lei nº 1, de 2026. "
    "Sim: 2; Não: 1; Abstenção: 0; Total: 3."
)


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def vote(identifier="123-1", *, occurred="2026-09-03", description=VOTE_DESCRIPTION,
         chamber="PLEN"):
    return {
        "id": identifier,
        "data": occurred,
        "dataHoraRegistro": f"{occurred}T12:00:00",
        "siglaOrgao": chamber,
        "descricao": description,
        "aprovacao": 1,
    }


def detail(identifier="123-1", *, occurred="2026-09-03", description=VOTE_DESCRIPTION,
           opening_description=None):
    result = {
        "id": identifier,
        "data": occurred,
        "siglaOrgao": "PLEN",
        "descricao": description,
        "proposicoesAfetadas": [{"id": 1, "siglaTipo": "PL", "numero": 1, "ano": 2026}],
    }
    if opening_description is not None:
        result["descUltimaAberturaVotacao"] = opening_description
    return result


def participant(person_id, choice):
    return {"deputado_": {"id": person_id}, "tipoVoto": choice}


class FakeChamberAPI:
    """Deterministic, offline response fixture for official API routes."""

    def __init__(self):
        self.list_pages = {1: {"dados": [], "links": []}}
        self.details = {}
        self.participant_pages = {}
        self.audit_routes = {}
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/v2/orgaos/180/votacoes":
            page = int(query.get("pagina", ["1"])[0])
            return encoded(self.list_pages[page])
        if parsed.path.startswith("/api/v2/votacoes/"):
            tail = parsed.path.removeprefix("/api/v2/votacoes/")
            if tail.endswith("/votos"):
                identifier = tail.removesuffix("/votos")
                page = int(query.get("pagina", ["1"])[0])
                return encoded(self.participant_pages[identifier][page])
            return encoded({"dados": self.details[tail], "links": []})
        if parsed.path.startswith("/api/v2/eventos") or parsed.path.startswith("/api/v2/proposicoes/"):
            return encoded({"dados": self.audit_routes.get(parsed.path, []), "links": []})
        raise AssertionError(f"Consulta inesperada: {url}")


class ChamberVoteInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.api = FakeChamberAPI()

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, *, root=None, api=None, **options):
        request = options.pop("request", None)
        options.setdefault("collect", True)
        return inventory.collect_inventory(
            root=root or self.root,
            start=START,
            through=THROUGH,
            request=request or api or self.api,
            **options,
        )

    def set_list(self, *rows, links=None, page=1, api=None):
        (api or self.api).list_pages[page] = {"dados": list(rows), "links": links or []}

    def test_follows_relative_next_link_and_deduplicates_identical_vote_rows(self):
        first = vote("123-1")
        second = vote("124-1", occurred="2026-09-04")
        self.set_list(first, links=[
            {"rel": "next", "href": "?pagina=2"},
            {"rel": "last", "href": "?pagina=2"},
        ])
        self.set_list(second, first, page=2, links=[{"rel": "last", "href": "?pagina=2"}])

        result = self.collect(detail_limit=0)

        requested_pages = [parse_qs(urlsplit(url).query).get("pagina", ["1"])[0]
                           for url in self.api.calls]
        self.assertEqual(requested_pages, ["1", "2"])
        self.assertTrue(result["listComplete"])
        self.assertEqual(result["listPageCount"], 2)
        self.assertEqual(result["voteCount"], 2)
        self.assertEqual(result["duplicateCount"], 1)

    def test_missing_next_before_announced_last_page_is_incomplete(self):
        self.set_list(vote(), links=[{"rel": "last", "href": "?pagina=2"}])

        with self.assertRaisesRegex(inventory.CollectionError, "Falta a próxima página"):
            self.collect()

    def test_rejects_external_looping_and_jumped_pagination_links(self):
        cases = (
            ("https://example.com/api/v2/orgaos/180/votacoes?pagina=2", "endpoint oficial"),
            ("?pagina=1", "pulou ou repetiu"),
            ("?pagina=3", "pulou ou repetiu"),
        )
        for index, (href, message) in enumerate(cases):
            with self.subTest(href=href):
                api = FakeChamberAPI()
                api.list_pages[1] = {"dados": [vote()], "links": [{"rel": "next", "href": href}]}
                with self.assertRaisesRegex(inventory.CollectionError, message):
                    self.collect(root=self.root / str(index), api=api)

    def test_rejects_conflicting_duplicate_vote_records(self):
        self.set_list(vote(), {**vote(), "descricao": "Rejeitado o Projeto de Lei nº 1, de 2026."})

        with self.assertRaisesRegex(inventory.CollectionError, "duplicados conflitantes"):
            self.collect()

    def test_validates_plenary_scope_and_occurrence_period(self):
        cases = (
            (vote(chamber="CFT"), "fora do período ou do Plenário"),
            (vote(occurred="2025-12-31"), "fora do período ou do Plenário"),
        )
        for index, (row, message) in enumerate(cases):
            with self.subTest(row=row):
                api = FakeChamberAPI()
                api.list_pages[1] = {"dados": [row], "links": []}
                with self.assertRaisesRegex(inventory.CollectionError, message):
                    self.collect(root=self.root / str(index), api=api)

    def test_rejects_a_detail_that_does_not_match_its_list_record(self):
        self.set_list(vote())
        self.api.details["123-1"] = detail(occurred="2026-09-04")

        result = self.collect()

        self.assertFalse(result["entries"][0]["detailCollected"])
        self.assertIn("Detalhe não corresponde", result["entries"][0]["errors"][0])

    def test_offline_cache_reconstructs_inventory_and_checksum_rejects_tampering(self):
        self.set_list(vote())
        self.api.details["123-1"] = detail()
        self.api.participant_pages["123-1"] = {1: {"dados": [
            participant(1, "Sim"), participant(2, "Sim"), participant(3, "Não"),
        ], "links": []}}
        collected = self.collect(collect=True)

        offline = self.collect(collect=False, request=lambda _: self.fail("cache offline tentou acessar rede"))

        self.assertEqual(offline["entries"], collected["entries"])
        self.assertEqual(offline["voteCount"], collected["voteCount"])
        self.assertEqual(offline["detailCount"], collected["detailCount"])
        raw_list = (self.root / "data" / "raw" / "chamber-vote-inventory"
                    / f"{START}_{THROUGH}" / "list" / "page-1.json")
        raw_list.write_bytes(encoded({"dados": [], "links": []}))

        with self.assertRaisesRegex(inventory.CollectionError, "cache inválido"):
            self.collect(collect=False, request=lambda _: self.fail("cache inválido tentou acessar rede"))

    def test_refresh_failure_does_not_replace_previous_hashed_cache_or_claim_inventory(self):
        self.set_list(vote())
        self.api.details["123-1"] = detail()
        self.api.participant_pages["123-1"] = {1: {"dados": [
            participant(1, "Sim"), participant(2, "Sim"), participant(3, "Não"),
        ], "links": []}}
        self.collect(collect=True)
        raw_list = (self.root / "data" / "raw" / "chamber-vote-inventory"
                    / f"{START}_{THROUGH}" / "list" / "page-1.json")
        metadata = raw_list.with_suffix(".meta.json")
        prior_payload, prior_metadata = raw_list.read_bytes(), metadata.read_bytes()

        def failed_request(_):
            raise OSError("fonte indisponível")

        with self.assertRaises(inventory.CollectionError):
            self.collect(collect=True, refresh=True, request=failed_request)

        self.assertEqual(raw_list.read_bytes(), prior_payload)
        self.assertEqual(metadata.read_bytes(), prior_metadata)

    def test_audits_paginated_participants_deduplicates_people_and_matches_each_tally(self):
        description = (
            "Aprovado o Projeto de Lei nº 1, de 2026. "
            "Sim: 2; Não: 1; Abstenção: 1; Total: 4."
        )
        self.set_list(vote(description=description))
        self.api.details["123-1"] = detail(description=description)
        self.api.participant_pages["123-1"] = {
            1: {"dados": [participant(1, "Sim"), participant(2, "Sim")], "links": [
                {"rel": "next", "href": "?pagina=2"},
                {"rel": "last", "href": "?pagina=2"},
            ]},
            2: {"dados": [participant(1, "Sim"), participant(3, "Não"),
                           participant(4, "Abstenção")], "links": [
                {"rel": "last", "href": "?pagina=2"},
            ]},
        }

        result = self.collect(collect=True)
        audit = result["entries"][0]["participants"]

        participant_pages = [parse_qs(urlsplit(url).query).get("pagina", ["1"])[0]
                             for url in self.api.calls if urlsplit(url).path.endswith("/votos")]
        self.assertEqual(participant_pages, ["1", "2"])
        self.assertEqual(audit["recordCount"], 5)
        self.assertEqual(audit["personCount"], 4)
        self.assertEqual(audit["duplicateCount"], 1)
        self.assertEqual(audit["choices"], {"Abstenção": 1, "Não": 1, "Sim": 2})
        self.assertEqual(audit["tallyChecks"], {"yes": True, "no": True, "abstention": True})
        self.assertTrue(audit["consistent"])

    def test_conflicting_participant_votes_are_reported_without_a_consistent_audit(self):
        self.set_list(vote())
        self.api.details["123-1"] = detail()
        self.api.participant_pages["123-1"] = {1: {"dados": [
            participant(7, "Sim"), participant(7, "Não"),
        ], "links": []}}

        result = self.collect(collect=True)
        entry = result["entries"][0]

        self.assertIsNone(entry["participants"])
        self.assertTrue(any("votos conflitantes" in error for error in entry["errors"]))

    def test_detail_and_participant_limits_are_reported_as_attempted_work(self):
        rows = [vote(f"{identifier}-1", description=(
            f"Aprovado o Projeto de Lei nº {identifier}, de 2026."
        )) for identifier in (123, 124, 125)]
        self.set_list(*rows)
        for row in rows:
            self.api.details[row["id"]] = detail(row["id"], description=row["descricao"])
            self.api.participant_pages[row["id"]] = {1: {"dados": [], "links": []}}

        result = self.collect(collect=True, detail_limit=3, participant_limit=1)

        self.assertEqual(result["detailLimit"], 3)
        self.assertEqual(result["detailAttemptCount"], 3)
        self.assertEqual(result["detailCount"], 3)
        self.assertEqual(result["participantLimit"], 1)
        self.assertEqual(result["participantAttemptCount"], 1)
        self.assertEqual(result["participantAuditCount"], 1)

        bounded_api = FakeChamberAPI()
        bounded_api.list_pages[1] = {"dados": rows, "links": []}
        bounded_api.details["125-1"] = detail("125-1", description=rows[-1]["descricao"])
        bounded = self.collect(root=self.root / "bounded", api=bounded_api, detail_limit=1,
                               participant_limit=0, collect=True)
        self.assertEqual(bounded["detailLimit"], 1)
        self.assertEqual(bounded["detailAttemptCount"], 1)
        self.assertEqual(bounded["detailCount"], 1)
        self.assertEqual(bounded["participantLimit"], 0)
        self.assertEqual(bounded["participantAttemptCount"], 0)

    def test_unknown_details_are_opt_in_bounded_and_do_not_promote_vague_results(self):
        rows = [vote(f"{identifier}-1", description="Aprovada a matéria.") for identifier in (123, 124)]
        self.set_list(*rows)
        for row in rows:
            self.api.details[row["id"]] = detail(row["id"], description=row["descricao"])

        initial = self.collect(participant_limit=0)
        self.assertEqual(initial["detailAttemptCount"], 0)
        self.assertFalse(initial["auditUnknown"])

        audited = self.collect(audit_unknown=True, detail_limit=1, participant_limit=0)
        self.assertEqual(audited["detailAttemptCount"], 1)
        self.assertEqual(audited["detailCount"], 1)
        self.assertTrue(audited["auditUnknown"])
        self.assertEqual(audited["candidateCount"], 0)
        self.assertTrue(all(entry["category"] == "unknown" for entry in audited["entries"]))
        self.assertFalse(any(url.endswith("/votos") for url in self.api.calls))

    def test_report_keeps_candidate_provisional_and_does_not_infer_nominal_method(self):
        self.set_list(vote())
        self.api.details["123-1"] = detail()
        self.api.participant_pages["123-1"] = {1: {"dados": [
            participant(1, "Sim"), participant(2, "Sim"), participant(3, "Não"),
        ], "links": []}}

        result = self.collect(collect=True)
        entry = result["entries"][0]
        report = inventory.render_report(result)

        self.assertTrue(entry["candidate"])
        self.assertTrue(entry["participants"]["consistent"])
        self.assertEqual(entry["method"], "unknown")
        self.assertIn("Candidato não significa votação elegível", report)
        self.assertIn("O método fica desconhecido quando a fonte não o declara explicitamente", report)
        self.assertIn("| main_text | sim | unknown |", report)

    def test_type_guard_flags_missing_types_and_pec_turns_outside_candidates(self):
        self.set_list(vote(), vote("124-1", description="Aprovada a Emenda à PEC nº 9, de 2026, em primeiro turno."),
                      vote("125-1", description="Aprovado o Requerimento de quebra de interstício para o "
                                                "segundo turno da PEC nº 9, de 2026."))
        self.api.details["123-1"] = detail()

        result = self.collect(participant_limit=0)
        report = inventory.render_report(result)

        self.assertEqual(result["typeGuard"]["candidateTypes"], {"PL": 1, "PLP": 0, "PEC": 0})
        self.assertEqual(result["typeGuard"]["pecTurnsNotCandidates"], ["124-1"])
        self.assertIn("nenhum candidato PEC", report)
        self.assertIn("Turnos de PEC fora dos candidatos", report)

    def test_main_failure_preserves_preexisting_report_outputs(self):
        output = self.root / "data" / "reviews" / f"chamber-vote-inventory-{THROUGH}.json"
        markdown = output.with_suffix(".md")
        output.parent.mkdir(parents=True)
        output.write_bytes(b"previous json report\n")
        markdown.write_bytes(b"previous markdown report\n")

        with patch.object(inventory, "collect_inventory", side_effect=inventory.CollectionError("sem cache")):
            with self.assertRaises(SystemExit) as raised:
                inventory.main(["--root", str(self.root), "--year", "2026", "--through", THROUGH.isoformat()])

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(output.read_bytes(), b"previous json report\n")
        self.assertEqual(markdown.read_bytes(), b"previous markdown report\n")

    def omission_api(self):
        self.set_list(vote(), vote("124-1", occurred="2026-09-04",
                                   description="Aprovado o requerimento."))
        self.api.details["123-1"] = detail()
        self.api.audit_routes.update({
            "/api/v2/eventos": [
                {"id": 10, "descricaoTipo": "Sessão Deliberativa", "dataHoraInicio": "2026-09-03T14:00"},
                {"id": 11, "descricaoTipo": "Sessão Deliberativa Extraordinária",
                 "dataHoraInicio": "2026-09-05T14:00"},
                {"id": 12, "descricaoTipo": "Sessão Não Deliberativa Solene",
                 "dataHoraInicio": "2026-09-06T10:00"},
            ],
            "/api/v2/eventos/10/votacoes": [vote()],
            "/api/v2/eventos/10/pauta": [{"proposicao_": {"id": 7}}],
            "/api/v2/proposicoes/7/votacoes": [
                vote("7-9", occurred="2026-09-05", description="Aprovado o PL 7."),
                vote("7-8", occurred="2025-12-01"),
                vote("7-7", chamber="CFT"),
            ],
        })

    def test_omission_audit_reports_votes_missing_from_the_list_without_claiming_completeness(self):
        self.omission_api()

        result = self.collect(participant_limit=0, audit_omissions=True)
        audit = result["omissionAudit"]

        self.assertEqual([row["id"] for row in audit["missing"]], ["7-9"])
        self.assertEqual(audit["missing"][0]["origins"], ["proposição 7"])
        self.assertEqual((audit["eventCount"], audit["deliberativeEventCount"]), (3, 2))
        self.assertEqual(audit["eventVoteCount"], 1)
        self.assertEqual(audit["listOnlyCount"], 1)
        self.assertEqual(audit["propositionCount"], 2)
        self.assertEqual(audit["deliberativeWithoutListedVotes"], [{"id": "11", "start": "2026-09-05T14:00"}])
        self.assertTrue(audit["complete"])
        self.assertIn("não prova", audit["limitation"])
        self.assertIn("Votações ausentes da lista: 1.", inventory.render_report(result))
        self.assertEqual(result["voteCount"], 2)

    def test_omission_audit_is_opt_in_and_records_missing_caches_as_incomplete(self):
        self.omission_api()
        plain = self.collect(participant_limit=0)
        self.assertNotIn("omissionAudit", plain)
        self.assertFalse(any("/eventos" in url for url in self.api.calls))

        offline = self.collect(participant_limit=0, audit_omissions=True, collect=False,
                               request=lambda _: self.fail("cache offline tentou acessar rede"))
        self.assertFalse(offline["omissionAudit"]["complete"])
        self.assertEqual(offline["omissionAudit"]["missing"], [])

    def test_cli_defaults_previous_year_through_december_and_validates_start(self):
        with patch.object(inventory, "collect_inventory", side_effect=inventory.CollectionError("x")) as collect:
            with self.assertRaises(SystemExit):
                inventory.main(["--root", str(self.root), "--year", "2023", "--start", "2023-02-01"])
        self.assertEqual(collect.call_args.kwargs["start"], date(2023, 2, 1))
        self.assertEqual(collect.call_args.kwargs["through"], date(2023, 12, 31))
        with self.assertRaises(SystemExit) as raised:
            inventory.main(["--root", str(self.root), "--year", "2023", "--start", "2024-01-01"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
