import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ingest import accounts, finbra


TABLE_HEADERS = {
    "revenue": "Tabela: Receitas Orçamentárias (Anexo I-C)",
    "expenses": "Tabela: Despesas Orçamentárias (Anexo I-D)",
    "functions": "Tabela: Despesas por Função (Anexo I-E)",
}


def row(institution, code, uf, column, account, identifier, value):
    return [institution, code, uf, "100", column, account, identifier, value]


class FinbraImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.configured = finbra.paths(self.root, 2025)

    def tearDown(self):
        self.temp.cleanup()

    def write_city_identity(self, cities):
        catalog_path = self.configured["city_catalog"]
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(json.dumps({"municipalities": cities}), encoding="utf-8")
        accounts._cache_entes_payload({"items": [
            {"cod_ibge": int(city["id"]), "uf": city["uf"], "esfera": "M", "ente": city["name"]}
            for city in cities
        ], "hasMore": False}, self.configured["entities"], "2026-10-07T12:00:00+00:00")

    def write_file(self, file_key, rows, *, table_header=None, malformed_row=None):
        path = self.configured[file_key]
        path.parent.mkdir(parents=True, exist_ok=True)
        table_header = table_header or TABLE_HEADERS[file_key]
        with path.open("w", encoding="cp1252", newline="") as stream:
            stream.write("Exercício: 2025\nEscopo: Municípios\n")
            stream.write(table_header + "\n")
            writer = csv.writer(stream, delimiter=";", lineterminator="\n")
            writer.writerow(finbra.CSV_FIELDS)
            for item in rows:
                writer.writerow(item)
            if malformed_row is not None:
                stream.write(malformed_row + "\n")
        return path

    def complete_rows_for(self, code, uf, city_name, *, revenue="1.234,56"):
        institution = f"Prefeitura Municipal de {city_name} - {uf}"
        return {
            "revenue": [row(institution, code, uf, "Receitas Brutas Realizadas", "Receitas totais",
                            "siconfi-cor_TotalReceitas", revenue)],
            "expenses": [
                row(institution, code, uf, "Despesas Empenhadas", "Total Geral da Despesa",
                    "siconfi-cor_TotalDespesas", "0,00"),
                row(institution, code, uf, "Despesas Empenhadas", "Pessoal e Encargos Sociais",
                    "siconfi-cor_DO3.1.00.00.00.00", "100,00"),
            ],
            "functions": [
                row(institution, code, uf, "Despesas Empenhadas", "10 - Saúde",
                    "siconfi-cor_TotalDespesas", "20,01"),
                row(institution, code, uf, "Despesas Empenhadas", "12 - Educação",
                    "siconfi-cor_TotalDespesas", "0,00"),
                row(institution, code, uf, "Despesas Empenhadas", "Despesas Intraorçamentárias",
                    "siconfi-cor_TotalDespesas", "999,99"),
            ],
        }

    def write_dataset(self, cities, *, blank_city=None, duplicate_revenue=None):
        self.write_city_identity(cities)
        grouped = {"revenue": [], "expenses": [], "functions": []}
        for city in cities:
            code = city["id"]
            city_rows = self.complete_rows_for(
                code, city["uf"], city["name"], revenue="" if code == blank_city else "1.234,56")
            for file_key, rows in city_rows.items():
                if code == blank_city and file_key != "revenue":
                    continue
                grouped[file_key].extend(rows)
        if duplicate_revenue is not None:
            code, uf, name = duplicate_revenue
            institution = f"Prefeitura Municipal de {name} - {uf}"
            grouped["revenue"].append(row(
                institution, code, uf, "Receitas Brutas Realizadas", "Receitas totais",
                "siconfi-cor_TotalReceitas", "9.999,99"))

        malformed = (
            'Prefeitura Municipal de São Paulo - SP;3550308;SP;100;'
            '"Receitas Brutas Realizadas";"Conta "Inter Vivos" com aspas";'
            '"siconfi-cor_ContaNaoSelecionada";0,00'
        )
        for key, rows in grouped.items():
            self.write_file(key, rows, malformed_row=malformed if key == "revenue" else None)

    def test_stream_import_selects_exact_metrics_preserves_zero_and_missing_and_hashes_files(self):
        cities = [
            {"id": "3550308", "name": "São Paulo", "uf": "SP"},
            {"id": "3166600", "name": "Serra da Saudade", "uf": "MG"},
        ]
        self.write_dataset(cities, blank_city="3166600")
        manifest = finbra.collect(self.root, 2025)
        stage = self.configured["output"]
        sp = json.loads((stage / "3550308.json").read_text(encoding="utf-8"))
        serra = json.loads((stage / "3166600.json").read_text(encoding="utf-8"))
        values = {metric["id"]: metric["amountCents"] for metric in sp["metrics"]}
        self.assertEqual(values, {
            "revenue": 123456,
            "total-expense": 0,
            "personnel": 10000,
            "health": 2001,
            "education": 0,
        })
        serra_values = {metric["id"]: metric["amountCents"] for metric in serra["metrics"]}
        self.assertIsNone(serra_values["revenue"])
        self.assertIsNone(serra_values["health"])
        self.assertEqual(sp["declaration"]["status"], "unknown")
        self.assertTrue(sp["identityVerified"])
        self.assertTrue(sp["collectionComplete"])
        self.assertEqual(sp["status"], "available")
        self.assertEqual(serra["status"], "partial")
        self.assertFalse(serra["collectionComplete"])
        health_source = next(metric["source"] for metric in sp["metrics"] if metric["id"] == "health")
        self.assertEqual(health_source["file"], "finbra-functions.csv")
        self.assertEqual(health_source["evidenceType"], "national_finbra_export")
        self.assertEqual(manifest["coverage"]["stagedMunicipalities"], 2)
        self.assertEqual(manifest["files"]["revenue"]["malformedQuotedRows"], 1)
        self.assertEqual(manifest["files"]["revenue"]["invalidWidthRows"], 0)
        for file_key in ("revenue", "expenses", "functions"):
            path = self.configured[file_key]
            expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(manifest["files"][file_key]["sha256"], expected_hash)
            self.assertEqual(manifest["files"][file_key]["sizeBytes"], path.stat().st_size)
        self.assertFalse(self.configured["api_cache_dir"].exists())

    def test_wrong_metadata_rejects_import_before_publishing_stage(self):
        city = {"id": "3550308", "name": "São Paulo", "uf": "SP"}
        self.write_dataset([city])
        self.write_file("functions", [], table_header="Tabela: Despesas Orçamentárias (Anexo I-D)")
        with self.assertRaisesRegex(ValueError, "metadata"):
            finbra.collect(self.root, 2025)
        self.assertFalse(self.configured["output"].exists())

    def test_conflicting_duplicate_metric_selection_rejects_import(self):
        city = {"id": "3550308", "name": "São Paulo", "uf": "SP"}
        self.write_dataset([city], duplicate_revenue=(city["id"], city["uf"], city["name"]))
        with self.assertRaisesRegex(ValueError, "conflicting duplicate revenue"):
            finbra.collect(self.root, 2025)
        self.assertFalse(self.configured["output"].exists())

    def test_install_missing_preserves_api_values_and_audits_numeric_and_delivery_conflicts(self):
        cities = [
            {"id": "3550308", "name": "São Paulo", "uf": "SP"},
            {"id": "3166600", "name": "Serra da Saudade", "uf": "MG"},
            {"id": "1111111", "name": "Nova Cidade", "uf": "RJ"},
        ]
        self.write_dataset(cities)
        finbra.collect(self.root, 2025)
        stage_dir = self.configured["output"]
        sp_stage = json.loads((stage_dir / "3550308.json").read_text(encoding="utf-8"))
        serra_stage = json.loads((stage_dir / "3166600.json").read_text(encoding="utf-8"))
        api_dir = self.configured["api_cache_dir"]
        api_dir.mkdir(parents=True, exist_ok=True)

        api_sp = json.loads(json.dumps(sp_stage))
        api_sp["declaration"] = {"status": "submitted"}
        api_sp["source"] = accounts._source(
            accounts.DCA_URL.format(year=2025, municipality_id="3550308"), 2025,
            "2026-10-07T12:00:00+00:00", "available")
        for metric in api_sp["metrics"]:
            metric["source"] = dict(api_sp["source"])
        api_sp["metrics"][0]["amountCents"] += 10
        accounts._atomic_json(accounts._cache_path(api_dir, "3550308"), api_sp)
        original_sp = json.loads(json.dumps(api_sp))

        api_serra = {
            "id": "3166600", "year": 2025, "status": "not_filed",
            "collectionComplete": True, "identityVerified": True,
            "declaration": {"status": "not_filed"}, "metrics": [],
            "message": "Não entregou ao Tesouro",
            "source": accounts._source(
                accounts.DELIVERIES_URL.format(year=2025, municipality_id="3166600"), 2025,
                "2026-10-07T12:00:00+00:00", "cached"),
        }
        accounts._atomic_json(accounts._cache_path(api_dir, "3166600"), api_serra)

        report = finbra.install_missing(self.root, stage_dir, 2025)
        self.assertEqual(report["counts"]["installedMissing"], 1)
        self.assertEqual(report["counts"]["numericConflictRows"], 1)
        self.assertEqual(report["counts"]["numericConflictMetrics"], 1)
        self.assertEqual(report["counts"]["deliveryConflictRows"], 1)

        updated_sp = json.loads(accounts._cache_path(api_dir, "3550308").read_text(encoding="utf-8"))
        self.assertEqual(updated_sp["status"], "partial")
        self.assertIsNone(updated_sp["metrics"][0]["amountCents"])
        self.assertEqual(updated_sp["metrics"][1]["amountCents"], original_sp["metrics"][1]["amountCents"])
        updated_serra = json.loads(accounts._cache_path(api_dir, "3166600").read_text(encoding="utf-8"))
        self.assertEqual(updated_serra["status"], "partial")
        self.assertEqual(updated_serra["declaration"], {"status": "unknown"})
        self.assertEqual(updated_serra["metrics"], [])
        self.assertTrue(updated_serra["collectionComplete"])
        self.assertTrue(updated_serra["identityVerified"])
        installed = json.loads(accounts._cache_path(api_dir, "1111111").read_text(encoding="utf-8"))
        self.assertEqual(installed["declaration"], {"status": "unknown"})

        saved_report = json.loads((stage_dir / "reconciliation.json").read_text(encoding="utf-8"))
        numeric_entry = next(item for item in saved_report["entries"] if item["action"] == "numeric_conflict")
        self.assertEqual(numeric_entry["originalApiRow"]["metrics"][0]["amountCents"], original_sp["metrics"][0]["amountCents"])
        self.assertEqual(numeric_entry["finbraStageRow"]["metrics"][0]["amountCents"], sp_stage["metrics"][0]["amountCents"])
        delivery_entry = next(item for item in saved_report["entries"] if item["action"] == "delivery_conflict")
        self.assertEqual(delivery_entry["originalApiRow"]["declaration"]["status"], "not_filed")
        self.assertEqual(len(delivery_entry["finbraStageRow"]["metrics"]), 5)

        second = finbra.install_missing(self.root, stage_dir, 2025)
        self.assertEqual(second["counts"].get("installedMissing", 0), 0)
        self.assertEqual(len(second["entries"]), 2)


if __name__ == "__main__":
    unittest.main()
