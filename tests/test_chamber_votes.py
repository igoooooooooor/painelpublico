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


if __name__ == "__main__":
    unittest.main()
