import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from ingest import chamber_votes
from ingest.chamber_vote_inventory import CollectionError
from ingest.chamber_vote_urgencies import build_urgencies, cites
from test_chamber_votes import THROUGH, VOTE_ID, FakeChamberAPI, encoded, inventory, participant, review, target

URGENCY_ID = "555-3"
URGENCY_ROLL_CALL = "https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?ideVotacao=98"
OBJECT = "URGÊNCIA PARA APRECIAÇÃO DO PL Nº 1/2026"
REQUEST_FICHA = "https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=555"
PROJECT_FICHA = "https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=42"


def urgency_report(*, obj=OBJECT, request="REQ Nº 10/2026", yes=1, no=2, day="09/10/2026"):
    rows = "".join(f"<tr><td>Deputado {index}</td><td>SP</td><td>{choice}</td></tr>"
                   for index, choice in enumerate(["Sim"] * yes + ["Não"] * no, 1))
    return (f"<p>SESSÃO EXTRAORDINÁRIA Nº 1 - {day}</p>"
            f"<p>Abertura da sessão: {day} 09:00<br>Encerramento da sessão: {day} 13:00</p>"
            f"<p>Proposição: {request} - {obj} - Nominal Eletrônica</p>"
            f"<p>Início da votação: {day} 10:20<br>Encerramento da votação: {day} 10:30</p>"
            f'<div id="listaVotacao"><table><tr><th>Sim:</th><td>{yes}</td></tr>'
            f'<tr><th>Não:</th><td>{no}</td></tr><tr><th>Total da Votação:</th><td>{yes + no}</td></tr></table></div>'
            '<div id="listagem"><table><thead><tr><th>Parlamentar</th><th>UF</th><th>Voto</th></tr></thead>'
            f'<tbody><tr><th colspan="3">ABC</th></tr>{rows}'
            f'<tr><td colspan="3">Total ABC: {yes + no}</td></tr></tbody></table></div>').encode("utf-8")


def urgency_review(**changes):
    return {
        "id": URGENCY_ID, "parentId": VOTE_ID, "status": "confirmed", "reviewedAt": "2026-10-12",
        "request": {"label": "REQ 10/2026"},
        "title": "Urgência para o PL 1/2026", "summary": "O REQ 10/2026 pediu urgência para o PL 1/2026.",
        "decisionLabel": "Urgência rejeitada",
        "yesMeaning": "Aprovar o pedido para acelerar a tramitação. Esse voto não aprova o conteúdo do projeto.",
        "noMeaning": "Rejeitar o pedido de urgência.", "outcome": "rejected", "reportObject": OBJECT,
        "sources": {"rollCall": URGENCY_ROLL_CALL, "request": REQUEST_FICHA, "proposition": PROJECT_FICHA},
        "evidence": {"method": "relatório nominal", "object": "REQ 10/2026", "text": "ementa do requerimento"},
        **changes,
    }


class UrgencyAPI(FakeChamberAPI):
    """Adds an urgency request voted before the main text to the offline API fixture."""

    def __init__(self, *, aprovacao=0, yes=1, no=2, affected=None, request_type="REQ", description=None, report=None,
                 request_ementa="Requer, nos termos do art. 155, urgência para o PL 1/2026."):
        super().__init__()
        self.urgency = {"id": URGENCY_ID, "data": THROUGH, "aprovacao": aprovacao,
                        "dataHoraRegistro": f"{THROUGH}T10:31:00",
                        "descricao": description or (f"{'Aprovado' if aprovacao else 'Rejeitado'} o Requerimento de "
                                                     f"Urgência (Art. 155 do RICD). Sim: {yes}; Não: {no}; Total: {yes + no}."),
                        "proposicoesAfetadas": affected if affected is not None else [target()]}
        self.request_record = {"id": 555, "siglaTipo": request_type, "numero": 10, "ano": 2026,
                               "ementa": request_ementa}
        self.urgency_report = report or urgency_report(yes=yes, no=no)
        self.votes = [participant(index, "Sim") for index in range(1, yes + 1)] + \
                     [participant(yes + index, "Não") for index in range(1, no + 1)]

    def __call__(self, url):
        path = urlsplit(url).path
        if url == URGENCY_ROLL_CALL:
            return self.urgency_report
        if path == f"/api/v2/votacoes/{URGENCY_ID}":
            return encoded({"dados": self.urgency, "links": []})
        if path == f"/api/v2/votacoes/{URGENCY_ID}/votos":
            return encoded({"dados": self.votes, "links": []})
        if path == "/api/v2/proposicoes/555":
            return encoded({"dados": self.request_record, "links": []})
        return super().__call__(url)


