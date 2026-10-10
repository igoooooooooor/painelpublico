import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from ingest import chamber_votes
from ingest.chamber_vote_inventory import API_BASE, CollectionError


THROUGH = "2026-10-09"
VOTE_ID = "123-1"
ROLL_CALL_URL = "https://www.camara.leg.br/votacoes/123-1/relatorio"
DESCRIPTION = (
    "Aprovado o Projeto de Lei nº 1, de 2026. "
    "Sim: 2; Não: 1; Total: 3."
)


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def target(proposition_type="PL", identifier=42):
    return {"id": identifier, "siglaTipo": proposition_type, "numero": 1, "ano": 2026}


def participant(identifier, choice, *, name=None, party="ABC", state="SP"):
    return {
        "deputado_": {
            "id": identifier,
            "nome": name or f"Deputado {identifier}",
            "siglaPartido": party,
            "siglaUf": state,
        },
        "tipoVoto": choice,
    }


def detail(*, identifier=VOTE_ID, proposition_type="PL", targets=None, description=DESCRIPTION):
    return {
        "id": identifier,
        "data": THROUGH,
        "siglaOrgao": "PLEN",
        "descricao": description,
        "aprovacao": 1,
        "proposicoesAfetadas": targets if targets is not None else [target(proposition_type)],
    }


def inventory(*, identifier=VOTE_ID, proposition_type="PL"):
    return {
        "listComplete": True,
        "period": {"start": "2026-01-01", "end": THROUGH},
        "voteCount": 1,
        "candidateCount": 1,
        "entries": [{"id": identifier, "date": THROUGH, "candidate": True}],
    }


def review(*, identifier=VOTE_ID, proposition_id=42):
    return {
        "id": identifier,
        "status": "confirmed",
        "reviewedAt": "2026-10-09T12:00:00Z",
        "title": "Projeto de Lei 1/2026",
        "summary": "A Câmara aprovou o texto principal da proposta.",
        "decisionLabel": "Aprovado",
        "yesMeaning": "A favor do texto",
        "noMeaning": "Contra o texto",
        "evidence": {"method": "conferência", "object": "texto principal", "text": "Resultado nominal"},
        "sources": {
            "rollCall": ROLL_CALL_URL,
            "text": None,
            "decision": "https://www.camara.leg.br/atividade-legislativa/plenario",
            "proposition": (
                "https://www.camara.leg.br/proposicoesWeb/fichadetramitacao"
                f"?idProposicao={proposition_id}"
            ),
        },
    }


def roll_call_html(*, day="09/10/2026", number=1, choices=("Sim", "Sim", "Não")):
    rows = "".join(f"<tr><td>Deputado {index}</td><td>SP</td><td>{choice}</td></tr>"
                   for index, choice in enumerate(choices, 1))
    return (f"<p>SESSÃO EXTRAORDINÁRIA Nº 1 - {day}</p>"
            f"<p>Abertura da sessão: {day} 11:00<br>Encerramento da sessão: {day} 13:00</p>"
            f"<p>Proposição: PL Nº {number}/2026 - SUBEMENDA SUBSTITUTIVA - Nominal Eletrônica</p>"
            f"<p>Início da votação: {day} 12:00<br>Encerramento da votação: {day} 12:10</p>"
            '<div id="listaVotacao"><table><tr><th>Sim:</th><td>2</td></tr>'
            '<tr><th>Não:</th><td>1</td></tr><tr><th>Total da Votação:</th><td>3</td></tr></table></div>'
            '<div id="listagem"><table><thead><tr><th>Parlamentar</th><th>UF</th><th>Voto</th></tr></thead>'
            f'<tbody><tr><th colspan="3">ABC</th></tr>{rows}'
            f'<tr><td colspan="3">Total ABC: {len(choices)}</td></tr></tbody></table></div>').encode("utf-8")


