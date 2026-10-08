import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingest import chamber_payroll as payroll


COMPONENT_ROWS = [
    ("a - Remuneração Fixa", "1.234,56"),
    ("b - Vantagens de Natureza Pessoal", "0,00"),
    ("a - Função ou Cargo em Comissão", "0,00"),
    ("b - Gratificação Natalina", "0,00"),
    ("c - Férias (1/3 Constitucional)", "0,00"),
    ("d - Outras Remunerações Eventuais/Provisórias(*)", "0,00"),
    ("a - Abono Permanência", "0,00"),
    ("a - Redutor Constitucional", "0,00"),
    ("b - Contribuição Previdenciária", "-988,07"),
    ("c - Imposto de Renda", "-11.570,25"),
    ("a - Remuneração após Descontos Obrigatórios", "33.807,87"),
    ("a - Diárias", "0,00"),
    ("b - Auxílios", "0,00"),
    ("c - Vantagens Indenizatórias", "0,00"),
]

CSV_COLUMNS = [
    "Cargo Individualizado do Servidor",
    "Grupo Funcional",
    "Folha de Pagamento",
    "Ano Ingresso",
    "Remuneração Fixa",
    "Vantagens de Natureza Pessoal",
    "Função ou Cargo em Comissão",
    "Gratificação Natalina",
    "Férias (1/3 Constitucional)",
    "Outras Remunerações Eventuais/Provisórias(*)",
    "Abono de Permanência",
    "Redutor Constitucional",
    "Constribuição Previdenciária",
    "Imposto de Renda",
    "Remuneração Após Descontos Obrigatórios",
    "Diárias",
    "Auxílios",
    "Vantagens Indenizatórias",
]
JANUARY_CSV_URL = (
    "https://www2.camara.leg.br/transparencia/recursos-humanos/remuneracao/"
    "relatorios-consolidados-por-ano-e-mes/2026/janeiro-de-2026-csv"
)


def payroll_table(identity="FOLHA NORMAL", period="02/2026", rows=None):
    body = "".join(
        f"<tr><td>{label}</td><td align='right'>{value}</td></tr>"
        for label, value in (COMPONENT_ROWS if rows is None else rows)
    )
    return (
        "<table><caption>Mês/Ano de Referência/Tipo Folha: "
        f"{period} -{identity}</caption><thead><tr><th>Descrição</th><th>Valor R$</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def csv_row(role, sheet, code, *, missing_component=None):
    values = {column: "0,00" for column in CSV_COLUMNS}
    values.update({
        "Cargo Individualizado do Servidor": code,
        "Grupo Funcional": role,
        "Folha de Pagamento": sheet,
        "Ano Ingresso": "2023",
        "Remuneração Fixa": "1.234,56",
        "Constribuição Previdenciária": "-988,07",
    })
    if missing_component:
        values[missing_component] = ""
    return values


def roster_file(root, profile_id="camara:220661"):
    path = root / "data" / "imports" / "legislative.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"authorities": [{
        "id": profile_id,
        "role": "deputado",
        "sourceId": payroll.ROSTER_SOURCE_ID,
    }]}), encoding="utf-8")


