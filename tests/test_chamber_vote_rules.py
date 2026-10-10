import unittest

from ingest import chamber_vote_rules as rules


class ChamberVoteRulesTests(unittest.TestCase):
    def setUp(self):
        self.base = {"siglaOrgao": "PLEN", "descricao": ""}

    def classify(self, description, **fields):
        return rules.classify_vote({**self.base, "descricao": description, **fields})

    def test_rule_version_and_result_shape_are_stable(self):
        result = self.classify("Aprovado o Projeto de Lei nº 10, de 2026.")

        self.assertEqual(rules.RULE_VERSION, "chamber-vote-inventory-v3")
        self.assertEqual(
            set(result),
            {"category", "candidate", "reason", "method", "recordedTally", "targetPropositions"},
        )

    def test_approved_and_rejected_project_text_are_candidates(self):
        for description in (
            "Aprovado o Projeto de Lei nº 10, de 2026.",
            "Rejeitada a PEC nº 20, de 2026, em segundo turno.",
        ):
            with self.subTest(description=description):
                result = self.classify(description)
                self.assertEqual(result["category"], "main_text")
                self.assertTrue(result["candidate"])

    def test_substitutive_subamendment_with_reserved_highlights_is_main_text(self):
        result = self.classify(
            "Aprovada a Subemenda Substitutiva ao Projeto de Lei Complementar nº 74, "
            "de 2026, adotada pelo relator. Sim: 346; Não: 46; Abstenção: 3; Total: 395.",
            proposicoesAfetadas=[{"id": 740, "siglaTipo": "PLP", "numero": 74, "ano": 2026}],
        )

        self.assertEqual(result["category"], "main_text")
        self.assertTrue(result["candidate"])
        self.assertEqual(result["recordedTally"], {"yes": 346, "no": 46, "abstention": 3, "total": 395})

    def test_spelled_out_pec_turns_are_main_text_not_amendments(self):
        for description in (
            "Aprovada, em segundo turno, a Proposta de Emenda à Constituição nº 45, de 2019, "
            "ressalvados os destaques. Sim: 375; não: 113; abstenção:3; total: 491.",
            "Aprovado, em primeiro turno, o Substitutivo à Proposta de Emenda à Constituição nº 18, "
            "de 2025, adotado pelo relator da Comissão Especial.",
            "Aprovada, em primeiro turno, a Proposta de Emenda à Constituição nº 5, de 2023, na forma da "
            "Emenda Aglutinativa Substitutiva nº 3. Sim: 385; Não: 93.",
            "Aprovada, em primeiro turno, a Emenda Aglutinativa Substitutiva à Proposta de Emenda à "
            "Constituição nº 31, de 2007. Sim: 344; Não: 154; Abstenção: 2; Total: 500.",
        ):
            with self.subTest(description=description):
                result = self.classify(description)
                self.assertEqual(result["category"], "main_text")
                self.assertTrue(result["candidate"])
        for description in ("Aprovada a Emenda nº 3 à Proposta de Emenda à Constituição nº 45, de 2019.",
                            "Aprovada a Emenda Aglutinativa nº 1. Sim: 379; não: 114; total: 494.",
                            "Aprovada a Emenda Aglutinativa Substitutiva nº 2 ao Projeto de Lei nº 4, de 2024."):
            self.assertEqual(self.classify(description)["category"], "amendment")

    def test_actual_highlight_and_amendment_votes_are_amendments(self):
        descriptions = (
            "Aprovado o destaque ao PLP nº 74, de 2026.",
            "Rejeitada a Emenda nº 4 ao Projeto de Lei nº 10.",
            "Rejeitadas as Emendas ao Substitutivo.",
            "Aprovada a Emenda do Senado ao Projeto de Lei nº 10.",
            "Aprovado o trecho destacado do Projeto de Lei nº 10.",
            "Rejeitada a supressão do art. 2º.",
            "Aprovada a manutenção do dispositivo.",
        )
        for description in descriptions:
            with self.subTest(description=description):
                result = self.classify(description)
                self.assertEqual(result["category"], "amendment")
                self.assertFalse(result["candidate"])

    def test_senate_substitute_exception_does_not_hide_a_main_text_candidate(self):
        result = self.classify(
            "Aprovado o Substitutivo do Senado Federal ao Projeto de Lei nº 3.780, "
            "de 2023, com exceção dos dispositivos rejeitados.",
            descUltimaAberturaVotacao=(
                "Votação do Substitutivo do Senado Federal ao Projeto de Lei nº 3.780, "
                "de 2023, com parecer pela aprovação, com exceção dos dispositivos rejeitados."
            ),
            proposicoesAfetadas=[{"id": 2376169, "siglaTipo": "PL", "numero": 3780, "ano": 2023}],
        )
        self.assertEqual(result["category"], "main_text")
        self.assertTrue(result["candidate"])
        self.assertEqual(result["method"], "unknown")
        self.assertIsNone(result["recordedTally"])

    def test_senate_substitute_exception_clause_does_not_decide_the_category(self):
        result = self.classify(
            "Aprovado o Substitutivo do Senado Federal ao Projeto de Lei Complementar nº 175, de 2024, "
            "com exceção dos artigos 3º e 7º, da supressão do § 4º do art. 4º aprovado pela Câmara e do "
            "§ 2º do art. 8º. Sim: 343; Não: 41; Total: 384.")
        self.assertEqual(result["category"], "main_text")
        self.assertTrue(result["candidate"])
        self.assertEqual(self.classify("Rejeitados os artigos 3º e 7º; a supressão do § 4º do art. 4º.")["category"],
                         "amendment")

    def test_generic_dispositions_need_an_explicit_highlight_opening(self):
        for description in ("Mantido o texto. Sim: 335; Não: 117; Total: 452.",
                            "Suprimido o texto.", "Resultado. Sim: 182; Não: 182; Total: 364."):
            with self.subTest(description=description):
                result = self.classify(description, descUltimaAberturaVotacao=(
                    "Votação do DTQ 4: Destaque para Votação em Separado da expressão do art. 1º."
                ))
                self.assertEqual(result["category"], "amendment")
                self.assertFalse(result["candidate"])
                self.assertEqual(result["method"], "unknown")
                self.assertEqual(self.classify(description)["category"], "unknown")
                self.assertEqual(self.classify(description, descUltimaAberturaVotacao=(
                    "Votação em turno único do Projeto de Lei nº 10."
                ))["category"], "unknown")

    def test_requests_appeals_and_highlight_preference_are_procedural(self):
        for description in ("Rejeitado o Requerimento.", "Aprovado o Requerimento.",
                            "Rejeitado o Recurso nº 2, de 2026, contra parecer terminativo "
                            "à Emenda de Plenário nº 3 oferecida ao Projeto de Lei nº 1.743, de 2024."):
            with self.subTest(description=description):
                result = self.classify(description)
                self.assertEqual(result["category"], "procedure")
                self.assertFalse(result["candidate"])
        for description in ("Preferência.", "Aprovada a Preferência.", "Rejeitada a preferência.",
                            "Aprovada a preferência. Sim: 467; Não: 4; Abstenção: 1; Total: 472."):
            with self.subTest(description=description):
                preference = self.classify(description, descUltimaAberturaVotacao=(
                    "Votação do DTQ 2: Destaque de Preferência para o Projeto de Lei."
                ))
                self.assertEqual(preference["category"], "procedure")
                self.assertEqual(self.classify(description)["category"], "unknown")

    def test_misspelled_subamendment_is_resolved_only_by_the_specific_opening(self):
        description = "Aprovada a Submenda da Comissão de Constituição e Justiça e de Cidadania."
        result = self.classify(description, descUltimaAberturaVotacao=(
            "Votação da Subemenda da Comissão de Constituição e Justiça e de Cidadania "
            "ao Substitutivo da Comissão de Viação e Transportes."
        ))
        self.assertEqual(result["category"], "amendment")
        self.assertFalse(result["candidate"])
        self.assertEqual(self.classify(description)["category"], "unknown")
        self.assertEqual(self.classify(description, descUltimaAberturaVotacao=(
            "Votação da Subemenda Substitutiva global ao Projeto."
        ))["category"], "unknown")

    def test_reserved_single_highlight_is_not_the_decision_being_voted(self):
        result = self.classify(
            "Aprovado o Substitutivo Reformulado ao Projeto de Lei Complementar nº 114, "
            "de 2026, adotado pela relatora da Comissão de Minas e Energia, ressalvado o destaque. "
            "Sim: 318; Não: 113; Abstenção: 1; Total: 432.",
            proposicoesAfetadas=[{"id": 2618177, "siglaTipo": "PLP", "numero": 114, "ano": 2026}],
        )
        self.assertEqual(result["category"], "main_text")
        self.assertTrue(result["candidate"])

    def test_urgency_nominal_request_admissibility_and_withdrawal_are_procedures(self):
        descriptions = (
            "Aprovado o requerimento de urgência para o Projeto de Lei nº 10.",
            "Aprovado o requerimento de votação nominal.",
            "Rejeitada a admissibilidade da PEC nº 20.",
            "Aprovada a retirada de pauta do Projeto de Lei nº 10.",
            "Alteração do Regime de Tramitação desta proposição em virtude da alteração "
            "do regime do PL 3904/2023, por ter sido aprovado o REQ 4650/2025 que está apensado ao primeiro.",
            "Aprovada a apreciação preliminar dos pressupostos constitucionais da PEC nº 20.",
            "Aprovado parecer só de admissibilidade do Projeto de Lei nº 10.",
        )
        for description in descriptions:
            with self.subTest(description=description):
                result = self.classify(description)
                self.assertEqual(result["category"], "procedure")
                self.assertFalse(result["candidate"])
                if "votação nominal" in description:
                    self.assertEqual(result["method"], "unknown")

        explicit_current_method = self.classify(
            "Aprovado o requerimento de votação nominal.",
            descUltimaAberturaVotacao="Votação nominal",
        )
        self.assertEqual(explicit_current_method["category"], "procedure")
        self.assertEqual(explicit_current_method["method"], "nominal")

    def test_final_wording_is_separate_from_main_text(self):
        result = self.classify("Aprovada a Redação Final do Projeto de Lei nº 10.")

        self.assertEqual(result["category"], "final_wording")
        self.assertFalse(result["candidate"])

    def test_explicit_method_only_and_secret_or_symbolic_votes_are_excluded(self):
        nominal = self.classify("Aprovado o Projeto de Lei nº 10.", descUltimaAberturaVotacao="Votação nominal")
        secret = self.classify("Aprovado o Projeto de Lei nº 10 em votação secreta.")
        symbolic = self.classify("Aprovado o Projeto de Lei nº 10 em votação simbólica.")
        conflicting_method = self.classify(
            "Aprovado o Projeto de Lei nº 10 em votação nominal e secreta."
        )
        inferred = self.classify(
            "Aprovado o Projeto de Lei nº 10. Sim: 3; Não: 2; Abstenção: 0; Total: 5.",
            votos=[{"voto": "Sim"}, {"voto": "Não"}],
        )

        self.assertEqual(nominal["method"], "nominal")
        self.assertTrue(nominal["candidate"])
        self.assertEqual(secret["method"], "secret")
        self.assertFalse(secret["candidate"])
        self.assertEqual(symbolic["method"], "symbolic")
        self.assertFalse(symbolic["candidate"])
        self.assertEqual(conflicting_method["method"], "unknown")
        self.assertFalse(conflicting_method["candidate"])
        self.assertEqual(inferred["method"], "unknown")
        self.assertTrue(inferred["candidate"])

    def test_zero_tally_is_distinct_from_absent_tally(self):
        zero = self.classify("Aprovado o Projeto de Lei nº 10. Sim: 0; Não: 0; Abstenção: 0; Total: 0.")
        missing = self.classify("Aprovado o Projeto de Lei nº 10.")
        partial = self.classify(
            "Aprovado o Substitutivo. Sim: 333; Não: 91; Total: 424."
        )

        self.assertEqual(zero["recordedTally"], {"yes": 0, "no": 0, "abstention": 0, "total": 0})
        self.assertIsNone(missing["recordedTally"])
        self.assertEqual(
            partial["recordedTally"],
            {"yes": 333, "no": 91, "abstention": None, "total": 424},
        )

    def test_conflicting_or_unclear_description_is_not_a_candidate(self):
        descriptions = (
            "Aprovado e rejeitado o Projeto de Lei nº 10.",
            "Aprovada a matéria em discussão.",
            "Votação do Projeto de Lei nº 10.",
            "Aprovado o Projeto de Lei nº 10 e rejeitada a emenda nº 3.",
        )
        for description in descriptions:
            with self.subTest(description=description):
                result = self.classify(description)
                self.assertEqual(result["category"], "unknown")
                self.assertFalse(result["candidate"])

    def test_possible_objects_and_last_presentation_do_not_infer_a_voted_target(self):
        result = self.classify(
            "Aprovada a matéria.",
            objetosPossiveis=[{"id": 10, "siglaTipo": "PL", "numero": 10, "ano": 2026}],
            ultimaApresentacao={"id": 10, "siglaTipo": "PL"},
        )

        self.assertEqual(result["category"], "unknown")
        self.assertFalse(result["candidate"])
        self.assertEqual(result["targetPropositions"], [])

    def test_non_plenary_record_cannot_be_a_candidate(self):
        result = self.classify("Aprovado o Projeto de Lei nº 10.", siglaOrgao="CFT")

        self.assertEqual(result["category"], "main_text")
        self.assertFalse(result["candidate"])

    def test_target_propositions_are_restricted_and_deduplicated_by_id(self):
        project = {"id": 10, "siglaTipo": "PL", "numero": 10, "ano": 2026}
        duplicate_project = {**project, "ementa": "duplicate record"}
        targets = [
            project,
            duplicate_project,
            {"id": 11, "siglaTipo": "PLP", "numero": 11, "ano": 2026},
            {"id": 12, "siglaTipo": "PEC", "numero": 12, "ano": 2026},
            {"id": 13, "siglaTipo": "REQ", "numero": 13, "ano": 2026},
        ]
        result = self.classify("Aprovado o Projeto de Lei nº 10.", proposicoesAfetadas=targets)

        self.assertTrue(result["candidate"])
        self.assertEqual([item["id"] for item in result["targetPropositions"]], [10, 11, 12])
        self.assertIs(result["targetPropositions"][0], project)

    def test_affected_proposition_does_not_resolve_a_vague_vote_description(self):
        result = self.classify(
            "Aprovada a matéria.",
            proposicoesAfetadas=[{"id": 10, "siglaTipo": "PL", "numero": 10, "ano": 2026}],
        )

        self.assertEqual(result["category"], "unknown")
        self.assertFalse(result["candidate"])
        self.assertEqual([item["id"] for item in result["targetPropositions"]], [10])

    def test_valid_affected_types_outside_v1_block_substitute_candidates(self):
        records = (
            (
                "Aprovado o Substitutivo ao Projeto de Lei de Conversão nº 1.",
                {"id": 101, "siglaTipo": "PLV", "numero": 1, "ano": 2026},
            ),
            (
                "Aprovada a Subemenda Substitutiva à Medida Provisória nº 2.",
                {"id": 202, "siglaTipo": "MPV", "numero": 2, "ano": 2026},
            ),
        )
        for description, proposition in records:
            with self.subTest(proposition_type=proposition["siglaTipo"]):
                result = self.classify(description, proposicoesAfetadas=[proposition])
                self.assertEqual(result["category"], "main_text")
                self.assertFalse(result["candidate"])
                self.assertIn("fora do escopo", result["reason"])
                self.assertEqual(result["targetPropositions"], [])

    def test_out_of_scope_project_types_block_list_candidates(self):
        descriptions = (
            "Aprovado o Projeto de Decreto Legislativo nº 1.",
            "Aprovado o Projeto de Resolução nº 2.",
            "Aprovada a Medida Provisória nº 3.",
            "Aprovado o Projeto de Lei de Conversão nº 4.",
            "Aprovado o PLV nº 5.",
        )
        for description in descriptions:
            with self.subTest(description=description):
                result = self.classify(description)
                self.assertEqual(result["category"], "main_text")
                self.assertFalse(result["candidate"])
                self.assertIn("fora do escopo", result["reason"])

    def test_list_row_requires_an_explicit_text_reference_when_no_target_exists(self):
        explicit = self.classify("Aprovado o Substitutivo.")
        unclear = self.classify("Aprovado o texto principal.")

        self.assertTrue(explicit["candidate"])
        self.assertEqual(unclear["category"], "unknown")
        self.assertFalse(unclear["candidate"])


if __name__ == "__main__":
    unittest.main()
