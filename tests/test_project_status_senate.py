import unittest

from ingest.project_status_senate import needs_detail, normalize_status


CONSULTED = "2026-10-07T18:00:00Z"
SOURCE = "https://legis.senado.leg.br/dadosabertos/processo?idProcesso=8993967"


class SenateProjectStatusTests(unittest.TestCase):
    def test_law_requires_explicit_generated_norm_and_keeps_observation_dates_separate(self):
        row = {
            "id": 8993967,
            "identificacao": "PLP 14/2026",
            "tramitando": "Não",
            "normaGerada": "Lei Complementar nº 228 de 19/03/2026",
        }
        detail = {
            "normaGerada": {
                "codigo": 42916365,
                "siglaTipo": "LCP",
                "tipo": "Lei Complementar",
                "numero": 228,
                "anoAssinatura": "2026",
            },
            "autuacoes": [{
                "descricao": "Autuação Principal",
                "situacoes": [{
                    "sigla": "TNJR",
                    "descricao": "TRANSFORMADA EM NORMA JURÍDICA",
                    "inicio": "2026-03-20",
                    "fim": "2026-03-25",
                }],
            }],
        }

        result = normalize_status(row, CONSULTED, SOURCE, detail)

        self.assertEqual(result["grupo"], "lei")
        self.assertEqual(result["status"], "imported")
        self.assertEqual(result["consultadoEm"], CONSULTED.replace("Z", "+00:00"))
        self.assertEqual(result["atualizadoEm"], "2026-03-25")
        self.assertEqual(result["normas"], [{
            "tipo": "Lei Complementar",
            "numero": "228",
            "ano": 2026,
            "url": "https://legis.senado.leg.br/norma/42916365",
        }])
        self.assertIsNone(result["detail"])

    def test_transformed_status_without_a_generated_norm_stays_unknown(self):
        row = {
            "id": 700,
            "tramitando": "Não",
            "situacaoAtual": "TRANSFORMADA EM NORMA JURÍDICA",
        }

        result = normalize_status(row, CONSULTED, SOURCE)

        self.assertIsNone(result["grupo"])
        self.assertIn("tipo da norma não foi confirmado", result["detail"])
        self.assertTrue(needs_detail(row))

    def test_pec_becomes_constitutional_amendment_not_law(self):
        row = {
            "id": 701,
            "identificacao": "PEC 113/2021",
            "tramitando": "Não",
            "normaGerada": "Emenda Constitucional nº 113 de 08/12/2021",
        }

        result = normalize_status(row, CONSULTED, SOURCE)

        self.assertEqual(result["grupo"], "emenda")
        self.assertEqual(result["normas"][0]["tipo"], "Emenda Constitucional")
        self.assertEqual(result["normas"][0]["numero"], "113")
        self.assertEqual(result["normas"][0]["ano"], 2021)

    def test_official_lei_numerada_merges_text_and_object_and_keeps_norm_url(self):
        row = {
            "id": 9064334,
            "tramitando": "Não",
            "situacaoAtual": "TRANSFORMADA EM NORMA JURÍDICA",
            "normaGerada": "Lei nº 15.484 de 04/08/2026",
        }
        detail = {
            "normaGerada": {
                "codigo": 43627311,
                "siglaTipo": "LEI-n",
                "tipo": "Lei Numerada",
                "numero": 15484,
                "anoAssinatura": "2026",
            },
        }

        result = normalize_status(row, CONSULTED, SOURCE, detail)

        self.assertEqual(result["grupo"], "lei")
        self.assertEqual(result["normas"], [{
            "tipo": "Lei",
            "numero": "15484",
            "ano": 2026,
            "url": "https://legis.senado.leg.br/norma/43627311",
        }])

    def test_archive_description_conflicting_with_generated_law_stays_unknown(self):
        row = {
            "id": 711,
            "tramitando": "Não",
            "situacaoAtual": "ARQUIVADA AO FINAL DA LEGISLATURA",
            "normaGerada": "Lei nº 55 de 2026",
        }

        result = normalize_status(row, CONSULTED, SOURCE)

        self.assertIsNone(result["grupo"])
        self.assertIn("conflita", result["detail"])

    def test_explicit_archive_status_is_classified_as_archived(self):
        row = {
            "id": 702,
            "tramitando": "Não",
            "situacaoAtual": "ARQUIVADA AO FINAL DA LEGISLATURA",
        }

        result = normalize_status(row, CONSULTED, SOURCE)

        self.assertEqual(result["grupo"], "arquivado")
        self.assertTrue(needs_detail(row))

    def test_active_nonterminal_process_is_classified_as_in_progress(self):
        row = {
            "id": 703,
            "tramitando": "Sim",
            "situacaoAtual": "AUDIÊNCIA PÚBLICA REALIZADA",
        }

        result = normalize_status(row, CONSULTED, SOURCE)

        self.assertEqual(result["grupo"], "tramitando")
        self.assertFalse(needs_detail(row))

    def test_in_progress_alone_does_not_imply_archived_or_rejected(self):
        row = {"id": 704, "tramitando": "Não"}

        result = normalize_status(row, CONSULTED, SOURCE)

        self.assertIsNone(result["grupo"])
        self.assertIn("desfecho não foi classificado", result["detail"])
        self.assertTrue(needs_detail(row))

    def test_withdrawn_and_prejudiced_are_not_labeled_archived(self):
        for situation in ("RETIRADA PELO AUTOR", "PREJUDICADA"):
            with self.subTest(situation=situation):
                result = normalize_status({
                    "id": 705,
                    "tramitando": "Não",
                    "situacaoAtual": situation,
                }, CONSULTED, SOURCE)
                self.assertIsNone(result["grupo"])
                self.assertIn("não presume arquivamento", result["detail"])

    def test_norms_in_related_processes_are_never_used_as_evidence(self):
        row = {"id": 706, "tramitando": "Não"}
        detail = {
            "processosRelacionados": [{
                "normaGerada": {
                    "codigo": 123,
                    "tipo": "Lei",
                    "numero": 55,
                    "anoAssinatura": "2026",
                },
            }],
            "outrosNumeros": [{
                "normaGerada": "Lei nº 55 de 2026",
            }],
        }

        result = normalize_status(row, CONSULTED, SOURCE, detail)

        self.assertIsNone(result["grupo"])
        self.assertEqual(result["normas"], [])

    def test_conflicting_active_flag_and_generated_norm_stays_unknown(self):
        row = {
            "id": 707,
            "tramitando": "Sim",
            "situacaoAtual": "MATÉRIA COM A RELATORIA",
            "normaGerada": "Lei nº 55 de 2026",
        }

        result = normalize_status(row, CONSULTED, SOURCE)

        self.assertIsNone(result["grupo"])
        self.assertIn("conflita", result["detail"])

    def test_conflicting_active_flag_and_terminal_status_stays_unknown(self):
        row = {
            "id": 708,
            "tramitando": "Sim",
            "situacaoAtual": "ARQUIVADA AO FINAL DA LEGISLATURA",
        }

        result = normalize_status(row, CONSULTED, SOURCE)

        self.assertIsNone(result["grupo"])
        self.assertIn("situação final", result["detail"])

    def test_conflicting_generated_norm_records_stay_unknown(self):
        row = {
            "id": 709,
            "tramitando": "Não",
            "normaGerada": "Lei Complementar nº 228 de 19/03/2026",
        }
        detail = {"normaGerada": {
            "tipo": "Lei Complementar",
            "numero": 229,
            "anoAssinatura": 2026,
        }}

        result = normalize_status(row, CONSULTED, SOURCE, detail)

        self.assertIsNone(result["grupo"])
        self.assertIn("Tipos de norma gerada conflitantes", result["detail"])

    def test_nonprincipal_or_invalid_history_is_not_terminal_evidence(self):
        row = {"id": 710, "tramitando": "Não"}
        detail = {"autuacoes": [
            {"descricao": "Autuação Secundária", "situacoes": [{
                "sigla": "ARQVD",
                "descricao": "ARQUIVADA AO FINAL DA LEGISLATURA",
                "inicio": "2026-01-01",
                "fim": None,
            }]},
            {"descricao": "Autuação Principal", "situacoes": [{
                "sigla": "ARQVD",
                "descricao": "ARQUIVADA AO FINAL DA LEGISLATURA",
                "inicio": "data inválida",
                "fim": None,
            }]},
        ]}

        result = normalize_status(row, CONSULTED, SOURCE, detail)

        self.assertIsNone(result["grupo"])
        self.assertIn("datas válidas", result["detail"])

    def test_invalid_process_response_is_unavailable(self):
        result = normalize_status(None, CONSULTED, SOURCE)

        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["grupo"])
        self.assertEqual(result["normas"], [])


if __name__ == "__main__":
    unittest.main()