def urgency_inventory(extra=()):
    data = inventory()
    data["entries"][0]["registeredAt"] = f"{THROUGH}T12:31:00"
    data["entries"].append({"id": URGENCY_ID, "date": THROUGH, "candidate": False, "registeredAt": f"{THROUGH}T10:31:00"})
    data["entries"].extend(extra)
    data["voteCount"] = len(data["entries"])
    return data


class ChamberVoteUrgenciesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def build(self, urgencies, api=None, extra=(), parent_number=100):
        root = Path(tempfile.mkdtemp(dir=self.root))
        api = api or UrgencyAPI()
        data = urgency_inventory(extra)
        snapshot, details = chamber_votes.build_catalogue(data, [review()], root=root, collect=True, request=api)
        # Relatório da votação principal com número sequencial, como no catálogo real.
        if parent_number is not None:
            snapshot["items"][0]["sources"]["rollCall"] = (
                f"https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?ideVotacao={parent_number}")
        entries = {entry["id"]: entry for entry in data["entries"]}
        cache = root / "data" / "raw" / "chamber-vote-inventory" / f"{data['period']['start']}_{data['period']['end']}"
        details.update(build_urgencies(snapshot["items"], entries, urgencies, taken=set(details), cache=cache,
                                       collect=True, refresh=False, request=api))
        return snapshot, details

    def test_confirmed_request_hangs_on_the_main_vote_with_its_own_roll_call(self):
        snapshot, details = self.build([urgency_review()])
        urgency = snapshot["items"][0]["urgencies"][0]
        self.assertEqual(urgency["id"], URGENCY_ID)
        self.assertEqual(urgency["request"], {"label": "REQ 10/2026", "url": REQUEST_FICHA})
        self.assertEqual(urgency["tally"], {"yes": 1, "no": 2, "abstention": None, "total": 3})
        self.assertEqual((urgency["outcome"], urgency["quorum"]), ("rejected", 257))
        self.assertNotIn("registeredAt", urgency)
        self.assertEqual([person["vote"] for person in details[URGENCY_ID]["participants"]], ["Sim", "Não", "Não"])
        # A urgência não conta como decisão publicada do texto principal.
        self.assertEqual(snapshot["coverage"]["publishedCount"], 1)

    def test_approval_needs_the_absolute_majority(self):
        with self.assertRaisesRegex(CollectionError, "quórum do art. 155"):
            self.build([urgency_review(outcome="approved")], api=UrgencyAPI(aprovacao=1, yes=200, no=2))
        snapshot, _ = self.build([urgency_review(outcome="approved", decisionLabel="Urgência aprovada")],
                                 api=UrgencyAPI(aprovacao=1, yes=257, no=2))
        self.assertEqual(snapshot["items"][0]["urgencies"][0]["tally"]["yes"], 257)

    def test_outcome_must_match_the_api(self):
        with self.assertRaisesRegex(CollectionError, "resultado da revisão diverge"):
            self.build([urgency_review(outcome="approved")])

    def test_request_identity_comes_from_the_vote_id_and_the_roll_call(self):
        with self.assertRaisesRegex(CollectionError, "requerimento não confirma"):
            self.build([urgency_review(request={"label": "REQ 11/2026"})])
        with self.assertRaisesRegex(CollectionError, "requerimento não confirma"):
            self.build([urgency_review()], api=UrgencyAPI(request_type="PL"))
        with self.assertRaisesRegex(CollectionError, "relatório não corresponde"):
            self.build([urgency_review()], api=UrgencyAPI(report=urgency_report(request="REQ Nº 12/2026")))

    def test_target_must_be_the_project_of_the_linked_main_vote(self):
        with self.assertRaisesRegex(CollectionError, "projeto afetado diferente"):
            self.build([urgency_review()], api=UrgencyAPI(affected=[target(identifier=43)]))
        with self.assertRaisesRegex(CollectionError, "projeto afetado diferente"):
            self.build([urgency_review()], api=UrgencyAPI(affected=[target(), target(identifier=43)]))
        with self.assertRaisesRegex(CollectionError, "não cita a urgência do projeto-alvo"):
            other = "URGÊNCIA PARA APRECIAÇÃO DO PL Nº 2/2026"
            self.build([urgency_review(reportObject=other)], api=UrgencyAPI(report=urgency_report(obj=other)))

    def test_report_may_cite_the_main_vote_numbering_of_the_same_project_id(self):
        # Dados Abertos com outra numeração para o mesmo ID (apensado): vale a da votação principal.
        renumbered = [{**target(), "numero": 9, "ano": 2020}]
        snapshot, _ = self.build([urgency_review()], api=UrgencyAPI(affected=renumbered))
        self.assertEqual(len(snapshot["items"][0]["urgencies"]), 1)
        other = "URGÊNCIA PARA APRECIAÇÃO DO PL Nº 5/2020"
        with self.assertRaisesRegex(CollectionError, "não cita a urgência do projeto-alvo"):
            self.build([urgency_review(reportObject=other)],
                       api=UrgencyAPI(affected=renumbered, report=urgency_report(obj=other)))

    def test_no_other_main_text_deliberation_between_request_and_linked_vote(self):
        between = {"id": "42-7", "date": THROUGH, "candidate": True, "registeredAt": f"{THROUGH}T11:00:00"}
        with self.assertRaisesRegex(CollectionError, "outra deliberação do texto principal"):
            self.build([urgency_review()], extra=[between])
        # Deliberações depois da votação ligada (redação final, destaques) não impedem a ligação.
        after = {**between, "registeredAt": f"{THROUGH}T13:00:00"}
        snapshot, _ = self.build([urgency_review()], extra=[after])
        self.assertEqual(len(snapshot["items"][0]["urgencies"]), 1)

    def test_order_comes_from_the_roll_call_sequence_and_ambiguous_registrations_fail(self):
        with self.assertRaisesRegex(CollectionError, "não é anterior"):
            self.build([urgency_review()], parent_number=97)
        with self.assertRaisesRegex(CollectionError, "não é anterior"):
            self.build([urgency_review()], parent_number=None)
        # Registrada 3 minutos depois da votação ligada: dentro da folga de atraso da API, a ordem é ambígua.
        close = {"id": "42-7", "date": THROUGH, "candidate": True, "registeredAt": f"{THROUGH}T12:34:00"}
        with self.assertRaisesRegex(CollectionError, "ordem é ambígua"):
            self.build([urgency_review()], extra=[close])
        undated = {**close, "registeredAt": None}
        with self.assertRaisesRegex(CollectionError, "ordem é ambígua"):
            self.build([urgency_review()], extra=[undated])

    def test_api_record_must_describe_an_article_155_request(self):
        with self.assertRaisesRegex(CollectionError, "art. 155"):
            self.build([urgency_review()], api=UrgencyAPI(description="Rejeitado o Requerimento. Sim: 1; Não: 2; Total: 3."))

    def test_pending_needs_a_reason_and_ids_cannot_repeat_published_decisions(self):
        with self.assertRaisesRegex(CollectionError, "precisa de motivo"):
            self.build([{"id": URGENCY_ID, "status": "pending"}])
        snapshot, details = self.build([{"id": URGENCY_ID, "status": "pending", "reason": "Relatório não localizado."}])
        self.assertNotIn("urgencies", snapshot["items"][0])
        with self.assertRaisesRegex(CollectionError, "igual a outra decisão"):
            self.build([urgency_review(id=VOTE_ID)])

    def test_citation_accepts_official_number_formats(self):
        self.assertTrue(cites("URGÊNCIA PARA APROVAÇÃO DO PL Nº 1.958/2021", 1958, 2021))
        self.assertTrue(cites("Projeto de Lei Complementar nº 177, de 2023", 177, 2023))
        self.assertFalse(cites("URGÊNCIA PARA APRECIAÇÃO DO PL Nº 1.958/2021", 1958, 2022))
        self.assertTrue(cites("URGÊNCIA PARA APRECIAÇÃO DO PL 2342/22", 2342, 2022))
        self.assertFalse(cites("URGÊNCIA PARA APRECIAÇÃO DO PL 2342/22", 2342, 1922))