class FakeChamberAPI:
    """Small offline fixture for the API and HTML routes used by the builder."""

    def __init__(self, *, vote_detail=None, participant_pages=None, themes=None, report=None):
        self.vote_detail = vote_detail or detail()
        self.participant_pages = participant_pages or {
            1: {"dados": [participant(1, "Sim"), participant(2, "Sim")], "links": [
                {"rel": "next", "href": "?pagina=2"},
                {"rel": "last", "href": "?pagina=2"},
            ]},
            2: {"dados": [participant(3, "Não"), participant(4, "Artigo 17")], "links": [
                {"rel": "last", "href": "?pagina=2"},
            ]},
        }
        self.themes = themes or [
            {"codTema": 10, "tema": "Educação"},
            {"codTema": 20, "tema": "Orçamento"},
        ]
        self.report = report or "<html><p>Votação nominal eletrônica</p></html>".encode("utf-8")
        self.fail_report = False
        self.propositions = {}
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if url == ROLL_CALL_URL:
            if self.fail_report:
                raise OSError("fonte nominal indisponível")
            return self.report
        if parsed.path == f"/api/v2/votacoes/{VOTE_ID}":
            return encoded({"dados": self.vote_detail, "links": []})
        if parsed.path == f"/api/v2/votacoes/{VOTE_ID}/votos":
            page = int(query.get("pagina", ["1"])[0])
            return encoded(self.participant_pages[page])
        if parsed.path.startswith("/api/v2/proposicoes/") and parsed.path.endswith("/temas"):
            return encoded({"dados": self.themes, "links": []})
        if parsed.path.startswith("/api/v2/proposicoes/"):
            identifier = int(parsed.path.rsplit("/", 1)[1])
            return encoded({"dados": self.propositions[identifier], "links": []})
        if parsed.path == "/api/v2/deputados":
            return encoded({"dados": [participant(i, "Sim")["deputado_"] for i in (1, 2, 3)], "links": []})
        raise AssertionError(f"Consulta inesperada: {url}")


class ChamberVotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.api = FakeChamberAPI()

    def tearDown(self):
        self.temp.cleanup()

    def build(self, reviews=None, *, root=None, api=None, collect=True, refresh=False,
              vote_inventory=None):
        return chamber_votes.build_catalogue(
            vote_inventory or inventory(),
            [review()] if reviews is None else reviews,
            root=root or self.root,
            collect=collect,
            refresh=refresh,
            request=api or self.api,
        )

    def test_requires_complete_inventory_and_rejects_duplicate_review_ids(self):
        incomplete = inventory()
        incomplete["listComplete"] = False
        with self.assertRaisesRegex(CollectionError, "inventário completo"):
            self.build(vote_inventory=incomplete)

        pending = {"id": VOTE_ID, "status": "pending", "reason": "Conferir o objeto."}
        with self.assertRaisesRegex(CollectionError, "ID duplicado"):
            self.build([pending, pending])

    def test_pending_review_requires_reason_and_is_not_published(self):
        with self.assertRaisesRegex(CollectionError, "pendência sem motivo"):
            self.build([{"id": VOTE_ID, "status": "pending"}])

        snapshot, details = self.build([{
            "id": VOTE_ID, "status": "pending", "reason": "Aguardando conferência do resultado.",
        }])

        self.assertEqual(snapshot["items"], [])
        self.assertEqual(snapshot["coverage"]["publishedCount"], 0)
        self.assertEqual(snapshot["coverage"]["pendingCount"], 1)
        self.assertEqual(details, {})
        self.assertEqual(self.api.calls, [])

    def test_confirmed_review_needs_evidence_and_official_chamber_sources(self):
        incomplete = review()
        incomplete.pop("evidence")
        with self.assertRaisesRegex(CollectionError, "revisão incompleta"):
            self.build([incomplete])

        unsafe = review()
        unsafe["sources"]["decision"] = "https://example.org/decision"
        with self.assertRaisesRegex(CollectionError, "link oficial da Câmara"):
            self.build([unsafe])

    def test_excluded_candidates_require_an_auditable_review_and_are_not_pending(self):
        excluded = {
            "id": VOTE_ID, "status": "excluded", "reviewedAt": THROUGH,
            "reason": "Decisão simbólica, fora do recorte nominal.",
            "sources": {"decision": "https://www.camara.leg.br/atividade-legislativa/plenario"},
            "evidence": {"method": "O registro da sessão identifica votação simbólica."},
        }
        snapshot, details = self.build([excluded])
        self.assertEqual(snapshot["items"], [])
        self.assertEqual(details, {})
        self.assertEqual(snapshot["coverage"]["reviewedCount"], 1)
        self.assertEqual(snapshot["coverage"]["excludedCount"], 1)
        self.assertEqual(snapshot["coverage"]["pendingCount"], 0)
        self.assertEqual(self.api.calls, [])

        for field in ("reason", "reviewedAt", "sources", "evidence"):
            invalid = {key: value for key, value in excluded.items() if key != field}
            with self.subTest(field=field), self.assertRaisesRegex(CollectionError, "exclusão sem"):
                self.build([invalid])
        excluded["sources"]["decision"] = "https://example.org/report"
        with self.assertRaisesRegex(CollectionError, "link oficial da Câmara"):
            self.build([excluded])

    def test_coverage_separates_published_excluded_and_unresolved_candidates(self):
        vote_inventory = inventory()
        vote_inventory["candidateCount"] = 4
        vote_inventory["voteCount"] = 4
        vote_inventory["entries"].extend([
            {"id": "123-2", "date": THROUGH, "candidate": True},
            {"id": "123-3", "date": THROUGH, "candidate": True},
            {"id": "123-4", "date": THROUGH, "candidate": True},
        ])
        excluded = {
            "id": "123-2", "status": "excluded", "reviewedAt": THROUGH,
            "reason": "Votação simbólica.", "sources": {"decision": ROLL_CALL_URL},
            "evidence": {"method": "Simbólica no registro da sessão."},
        }
        pending = {"id": "123-3", "status": "pending", "reason": "Método sem confirmação."}
        snapshot, _ = self.build([review(), excluded, pending], vote_inventory=vote_inventory)
        coverage = snapshot["coverage"]
        self.assertEqual(coverage["publishedCount"], 1)
        self.assertEqual(coverage["excludedCount"], 1)
        self.assertEqual(coverage["pendingCount"], 2)
        self.assertEqual(coverage["reviewedCount"], 3)

    def test_confirmed_main_decisions_for_pl_plp_and_pec_build_a_summary_and_separate_detail(self):
        for proposition_type in ("PL", "PLP", "PEC"):
            with self.subTest(proposition_type=proposition_type):
                root = self.root / proposition_type
                proposition_id = {"PL": 42, "PLP": 43, "PEC": 44}[proposition_type]
                api = FakeChamberAPI(vote_detail=detail(
                    proposition_type=proposition_type,
                    targets=[target(proposition_type, proposition_id)],
                ))
                snapshot, details = self.build(
                    [review(proposition_id=proposition_id)],
                    root=root,
                    api=api,
                )

                self.assertEqual(snapshot["items"][0]["type"], proposition_type)
                self.assertEqual(snapshot["items"][0]["proposition"], f"{proposition_type} 1/2026")
                self.assertEqual([theme["label"] for theme in snapshot["items"][0]["themes"]],
                                 ["Educação", "Orçamento"])
                self.assertNotIn("participants", snapshot["items"][0])
                self.assertNotIn("partyTotals", snapshot["items"][0])
                self.assertEqual(len(details[VOTE_ID]["participants"]), 4)
                self.assertTrue(any(url.endswith("/votacoes/123-1") for url in api.calls))
                self.assertTrue(any(url.endswith("/votacoes/123-1/votos?pagina=2") for url in api.calls))
                self.assertTrue(any(url.endswith(f"/proposicoes/{proposition_id}/temas")
                                    for url in api.calls))

                chamber_votes.write_catalogue(snapshot, details, root / "data" / "snapshots")
                index = json.loads((root / "data/snapshots/chamber-votes.json").read_text())
                details_version = snapshot["detailsVersion"]
                self.assertRegex(details_version, r"^[0-9a-f]{64}$")
                saved_detail = json.loads((root / f"data/snapshots/chamber-vote-details/{details_version}/{VOTE_ID}.json").read_text())
                self.assertEqual(index["detailsVersion"], details_version)
                self.assertNotIn("participants", index["items"][0])
                self.assertEqual(len(saved_detail["participants"]), 4)

    def test_rejects_multiple_affected_propositions_in_a_confirmed_decision(self):
        api = FakeChamberAPI(vote_detail=detail(targets=[target(), target("PEC", 77)]))
        with self.assertRaisesRegex(CollectionError, "não confirma decisão"):
            self.build(api=api)

    def test_nominal_html_detection_handles_entities_and_latin1(self):
        self.assertTrue(chamber_votes._nominal_report(
            b"<div>Vota&ccedil;&atilde;o nominal eletr&ocirc;nica</div>"))
        self.assertTrue(chamber_votes._nominal_report(
            "<p>Votação nominal eletrônica</p>".encode("latin-1")))

    def test_roll_call_cache_reuses_valid_metadata_and_rejects_tampering_offline(self):
        self.build()
        report_path = (self.root / "data/raw/chamber-vote-inventory"
                       / "2026-01-01_2026-10-09/reports/123-1.html")
        metadata_path = report_path.with_suffix(".meta.json")
        metadata = json.loads(metadata_path.read_text())
        self.assertEqual(metadata["sourceUrl"], ROLL_CALL_URL)
        self.assertEqual(metadata["sha256"], hashlib.sha256(report_path.read_bytes()).hexdigest())

        calls_before = len(self.api.calls)
        self.build(collect=False, api=lambda _: self.fail("cache offline tentou acessar a rede"))
        self.assertEqual(len(self.api.calls), calls_before)

        report_path.write_bytes(b"tampered report")
        with self.assertRaisesRegex(CollectionError, "fonte nominal ainda não coletada"):
            self.build(collect=False, api=lambda _: self.fail("cache adulterado tentou acessar a rede"))

    def test_reviewed_report_fills_missing_api_tally_and_empty_voters_with_source_notes(self):
        vote_detail = detail(description="Aprovada a Subemenda Substitutiva ao Projeto de Lei nº 1, de 2026.")
        vote_detail["dataHoraRegistro"] = f"{THROUGH}T12:10:20"
        api = FakeChamberAPI(vote_detail=vote_detail, report=roll_call_html(),
                             participant_pages={1: {"dados": [], "links": []}})
        reviewed = {**review(), "tallySource": "rollCall", "participantsSource": "rollCall",
                    "reportObject": "SUBEMENDA SUBSTITUTIVA"}
        snapshot, details = self.build([reviewed], api=api)
        item = snapshot["items"][0]
        self.assertEqual(item["tally"], {"yes": 2, "no": 1, "abstention": None, "total": 3})
        self.assertEqual(len(details[VOTE_ID]["participants"]), 3)
        self.assertEqual(details[VOTE_ID]["participants"][0]["id"], "camara:1")
        metadata = details[VOTE_ID]["sourceMetadata"]
        self.assertEqual(metadata["participantsOrigin"], "rollCall")
        self.assertTrue(metadata["identities"])
        self.assertEqual(len(item["dataNotes"]), 2)
        self.build([reviewed], collect=False, api=lambda _: self.fail("fallback offline tentou a rede"))

    def voted_build(self, voted, *, proposition_id, record=None, registered="12:10:20"):
        vote_detail = detail()
        vote_detail["dataHoraRegistro"] = f"{THROUGH}T{registered}"
        api = FakeChamberAPI(vote_detail=vote_detail, report=roll_call_html(number=7))
        if record:
            api.propositions[record["id"]] = record
        reviewed = {**review(proposition_id=proposition_id), "votedProposition": voted}
        return self.build([reviewed], api=api), api

    def test_voted_proposition_from_report_keeps_the_api_reference(self):
        (snapshot, _), api = self.voted_build(
            {"id": 77, "label": "PL 7/2026"}, proposition_id=77,
            record={"id": 77, "siglaTipo": "PL", "numero": 7, "ano": 2026})
        item = snapshot["items"][0]

        self.assertEqual((item["proposition"], item["type"]), ("PL 7/2026", "PL"))
        self.assertTrue(item["sources"]["proposition"].endswith("idProposicao=77"))
        self.assertTrue(item["sources"]["referenceProposition"].endswith("idProposicao=42"))
        self.assertEqual(item["sources"]["vote"], f"{API_BASE}/votacoes/{VOTE_ID}")
        self.assertIn("na proposição PL 1/2026", item["dataNotes"][0])
        self.assertTrue(any(url.endswith("/proposicoes/77/temas") for url in api.calls))

    def test_renumbered_proposition_uses_the_number_on_the_vote_date(self):
        (snapshot, _), _ = self.voted_build({"id": 42, "label": "PL 7/2026"}, proposition_id=42)
        item = snapshot["items"][0]

        self.assertEqual(item["proposition"], "PL 7/2026")
        self.assertNotIn("referenceProposition", item["sources"])
        self.assertIn("numeração atual PL 1/2026", item["dataNotes"][0])

    def test_voted_proposition_must_match_report_and_official_record(self):
        cases = (
            ({"id": 77, "label": "PL 8/2026"}, {"id": 77, "siglaTipo": "PL", "numero": 8, "ano": 2026},
             "relatório não corresponde"),
            ({"id": 77, "label": "PL 7/2026"}, {"id": 77, "siglaTipo": "PL", "numero": 9, "ano": 2026},
             "ficha oficial"),
            ({"id": 42, "label": "PL 1/2026"}, None, "igual à referência"),
            ({"id": 77, "label": "MPV 7/2026"}, None, "proposição votada inválida"),
        )
        for index, (voted, record, message) in enumerate(cases):
            with self.subTest(message=message):
                self.root = self.root / str(index)
                with self.assertRaisesRegex(CollectionError, message):
                    self.voted_build(voted, proposition_id=voted["id"], record=record)

    def test_report_fallback_accepts_registration_a_few_minutes_after_the_report(self):
        vote_detail = detail(description="Aprovada a Subemenda Substitutiva ao Projeto de Lei nº 1, de 2026.")
        reviewed = {**review(), "tallySource": "rollCall", "participantsSource": "rollCall",
                    "reportObject": "SUBEMENDA SUBSTITUTIVA"}
        for index, (registered, accepted) in enumerate((("12:13:40", True), ("12:16:00", False),
                                                        ("12:09:59", False))):
            with self.subTest(registered=registered):
                vote_detail["dataHoraRegistro"] = f"{THROUGH}T{registered}"
                api = FakeChamberAPI(vote_detail=dict(vote_detail), report=roll_call_html(),
                                     participant_pages={1: {"dados": [], "links": []}})
                build = lambda: self.build([reviewed], api=api, root=self.root / f"lag{index}")
                if accepted:
                    self.assertEqual(build()[0]["items"][0]["tally"]["yes"], 2)
                else:
                    with self.assertRaisesRegex(CollectionError, "horário"):
                        build()

    def test_report_tally_replaces_an_api_total_that_only_adds_obstructions(self):
        reviewed = {**review(), "tallySource": "rollCall", "reportObject": "SUBEMENDA SUBSTITUTIVA"}
        report = roll_call_html(choices=("Sim", "Sim", "Não", "Obstrução"))
        for index, (total, accepted) in enumerate(((4, True), (5, False))):
            with self.subTest(total=total):
                vote_detail = detail(description=f"Aprovado o Projeto de Lei nº 1, de 2026. Sim: 2; Não: 1; Total: {total}.")
                vote_detail["dataHoraRegistro"] = f"{THROUGH}T12:10:20"
                api = FakeChamberAPI(vote_detail=vote_detail, report=report, participant_pages={1: {"dados": [
                    participant(1, "Sim"), participant(2, "Sim"), participant(3, "Não"), participant(4, "Obstrução"),
                ], "links": []}})
                build = lambda: self.build([reviewed], api=api, root=self.root / f"obstruction{index}")
                if accepted:
                    item = build()[0]["items"][0]
                    self.assertEqual(item["tally"]["total"], 3)
                    self.assertIn("inclui 1 obstrução.", item["dataNotes"][0])
                else:
                    with self.assertRaisesRegex(CollectionError, "diverge do relatório"):
                        build()

    def test_report_tally_with_api_voters_does_not_need_the_registration_window(self):
        vote_detail = detail(description="Aprovado o Projeto de Lei nº 1, de 2026. Sim: 2; Total: 3.")
        vote_detail["dataHoraRegistro"] = f"{THROUGH}T12:40:00"
        api = FakeChamberAPI(vote_detail=vote_detail, report=roll_call_html(), participant_pages={1: {"dados": [
            participant(1, "Sim"), participant(2, "Sim"), participant(3, "Não")], "links": []}})
        reviewed = {**review(), "tallySource": "rollCall", "reportObject": "SUBEMENDA SUBSTITUTIVA"}
        item = self.build([reviewed], api=api)[0]["items"][0]
        self.assertEqual(item["tally"], {"yes": 2, "no": 1, "abstention": None, "total": 3})

    def test_report_fallback_requires_explicit_review_and_matching_decision(self):
        vote_detail = detail(description="Aprovada a Subemenda Substitutiva ao Projeto de Lei nº 1, de 2026.")
        vote_detail["dataHoraRegistro"] = f"{THROUGH}T12:10:20"
        api = FakeChamberAPI(vote_detail=vote_detail, report=roll_call_html(),
                             participant_pages={1: {"dados": [], "links": []}})
        with self.assertRaisesRegex(CollectionError, "placar nominal não conferido"):
            self.build(api=api)
        reviewed = {**review(), "tallySource": "rollCall", "participantsSource": "rollCall",
                    "reportObject": "SUBEMENDA SUBSTITUTIVA"}
        for changes in ({"reportObject": "DESTAQUE"}, {"tallySource": "other"}):
            with self.subTest(changes=changes), self.assertRaises(CollectionError):
                self.build([{**reviewed, **changes}], api=api)
        for report in (roll_call_html(day="08/10/2026"), roll_call_html(number=2)):
            api.report = report
            with self.assertRaisesRegex(CollectionError, "relatório não corresponde"):
                self.build([reviewed], api=api, refresh=True)

    def test_report_fallback_rejects_disagreement_with_available_api_counts(self):
        vote_detail = detail(description="Aprovada a Subemenda Substitutiva ao Projeto de Lei nº 1. "
                             "Sim: 3; Não: 0; Total: 3.")
        vote_detail["dataHoraRegistro"] = f"{THROUGH}T12:10:20"
        api = FakeChamberAPI(vote_detail=vote_detail, report=roll_call_html())
        reviewed = {**review(), "tallySource": "rollCall", "reportObject": "SUBEMENDA SUBSTITUTIVA"}
        with self.assertRaisesRegex(CollectionError, "placar da API diverge"):
            self.build([reviewed], api=api)

    def test_report_fallback_preserves_known_api_abstention_when_the_report_omits_it(self):
        vote_detail = detail(description=DESCRIPTION + " Abstenção: 0.")
        vote_detail["dataHoraRegistro"] = f"{THROUGH}T12:10:20"
        api = FakeChamberAPI(vote_detail=vote_detail, report=roll_call_html(),
                             participant_pages={1: {"dados": [], "links": []}})
        reviewed = {**review(), "tallySource": "rollCall", "participantsSource": "rollCall",
                    "reportObject": "SUBEMENDA SUBSTITUTIVA"}
        snapshot, _ = self.build([reviewed], api=api)
        self.assertEqual(snapshot["items"][0]["tally"]["abstention"], 0)
        vote_detail["descricao"] = "Aprovada a Subemenda Substitutiva ao Projeto. Não: 2."
        with self.assertRaisesRegex(CollectionError, "placar da API diverge"):
            self.build([reviewed], api=api, refresh=True)

    def test_failed_refresh_preserves_previous_roll_call_source_and_metadata(self):
        self.build()
        report_path = (self.root / "data/raw/chamber-vote-inventory"
                       / "2026-01-01_2026-10-09/reports/123-1.html")
        metadata_path = report_path.with_suffix(".meta.json")
        old_report, old_metadata = report_path.read_bytes(), metadata_path.read_bytes()
        self.api.fail_report = True

        with self.assertRaisesRegex(CollectionError, "saída anterior preservada"):
            self.build(refresh=True)

        self.assertEqual(report_path.read_bytes(), old_report)
        self.assertEqual(metadata_path.read_bytes(), old_metadata)

    def test_invalid_roll_call_refresh_and_semantically_invalid_cache_are_rejected(self):
        self.build()
        report_path = (self.root / "data/raw/chamber-vote-inventory"
                       / "2026-01-01_2026-10-09/reports/123-1.html")
        metadata_path = report_path.with_suffix(".meta.json")
        old_report, old_metadata = report_path.read_bytes(), metadata_path.read_bytes()
        self.api.report = b"<html><p>Votacao simbolica</p></html>"

        with self.assertRaisesRegex(CollectionError, "nominal|relatório"):
            self.build(refresh=True)

        self.assertEqual(report_path.read_bytes(), old_report)
        self.assertEqual(metadata_path.read_bytes(), old_metadata)

        # Even a matching checksum cannot make an HTML page with the wrong method
        # a trusted source for an offline catalogue build.
        report_path.write_bytes(self.api.report)
        metadata = json.loads(old_metadata)
        metadata["sha256"] = hashlib.sha256(self.api.report).hexdigest()
        metadata_path.write_bytes(json.dumps(metadata).encode("utf-8"))
        with self.assertRaisesRegex(CollectionError, "nominal|relatório"):
            self.build(collect=False, api=lambda _: self.fail("invalid cached report tried the network"))

    def test_failed_index_publish_keeps_previous_detail_generation_immutable(self):
        snapshot, details = self.build()
        output = self.root / "data/snapshots"
        chamber_votes.write_catalogue(snapshot, details, output)
        index_path = output / "chamber-votes.json"
        old_index = index_path.read_bytes()
        old_version = snapshot["detailsVersion"]
        old_detail_path = output / "chamber-vote-details" / old_version / f"{VOTE_ID}.json"
        old_detail = old_detail_path.read_bytes()

        self.api.participant_pages[1]["dados"][0]["deputado_"]["nome"] += " conferido"
        next_snapshot, next_details = self.build(refresh=True)
        self.assertNotEqual(next_snapshot["detailsVersion"], old_version)
        atomic_bytes = chamber_votes._atomic_bytes

        def fail_index(path, content):
            if Path(path) == index_path:
                raise OSError("falha simulada ao publicar índice")
            return atomic_bytes(path, content)

        with patch.object(chamber_votes, "_atomic_bytes", side_effect=fail_index):
            with self.assertRaisesRegex(OSError, "publicar índice"):
                chamber_votes.write_catalogue(next_snapshot, next_details, output)

        self.assertEqual(index_path.read_bytes(), old_index)
        self.assertEqual(old_detail_path.read_bytes(), old_detail)
        published_index = json.loads(index_path.read_text())
        self.assertEqual(published_index["detailsVersion"], old_version)
        self.assertEqual(len(json.loads(old_detail_path.read_text())["participants"]), 4)

    def test_presiding_participant_is_not_a_vote_or_part_of_total_and_missing_abstention_stays_unknown(self):
        snapshot, details = self.build()
        item = snapshot["items"][0]
        participants = details[VOTE_ID]["participants"]
        presider = next(person for person in participants if person["vote"] == "Presidiu")

        self.assertEqual(presider["id"], "camara:4")
        self.assertIsNone(item["tally"]["abstention"])
        self.assertEqual(item["tally"]["total"], 3)
        self.assertEqual(len(participants), 4)
        self.assertEqual(sum(total["yes"] + total["no"] + total["other"]
                             for total in details[VOTE_ID]["partyTotals"]), 4)

    def test_conflicting_unknown_and_mismatched_participant_votes_are_rejected(self):
        rows = [participant(1, "Sim"), participant(1, "Não")]
        with self.assertRaisesRegex(CollectionError, "duplicados conflitantes"):
            chamber_votes.normalize_participants(rows, {"yes": 1, "no": 1, "abstention": None, "total": 2})

        with self.assertRaisesRegex(CollectionError, "escolha reconhecida"):
            chamber_votes.normalize_participants(
                [participant(1, "Presente")], {"yes": 0, "no": 0, "abstention": None, "total": 0})

        with self.assertRaisesRegex(CollectionError, "Total do placar divergente"):
            chamber_votes.normalize_participants(
                [participant(1, "Sim"), participant(2, "Não")],
                {"yes": 1, "no": 1, "abstention": None, "total": 3},
            )

    def test_failed_cli_build_leaves_published_index_and_detail_untouched(self):
        reviews_dir = self.root / "data/reviews"
        reviews_dir.mkdir(parents=True)
        inventory_path = reviews_dir / f"chamber-vote-inventory-{THROUGH}.json"
        inventory_path.write_bytes(encoded(inventory()))
        reviews_path = reviews_dir / f"chamber-vote-reviews-{THROUGH}.json"
        reviews_path.write_bytes(encoded([review()]))
        snapshots = self.root / "data/snapshots"
        detail_path = snapshots / f"chamber-vote-details/{VOTE_ID}.json"
        index_path = snapshots / "chamber-votes.json"
        detail_path.parent.mkdir(parents=True)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        detail_path.write_bytes(b"previous detail\n")
        index_path.write_bytes(b"previous index\n")

        with self.assertRaises(SystemExit) as raised:
            chamber_votes.main([
                "--root", str(self.root), "--through", THROUGH,
                "--reviews", str(reviews_path),
            ])

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(detail_path.read_bytes(), b"previous detail\n")
        self.assertEqual(index_path.read_bytes(), b"previous index\n")

