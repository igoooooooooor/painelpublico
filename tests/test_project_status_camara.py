import unittest

from ingest.project_status_camara import needs_detail, normalize_status


CONSULTED_AT = "2026-10-07T18:00:00+00:00"
PROJECT_URI = "https://dadosabertos.camara.leg.br/api/v2/proposicoes/123"
ARCHIVE_URL = "https://dadosabertos.camara.leg.br/arquivos/proposicoes/json/proposicoes-2026.json"


class ProjectStatusCamaraTests(unittest.TestCase):
    def annual_row(self, *, proposition_type="PL", description="Aguardando Parecer", **status_fields):
        latest = {
            "data": "2026-09-01T19:34:35",
            "descricaoSituacao": description,
            "idSituacao": "915",
            "descricaoTramitacao": "Encerramento de Prazo",
            "despacho": "Encerrado o prazo; não foram apresentadas emendas.",
        }
        latest.update(status_fields)
        return {
            "id": 123,
            "uri": PROJECT_URI,
            "siglaTipo": proposition_type,
            "ultimoStatus": latest,
        }

    def test_active_status_requires_an_observed_allowlisted_label(self):
        result = normalize_status(self.annual_row(), CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["grupo"], "tramitando")
        self.assertEqual(result["status"], "imported")
        self.assertEqual(result["descricao"], "Aguardando Parecer")
        self.assertEqual(result["atualizadoEm"], "2026-09-01T19:34:35")
        self.assertEqual(result["consultadoEm"], CONSULTED_AT)
        self.assertEqual(result["sourceUrl"], PROJECT_URI)
        self.assertEqual(result["codSituacao"], "915")

        for label in (
            "Aguardando Redação Final",
            "Aguardando Criação de Comissão Temporária",
            "Aguardando Deliberação de Recurso",
            "Aguardando Apreciação do Veto",
            "Aguardando Definição Encaminhamento",
            "Aguardando Constituição de Comissão Temporária",
            "Aguardando Envio ao Senado Federal",
            "Aguardando Despacho do Presidente",
        ):
            with self.subTest(label=label):
                self.assertEqual(
                    normalize_status(self.annual_row(description=label), CONSULTED_AT, ARCHIVE_URL)["grupo"],
                    "tramitando",
                )

        unrecognized = normalize_status(
            self.annual_row(description="Em andamento", idSituacao="915"),
            CONSULTED_AT,
            ARCHIVE_URL,
        )
        self.assertIsNone(unrecognized["grupo"])
        self.assertEqual(unrecognized["status"], "imported")

    def test_direct_own_transformation_and_final_urn_classify_a_pl_as_law(self):
        row = self.annual_row(
            description="Transformado em Norma Jurídica",
            descricaoTramitacao="Apresentação de Proposição",
            despacho="Transformado na Lei Ordinária 15436/2026. DOU 18/06/2026.",
        )
        row["urnFinal"] = "urn:lex:br:federal:lei:2026-06-17;15436"
        result = normalize_status(row, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["grupo"], "lei")
        self.assertEqual(result["normas"], [{
            "tipo": "Lei", "numero": "15436", "ano": 2026,
            "url": "urn:lex:br:federal:lei:2026-06-17;15436",
        }])

        generic_norm = normalize_status(
            self.annual_row(description="Transformado em Norma Jurídica"),
            CONSULTED_AT,
            ARCHIVE_URL,
        )
        self.assertEqual(generic_norm["grupo"], "lei")
        self.assertEqual(generic_norm["normas"], [])

    def test_urn_requires_a_valid_calendar_date(self):
        row = self.annual_row(description="Aguardando Parecer")
        row["urnFinal"] = "urn:lex:br:federal:lei:2026-02-30;15436"
        result = normalize_status(row, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["grupo"], "tramitando")
        self.assertEqual(result["normas"], [])

    def test_apensado_or_principal_law_is_never_propagated_to_another_project(self):
        row = self.annual_row(
            description="Tramitando em Conjunto",
            descricaoTramitacao="Apensação",
            despacho="Apensação desta proposição ao PL 4778/2024, transformado em lei.",
        )
        row["uriPropPrincipal"] = "https://dadosabertos.camara.leg.br/api/v2/proposicoes/456"
        result = normalize_status(row, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["grupo"], "tramitando")
        self.assertEqual(result["normas"], [])

        combined_label = normalize_status(
            self.annual_row(description="Apensado ao PL 5794/2001 - Transformada na Lei 11552/2007"),
            CONSULTED_AT,
            ARCHIVE_URL,
        )
        self.assertIsNone(combined_label["grupo"])
        self.assertEqual(combined_label["normas"], [])

    def test_pec_transformation_is_an_emenda_group_and_needs_explicit_ec_evidence(self):
        row = self.annual_row(
            proposition_type="PEC",
            description="Transformada na Emenda Constitucional 113/2021",
            idSituacao="1140",
        )
        row["urnFinal"] = "urn:lex:br:federal:emenda.constitucional:2021-12-08;113"
        result = normalize_status(row, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["grupo"], "emenda")
        self.assertEqual(len(result["normas"]), 1)
        self.assertEqual(result["normas"][0]["tipo"], "Emenda Constitucional")
        self.assertEqual(result["normas"][0]["numero"], "113")
        self.assertEqual(result["normas"][0]["ano"], 2021)

        generic = normalize_status(
            self.annual_row(proposition_type="PEC", description="Transformado em Norma Jurídica"),
            CONSULTED_AT,
            ARCHIVE_URL,
        )
        self.assertIsNone(generic["grupo"])
        self.assertTrue(needs_detail(self.annual_row(
            proposition_type="PEC", description="Transformado em Norma Jurídica"
        )))

    def test_pec_own_norm_status_and_anchored_dispatch_identify_the_ec(self):
        # Fields copied from the official detail response for proposition 2352476.
        row = {
            "id": 2352476,
            "uri": "https://dadosabertos.camara.leg.br/api/v2/proposicoes/2352476",
            "siglaTipo": "PEC",
            "urnFinal": None,
            "statusProposicao": {
                "dataHora": "2024-08-22T00:00",
                "descricaoTramitacao": "Transformação em Norma Jurídica",
                "descricaoSituacao": "Transformado em Norma Jurídica",
                "codSituacao": 1140,
                "despacho": (
                    "Transformado na Emenda Constitucional 133/2024. "
                    "DOU 23/08/24 PÁG 02 COL 01."
                ),
            },
        }
        result = normalize_status(row, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["grupo"], "emenda")
        self.assertEqual(result["normas"], [{
            "tipo": "Emenda Constitucional",
            "numero": "133",
            "ano": 2024,
            "url": None,
        }])
        self.assertFalse(needs_detail(row))

    def test_anchored_ec_dispatch_does_not_classify_related_or_unqualified_text(self):
        apensado = self.annual_row(
            proposition_type="PEC",
            description="Transformado em Norma Jurídica",
            despacho="Apensada à Emenda Constitucional 133/2024, transformada em norma jurídica.",
        )
        self.assertIsNone(normalize_status(apensado, CONSULTED_AT, ARCHIVE_URL)["grupo"])
        self.assertTrue(needs_detail(apensado))

        mention_after_intro = self.annual_row(
            proposition_type="PEC",
            description="Transformado em Norma Jurídica",
            despacho="Informação: Transformado na Emenda Constitucional 133/2024.",
        )
        self.assertIsNone(normalize_status(mention_after_intro, CONSULTED_AT, ARCHIVE_URL)["grupo"])

        no_own_transform = self.annual_row(
            proposition_type="PEC",
            description="Aguardando Parecer",
            despacho="Transformado na Emenda Constitucional 133/2024.",
        )
        result = normalize_status(no_own_transform, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["grupo"], "tramitando")
        self.assertEqual(result["normas"], [])

        pl = self.annual_row(
            proposition_type="PL",
            description="Aguardando Parecer",
            despacho="Transformado na Emenda Constitucional 133/2024.",
        )
        result = normalize_status(pl, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["grupo"], "tramitando")
        self.assertEqual(result["normas"], [])

    def test_conflicting_final_law_urn_blocks_dispatch_as_an_ec(self):
        row = self.annual_row(
            proposition_type="PEC",
            description="Transformado em Norma Jurídica",
            despacho="Transformado na Emenda Constitucional 133/2024. DOU 23/08/24.",
        )
        row["urnFinal"] = "urn:lex:br:federal:lei:2024-08-23;133"
        result = normalize_status(row, CONSULTED_AT, ARCHIVE_URL)
        self.assertIsNone(result["grupo"])
        self.assertEqual(result["normas"][0]["tipo"], "Lei")
        self.assertFalse(needs_detail(row))

        mismatched_ec = self.annual_row(
            proposition_type="PEC",
            description="Transformado em Norma Jurídica",
            despacho="Transformado na Emenda Constitucional 133/2024. DOU 23/08/24.",
        )
        mismatched_ec["urnFinal"] = "urn:lex:br:federal:emenda.constitucional:2024-08-23;134"
        result = normalize_status(mismatched_ec, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["grupo"], "emenda")
        self.assertEqual(result["normas"][0]["numero"], "134")
        self.assertEqual(len(result["normas"]), 1)

    def test_detail_lookup_is_limited_to_own_transformations_missing_norm_evidence(self):
        generic_pl = self.annual_row(description="Transformado em Norma Jurídica")
        self.assertTrue(needs_detail(generic_pl))

        identified_law = self.annual_row(description="Transformado na Lei 15436/2026")
        self.assertFalse(needs_detail(identified_law))

        final_urn = self.annual_row(description="Transformado em Norma Jurídica")
        final_urn["urnFinal"] = "urn:lex:br:federal:lei:2026-06-17;15436"
        self.assertFalse(needs_detail(final_urn))

        new_proposition = self.annual_row(description="Transformado em nova proposição")
        self.assertFalse(needs_detail(new_proposition))

        dispatch_only = self.annual_row(
            description="Aguardando Parecer",
            despacho="Transformado na Lei 15436/2026.",
        )
        self.assertFalse(needs_detail(dispatch_only))
        self.assertEqual(
            normalize_status(dispatch_only, CONSULTED_AT, ARCHIVE_URL)["grupo"],
            "tramitando",
        )

    def test_archived_is_distinct_from_withdrawn_or_prejudiced_text(self):
        archived = normalize_status(
            self.annual_row(description="Arquivada", despacho="Esta proposição fica prejudicada."),
            CONSULTED_AT,
            ARCHIVE_URL,
        )
        self.assertEqual(archived["grupo"], "arquivado")
        self.assertIn("prejudicada", archived["detail"])

        conflict = self.annual_row(
            description="Arquivada",
            descricaoTramitacao="Transformado em Norma Jurídica",
        )
        conflict["urnFinal"] = "urn:lex:br:federal:lei:2026-06-17;15436"
        conflicted = normalize_status(conflict, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(conflicted["grupo"], "arquivado")
        self.assertFalse(needs_detail(conflict))

        withdrawn = normalize_status(
            self.annual_row(description="Retirado pelo(a) Autor(a)"),
            CONSULTED_AT,
            ARCHIVE_URL,
        )
        self.assertIsNone(withdrawn["grupo"])

    def test_api_detail_shape_and_unknown_numeric_codes_are_preserved_without_mapping(self):
        detail = {
            "dados": {
                "id": 321,
                "uri": "https://dadosabertos.camara.leg.br/api/v2/proposicoes/321",
                "siglaTipo": "PLP",
                "urnFinal": None,
                "statusProposicao": {
                    "dataHora": "2026-08-10T10:15:00",
                    "descricaoSituacao": "Situação futura desconhecida",
                    "codSituacao": 7654321,
                    "descricaoTramitacao": "Ação genérica",
                    "despacho": "Texto informativo sem classificação automática.",
                },
            }
        }
        result = normalize_status(detail, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["status"], "imported")
        self.assertIsNone(result["grupo"])
        self.assertEqual(result["atualizadoEm"], "2026-08-10T10:15:00")
        self.assertEqual(result["codSituacao"], "7654321")
        self.assertEqual(result["sourceUrl"], detail["dados"]["uri"])

    def test_missing_situation_keeps_a_valid_row_imported_but_unclassified(self):
        row = {"id": 777, "uri": PROJECT_URI, "siglaTipo": "PL"}
        result = normalize_status(row, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["status"], "imported")
        self.assertIsNone(result["grupo"])
        self.assertIsNone(result["descricao"])
        self.assertEqual(result["normas"], [])

    def test_invalid_row_is_unavailable(self):
        result = normalize_status({"dados": []}, CONSULTED_AT, ARCHIVE_URL)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["grupo"])
        self.assertEqual(result["sourceUrl"], ARCHIVE_URL)


if __name__ == "__main__":
    unittest.main()