class StandaloneUrgencyTests(unittest.TestCase):
    """Pedidos de projetos sem votação principal no Placar: a situação do texto vem do inventário."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def build(self, urgency=None, api=None, extra=(), excluded=None):
        root = Path(tempfile.mkdtemp(dir=self.root))
        api = api or UrgencyAPI()
        data = urgency_inventory(extra)
        snapshot, details = chamber_votes.build_catalogue(data, [review()], root=root, collect=True, request=api)
        entries = {entry["id"]: entry for entry in data["entries"]}
        cache = root / "data" / "raw" / "chamber-vote-inventory" / f"{data['period']['start']}_{data['period']['end']}"
        standalone = []
        build_urgencies(snapshot["items"], entries, [urgency or urgency_review(parentId=None)], taken=set(details), cache=cache,
                        collect=True, refresh=False, request=api, standalone=standalone,
                        excluded=excluded or {}, through=THROUGH)
        return snapshot, standalone

    def test_project_without_later_deliberation_is_not_voted(self):
        snapshot, standalone = self.build()
        self.assertNotIn("urgencies", snapshot["items"][0])
        self.assertEqual(standalone[0]["project"], {"label": "PL 1/2026", "type": "PL"})
        self.assertEqual(standalone[0]["textStatus"], {"kind": "not_voted", "through": THROUGH})
        self.assertNotIn("registeredAt", standalone[0])

    def test_procedures_do_not_count_and_a_symbolic_text_vote_is_recorded(self):
        regime = {"id": "42-8", "date": THROUGH, "category": "procedure", "registeredAt": f"{THROUGH}T10:40:00"}
        text = {"id": "42-9", "date": THROUGH, "category": "main_text", "candidate": True, "registeredAt": f"{THROUGH}T11:00:00",
                "description": "Aprovado o Projeto de Lei nº 1, de 2026."}
        # Emenda de comissão votada na mesma sessão, logo antes do texto.
        amendment = {"id": "42-7", "date": THROUGH, "category": "amendment", "registeredAt": f"{THROUGH}T10:50:00"}
        _, standalone = self.build(extra=[regime, amendment, text], excluded={"42-9": "Votação simbólica na transcrição."})
        self.assertEqual(standalone[0]["textStatus"], {"kind": "symbolic", "date": THROUGH})
        with self.assertRaisesRegex(CollectionError, "sem votação simbólica confirmada"):
            self.build(extra=[text], excluded={"42-9": "Outro motivo."})
        with self.assertRaisesRegex(CollectionError, "não registra aprovação"):
            self.build(extra=[{**text, "description": "Rejeitado o Projeto de Lei nº 1, de 2026."}],
                       excluded={"42-9": "Votação simbólica."})

    def build_with_published(self, published_id, registered, extra=(), excluded=None):
        """Catálogo em que uma votação nominal do texto do projeto 42 está publicada no Placar."""
        root = Path(tempfile.mkdtemp(dir=self.root))
        api = UrgencyAPI()
        data = urgency_inventory([{"id": published_id, "date": THROUGH, "category": "main_text", "candidate": True,
                                   "registeredAt": registered, "description": "Aprovado o Projeto de Lei nº 1, de 2026."}, *extra])
        snapshot, details = chamber_votes.build_catalogue(data, [review()], root=root, collect=True, request=api)
        published = {**snapshot["items"][0], "id": published_id,
                     "sources": {**snapshot["items"][0]["sources"],
                                 "rollCall": "https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?ideVotacao=100"}}
        items = [published]
        entries = {entry["id"]: entry for entry in data["entries"]}
        cache = root / "data" / "raw" / "chamber-vote-inventory" / f"{data['period']['start']}_{data['period']['end']}"
        standalone = []
        build_urgencies(items, entries, [urgency_review(parentId=None)], taken=set(details), cache=cache, collect=True,
                        refresh=False, request=api, standalone=standalone, excluded=excluded or {}, through=THROUGH)
        return items, standalone

    def test_a_request_is_linked_automatically_when_the_text_enters_the_scoreboard(self):
        items, standalone = self.build_with_published("42-9", f"{THROUGH}T11:00:00")
        self.assertEqual(standalone, [])
        self.assertEqual([urgency["id"] for urgency in items[0]["urgencies"]], [URGENCY_ID])
        # A ligação automática passa pelas mesmas conferências de ordem.
        with self.assertRaisesRegex(CollectionError, "ordem é ambígua"):
            self.build_with_published("42-9", f"{THROUGH}T11:00:00", extra=[
                {"id": "42-8", "date": THROUGH, "category": "main_text", "candidate": True, "registeredAt": f"{THROUGH}T11:02:00",
                 "description": "Rejeitado o Substitutivo."}], excluded={"42-8": "Votação simbólica."})

    def test_a_later_roll_call_on_the_text_is_pointed_from_the_symbolic_status(self):
        symbolic = {"id": "42-7", "date": THROUGH, "category": "main_text", "candidate": True,
                    "registeredAt": f"{THROUGH}T10:45:00", "description": "Aprovado o Projeto de Lei nº 1, de 2026."}
        _, standalone = self.build_with_published("42-9", f"{THROUGH}T12:40:00", extra=[symbolic],
                                                  excluded={"42-7": "Votação simbólica."})
        self.assertEqual(standalone[0]["textStatus"], {"kind": "symbolic", "date": THROUGH,
                                                       "laterVote": {"id": "42-9", "date": THROUGH}})

    def test_other_deliberations_without_the_main_text_fail_closed(self):
        senate = {"id": "42-9", "date": THROUGH, "category": "amendment", "registeredAt": f"{THROUGH}T11:00:00"}
        with self.assertRaisesRegex(CollectionError, "não é a do texto principal"):
            self.build(extra=[senate])
        undated = {**senate, "registeredAt": None}
        with self.assertRaisesRegex(CollectionError, "ordem ambígua"):
            self.build(extra=[undated])

    def test_only_article_155_requests_enter(self):
        with self.assertRaisesRegex(CollectionError, "art. 155"):
            self.build(api=UrgencyAPI(description="Rejeitado o Requerimento de Urgência (Art. 154 do RICD). Sim: 1; Não: 2; Total: 3."))
        # Sem artigo na descrição, vale a ementa oficial do requerimento.
        silent = "Rejeitado o requerimento de urgência. Sim: 1; Não: 2; Total: 3."
        _, standalone = self.build(api=UrgencyAPI(description=silent))
        self.assertEqual(len(standalone), 1)
        with self.assertRaisesRegex(CollectionError, "art. 155"):
            self.build(api=UrgencyAPI(description=silent, request_ementa="Requer urgência para o PL 1/2026."))


if __name__ == "__main__":
    unittest.main()