def yearly_part(start, end, identifier, *, published=1):
    coverage = {"inventoryCount": 10, "candidateCount": 3, "reviewedCount": 3, "publishedCount": published,
                "excludedCount": 3 - published, "pendingCount": 0, "missingTextCount": 0,
                "missingAbstentionCount": published, "missingThemeCount": 0, "detail": "ano"}
    items = [{"id": identifier, "date": start}] if published else []
    details = {identifier: {"id": identifier, "participants": []}} if published else {}
    return {"schemaVersion": 1, "period": {"start": start, "end": end},
            "coverage": coverage, "items": items}, details


class FollowedVersionTests(unittest.TestCase):
    def items(self):
        return [{'id': '1-1', 'proposition': 'PLP 1/2025', 'date': '2025-02-18', 'outcome': 'rejected',
                 'tally': {'yes': 34, 'no': 356, 'abstention': 1, 'total': 391}},
                {'id': '1-2', 'proposition': 'PLP 1/2025', 'date': '2025-02-18', 'outcome': 'approved',
                 'tally': {'yes': 407, 'no': 6, 'abstention': None, 'total': 413}}]

    def test_links_the_rejected_version_to_the_later_approval_both_ways(self):
        items = self.items()
        chamber_votes._link_followed_versions(items, {'1-1': '1-2'},
                                              {'1-1': '2025-02-18T19:49', '1-2': '2025-02-18T20:01'})
        self.assertEqual(items[0]['related']['id'], '1-2')
        self.assertEqual(items[0]['related']['relation'], 'approvedAfter')
        self.assertEqual(items[1]['related'], {'id': '1-1', 'relation': 'rejectedBefore', 'outcome': 'rejected',
                                               'tally': items[0]['tally']})

    def test_rejects_links_to_other_propositions_dates_order_or_outcomes(self):
        cases = (({'proposition': 'PLP 2/2025'}, {}), ({'date': '2025-02-19'}, {}), ({'outcome': 'rejected'}, {}),
                 ({}, {'1-2': '2025-02-18T19:00'}))
        for change, times in cases:
            with self.subTest(change=change, times=times):
                items = self.items(); items[1].update(change)
                with self.assertRaisesRegex(CollectionError, 'decisão seguinte'):
                    chamber_votes._link_followed_versions(
                        items, {'1-1': '1-2'}, {'1-1': '2025-02-18T19:49', '1-2': '2025-02-18T20:01', **times})