class ChamberPayrollTests(unittest.TestCase):
    def test_cents_keep_explicit_zero_and_missing_component_is_not_zero(self):
        self.assertEqual(payroll.parse_cents("46.366,19"), 4_636_619)
        self.assertEqual(payroll.parse_cents("-988,07"), -98_807)
        self.assertEqual(payroll.parse_cents("0,00"), 0)
        self.assertIsNone(payroll.parse_cents(""))

        rows = list(COMPONENT_ROWS)
        rows[1] = (rows[1][0], "")
        result = payroll.parse_payroll_html(
            payroll_table(rows=rows), "camara:220661", 2026, 2
        )
        sheet = result["sheets"][0]
        self.assertEqual(result["status"], "partial")
        self.assertNotIn("personal_advantages", sheet["componentsCents"])
        self.assertIn("personal_advantages", sheet["missingComponents"])
        self.assertEqual(sheet["componentsCents"]["fixed_remuneration"], 123_456)

    def test_wrong_period_is_rejected_before_it_can_be_attached_to_a_month(self):
        with self.assertRaisesRegex(payroll.SourceError, "período diferente"):
            payroll.parse_payroll_html(
                payroll_table(period="03/2026"), "camara:220661", 2026, 2
            )

    def test_every_supplementary_sheet_keeps_its_identity(self):
        html = (
            payroll_table()
            + payroll_table("FOLHA COMPLEMENTAR")
            + payroll_table("FOLHA COMPLEMENTAR - 1")
            + payroll_table("FOLHA COMPLEMENTAR - 2")
            + payroll_table("FOLHA DE ADIANTAMENTO GRATIFICAÇÃO NATALINA")
        )
        result = payroll.parse_payroll_html(html, "camara:220661", 2026, 2)
        self.assertEqual(result["status"], "complete")
        self.assertEqual([sheet["identity"] for sheet in result["sheets"]], [
            "FOLHA NORMAL", "FOLHA COMPLEMENTAR", "FOLHA COMPLEMENTAR - 1",
            "FOLHA COMPLEMENTAR - 2", "FOLHA DE ADIANTAMENTO GRATIFICAÇÃO NATALINA",
        ])
        self.assertEqual([sheet["sheetNumber"] for sheet in result["sheets"]], [None, None, 1, 2, None])
        self.assertEqual([sheet["sheetType"] for sheet in result["sheets"]], [
            "normal", "complementary", "complementary", "complementary", "advance_christmas_bonus",
        ])
        self.assertEqual(result["sheets"][2]["componentsCents"]["fixed_remuneration"], 123_456)

    def test_detail_url_must_match_public_profile_and_requested_month(self):
        with self.assertRaisesRegex(payroll.SourceError, "perfil e período"):
            payroll.parse_payroll_html(
                payroll_table(), "camara:220661", 2026, 2,
                "https://www.camara.leg.br/deputados/220714/remuneracao-deputado-detalhado?mesAno=022026",
            )
        with self.assertRaisesRegex(payroll.SourceError, "perfil e período"):
            payroll.parse_payroll_html(
                payroll_table(), "camara:220661", 2026, 2,
                "https://www.camara.leg.br/deputados/220661/remuneracao-deputado-detalhado?mesAno=032026",
            )

    def test_monthly_inventory_aggregates_only_parliamentary_rows_and_drops_codes(self):
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerow(csv_row("Parlamentar", "Normal", "Deputado 90501"))
        writer.writerow(csv_row("Parlamentar", "Complementar - 1", "Deputado 90501"))
        writer.writerow(csv_row("Aposentadoria Parlamentar", "Complementar - 1", "Deputado 10001"))
        writer.writerow(csv_row("Secretário Parlamentar", "Complementar - 1", "Servidor 19046"))

        result = payroll.parse_consolidated_csv(
            buffer.getvalue().encode("iso-8859-1"), 2026, 1,
            JANUARY_CSV_URL,
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["group"], "Parlamentar")
        self.assertEqual(result["rowCount"], 2)
        by_type = {row["sheetType"]: row for row in result["sheets"]}
        self.assertEqual(by_type["Complementar - 1"]["rowCount"], 1)
        self.assertEqual(by_type["Complementar - 1"]["componentTotalsCents"]["fixed_remuneration"], 123_456)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("90501", serialized)
        self.assertNotIn("19046", serialized)

    def test_inventory_missing_value_is_not_summed_as_zero(self):
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerow(csv_row(
            "Parlamentar", "Normal", "Deputado 90501",
            missing_component="Vantagens de Natureza Pessoal",
        ))
        result = payroll.parse_consolidated_csv(
            buffer.getvalue().encode("iso-8859-1"), 2026, 1,
            JANUARY_CSV_URL,
        )
        sheet = result["sheets"][0]
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(sheet["componentTotalsCents"]["personal_advantages"])
        self.assertIn("personal_advantages", sheet["componentsWithMissingValues"])

    def test_consolidated_csv_url_must_match_requested_month_and_year(self):
        with self.assertRaisesRegex(payroll.SourceError, "CSV ou período"):
            payroll.parse_consolidated_csv(
                b"not a csv", 2026, 1,
                "https://www2.camara.leg.br/transparencia/recursos-humanos/remuneracao/"
                "relatorios-consolidados-por-ano-e-mes/2026/fevereiro-de-2026-1",
            )
        parsed = payroll.parse_report_index(
            '<a href="https://www2.camara.leg.br/transparencia/recursos-humanos/remuneracao/'
            'relatorios-consolidados-por-ano-e-mes/2026/fevereiro-de-2026-1">CSV</a>',
            2026,
        )
        self.assertEqual(parsed[2].rsplit("/", 1)[-1], "fevereiro-de-2026-1")

    def test_partial_inventory_refresh_does_not_replace_complete_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory)
            cache_path = payroll._inventory_cache_path(raw_root, 2026, 1)
            complete = {
                "period": "2026-01", "year": 2026, "month": 1, "status": "complete",
                "group": "Parlamentar", "sourceUrl": JANUARY_CSV_URL,
                "sheets": [{"sheetType": "Normal", "rowCount": 1}],
            }
            payroll._atomic_json(cache_path, complete)
            partial = {
                "period": "2026-01", "year": 2026, "month": 1, "status": "partial",
                "group": "Parlamentar", "sourceUrl": JANUARY_CSV_URL,
                "sourceSha256": "b" * 64, "sheets": [],
                "missingHeaders": ["income_tax"], "unparseableRows": 0,
            }
            with patch.object(payroll, "_request_bytes", return_value=(b"csv", JANUARY_CSV_URL, "2026-10-07")), \
                    patch.object(payroll, "parse_consolidated_csv", return_value=partial):
                result = payroll._load_sheet_inventory(
                    raw_root, 2026, 1, JANUARY_CSV_URL, collect=True, refresh=True
                )
            self.assertEqual(result["status"], "complete")
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "complete")
            self.assertTrue(cache_path.with_suffix(".attempt.json").exists())

    def test_resume_uses_atomic_caches_and_marks_unlinked_supplementary_rows_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roster_file(root)
            raw_root = root / "data" / "raw" / "mandate-cost" / "payroll" / "camara"
            index_path = payroll._index_cache_path(raw_root, 2026)
            payroll._atomic_json(index_path, {
                "year": 2026,
                "sourceUrl": "https://www2.camara.leg.br/reports/2026",
                "urls": {"1": "https://www2.camara.leg.br/reports/janeiro-de-2026-csv"},
            })
            inventory = {
                "period": "2026-01", "year": 2026, "month": 1, "status": "complete",
                "group": "Parlamentar", "sourceUrl": "https://www2.camara.leg.br/reports/janeiro-de-2026-csv",
                "sourceSha256": "a" * 64, "rowCount": 2,
                "identityLinkage": "unavailable_from_consolidated_csv",
                "sheets": [
                    {"sheetType": "Normal", "rowCount": 1, "componentTotalsCents": {}},
                    {"sheetType": "Complementar - 1", "rowCount": 1, "componentTotalsCents": {}},
                ],
            }
            payroll._atomic_json(payroll._inventory_cache_path(raw_root, 2026, 1), inventory)
            detail = payroll.parse_payroll_html(
                payroll_table(period="01/2026"), "camara:220661", 2026, 1
            )
            payroll._atomic_json(payroll._profile_cache_path(raw_root, 2026, "camara:220661", 1), detail)
            output = root / "data" / "snapshots" / "chamber-payroll.json"
            with patch.object(payroll, "_request_bytes", side_effect=AssertionError("resume should not fetch")):
                snapshot, stats = payroll.build_snapshot(
                    root=root, year=2026, months=[1], collect=True,
                    profile_ids=["camara:220661"], output=output,
                )
            observation = snapshot["profiles"]["camara:220661"]["months"]["2026-01"]
            self.assertEqual(stats["partial"], 1)
            self.assertEqual(observation["status"], "partial")
            self.assertEqual(
                observation["sheetCoverage"]["reason"],
                "supplementary_rows_are_not_linked_to_public_deputy_ids",
            )
            self.assertEqual(observation["sheets"][0]["componentsCents"]["fixed_remuneration"], 123_456)

    def test_partial_refresh_keeps_a_previous_complete_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory)
            cache_path = payroll._profile_cache_path(raw_root, 2026, "camara:220661", 2)
            complete = payroll.parse_payroll_html(
                payroll_table(), "camara:220661", 2026, 2
            )
            payroll._atomic_json(cache_path, complete)
            rows = list(COMPONENT_ROWS)
            rows[0] = (rows[0][0], "")
            partial_payload = payroll_table(rows=rows).encode("utf-8")
            with patch.object(
                payroll, "_request_bytes",
                return_value=(partial_payload, payroll.detail_url("camara:220661", 2026, 2), "2026-10-07T12:00:00+00:00"),
            ):
                partial = payroll._collect_profile_month("camara:220661", 2026, 2, raw_root)
            self.assertEqual(partial["detailStatus"], "partial")
            preserved = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(preserved["detailStatus"], "complete")
            attempt = json.loads(cache_path.with_suffix(".attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["status"], "partial")
            self.assertIn("sheet-1-missing-components", attempt["issues"])

    def test_missing_cache_does_not_erase_a_previous_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roster_file(root)
            output = root / "data" / "snapshots" / "chamber-payroll.json"
            previous = {
                "profiles": {"camara:220661": {"months": {"2026-01": {
                    "profileId": "camara:220661", "period": "2026-01", "year": 2026, "month": 1,
                    "status": "complete", "detailStatus": "complete",
                    "sourceUrl": payroll.detail_url("camara:220661", 2026, 1),
                    "sheets": [{"identity": "FOLHA NORMAL", "componentsCents": {"fixed_remuneration": 123_456}}],
                }}}},
                "sheetInventory": {"months": {}},
            }
            payroll._atomic_json(output, previous)
            snapshot, stats = payroll.build_snapshot(
                root=root, year=2026, months=[1], collect=False,
                profile_ids=["camara:220661"], output=output,
            )
            preserved = snapshot["profiles"]["camara:220661"]["months"]["2026-01"]
            self.assertEqual(preserved["status"], "complete")
            self.assertEqual(preserved["sheets"][0]["componentsCents"]["fixed_remuneration"], 123_456)
            self.assertEqual(stats["complete"], 1)

    def test_failed_refresh_with_missing_raw_cache_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roster_file(root)
            output = root / "data" / "snapshots" / "chamber-payroll.json"
            previous_observation = {
                "profileId": "camara:220661", "period": "2026-01", "year": 2026, "month": 1,
                "status": "complete", "detailStatus": "complete",
                "sourceUrl": payroll.detail_url("camara:220661", 2026, 1),
                "sheets": [{"identity": "FOLHA NORMAL", "componentsCents": {"fixed_remuneration": 123_456}}],
            }
            payroll._atomic_json(output, {
                "profiles": {"camara:220661": {"months": {"2026-01": previous_observation}}},
                "sheetInventory": {"months": {}},
            })
            failed_attempt = dict(
                previous_observation,
                status="unavailable", detailStatus="unavailable", errorType="SourceError",
                fetchedAt="2026-10-07T12:00:00+00:00", sheets=[],
            )
            with patch.object(payroll, "_load_report_links", return_value=({}, None)), \
                    patch.object(payroll, "_load_sheet_inventory", return_value=None), \
                    patch.object(payroll, "_collect_profile_month", return_value=failed_attempt):
                snapshot, _ = payroll.build_snapshot(
                    root=root, year=2026, months=[1], collect=True, refresh=True,
                    profile_ids=["camara:220661"], output=output,
                )
            kept = snapshot["profiles"]["camara:220661"]["months"]["2026-01"]
            self.assertEqual(kept["status"], "complete")
            self.assertEqual(kept["sheets"][0]["componentsCents"]["fixed_remuneration"], 123_456)
            self.assertEqual(kept["lastAttempt"]["status"], "unavailable")

    def test_snapshot_does_not_retain_unneeded_names_or_raw_html(self):
        html = "<h1>Nome Civil Desnecessário</h1><p>CPF 00000000000</p>" + payroll_table()
        result = payroll.parse_payroll_html(html, "camara:220661", 2026, 2)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("Nome Civil Desnecessário", serialized)
        self.assertNotIn("00000000000", serialized)
        self.assertNotIn("<table", serialized)
        self.assertRegex(result["sourceSha256"], r"^[0-9a-f]{64}$")

    def test_month_parser_accepts_ranges_and_rejects_wrong_periods(self):
        self.assertEqual(payroll.parse_months("1-3, 7..9", 2026), [1, 2, 3, 7, 8, 9])
        self.assertEqual(payroll.parse_months(None, 2026, today=payroll.date(2026, 10, 7)), list(range(1, 10)))
        with self.assertRaises(ValueError):
            payroll.parse_months("9-2", 2026)


if __name__ == "__main__":
    unittest.main()