class MergeCatalogueTests(unittest.TestCase):
    def test_merges_contiguous_years_summing_coverage_and_keeping_details(self):
        snapshot, details = chamber_votes.merge_catalogues([
            yearly_part("2024-01-01", "2024-12-31", "2-1"),
            yearly_part("2023-02-01", "2023-12-31", "1-1"),
        ])

        self.assertEqual(snapshot["period"], {"start": "2023-02-01", "end": "2024-12-31"})
        self.assertEqual([item["id"] for item in snapshot["items"]], ["2-1", "1-1"])
        self.assertEqual(snapshot["coverage"]["inventoryCount"], 20)
        self.assertEqual(snapshot["coverage"]["excludedCount"], 4)
        self.assertEqual(snapshot["coverage"]["missingAbstentionCount"], 2)
        self.assertIn("Recorte de 2023 a 2024", snapshot["coverage"]["detail"])
        self.assertEqual(set(details), {"1-1", "2-1"})
        self.assertEqual(snapshot["detailsVersion"],
                         hashlib.sha256(chamber_votes._json_bytes(details)).hexdigest())

    def test_rejects_gaps_overlaps_and_repeated_decisions(self):
        cases = (
            ([yearly_part("2023-02-01", "2023-12-31", "1-1"), yearly_part("2025-01-01", "2025-12-31", "2-1")],
             "contíguos"),
            ([yearly_part("2023-02-01", "2023-10-09", "1-1"), yearly_part("2024-01-01", "2024-12-31", "2-1")],
             "contíguos"),
            ([yearly_part("2023-02-01", "2023-12-31", "1-1"), yearly_part("2024-01-01", "2024-12-31", "1-1")],
             "repetida"),
        )
        for parts, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(CollectionError, message):
                    chamber_votes.merge_catalogues(parts)

    def test_cli_rejects_alternative_review_with_several_years(self):
        with self.assertRaises(SystemExit) as raised:
            chamber_votes.main(["--through", "2024-12-31", "--through", "2025-12-31",
                                "--reviews", "revisao.json"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
