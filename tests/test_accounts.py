import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import accounts, cities


SOURCE = {
    "label": "Tesouro Nacional — Siconfi",
    "url": "https://dados.gov.br/example",
    "period": "2025",
    "fetchedAt": "2026-10-07T12:00:00+00:00",
    "status": "available",
}
POPULATION_SOURCE = {
    "label": "IBGE — Estimativas de população",
    "url": "https://ibge.example",
    "status": "available",
}


def account_row(status="available", metric_amount=500, metric_source=None, message=None):
    row = {
        "status": status,
        "declaration": {"status": "submitted", "submittedAt": "2026-03-30"},
        "metrics": [{
            "id": "expense:health",
            "label": "Despesa com saúde",
            "amountCents": metric_amount,
            "classification": "function",
            "stage": "paid",
        }],
    }
    if metric_source is not None:
        row["metrics"][0]["source"] = metric_source
    if message:
        row["message"] = message
    return row


def write_snapshot(path, *, rows=None, populations=None, complete=True, source=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "year": 2025,
        "generatedAt": "2026-10-07T12:00:00+00:00",
        "source": source if source is not None else SOURCE,
        "coverage": {"nationalCollectionComplete": complete},
        "municipalities": rows if rows is not None else {},
        "population": {
            "year": 2025,
            "source": POPULATION_SOURCE,
            "municipalities": populations if populations is not None else {},
        },
    }
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    return snapshot


class AccountDetailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot_path = self.root / "accounts.json"
        self.city_id = "1111111"
        self.rows = {
            self.city_id: account_row(metric_amount=500),
            "3550308": account_row(metric_amount=0),
            "3304557": account_row(metric_amount=100),
            "1234567": account_row(metric_amount=200),
            "7654321": account_row(status="not_filed", metric_amount=999),
            "7654322": account_row(metric_amount=999, metric_source={"status": "unavailable"}),
            "7654323": account_row(metric_amount=999),
            "7654324": account_row(metric_amount=999),
            "5300108": account_row(metric_amount=888),
            "2605459": account_row(metric_amount=777),
        }
        self.populations = {
            self.city_id: 10_000,
            "3550308": 5_001,
            "3304557": 10_000,
            "1234567": 5_001,
            "7654321": 7_000,
            "7654322": 8_000,
            "7654323": 5_000,
            "7654324": 10_001,
            "5300108": 7_000,
            "2605459": 9_000,
            "7654325": True,
        }
        write_snapshot(self.snapshot_path, rows=self.rows, populations=self.populations)

    def tearDown(self):
        self.temp.cleanup()

    def test_population_band_boundaries_and_invalid_values(self):
        self.assertEqual(accounts._population_band(1)["id"], "up_to_5000")
        self.assertEqual(accounts._population_band(5_000)["id"], "up_to_5000")
        self.assertEqual(accounts._population_band(5_001)["id"], "5001_to_10000")
        self.assertEqual(accounts._population_band(10_000)["id"], "5001_to_10000")
        self.assertEqual(accounts._population_band(10_001)["id"], "10001_to_20000")
        self.assertEqual(accounts._population_band(500_001)["id"], "over_500000")
        for value in (0, -1, None, True, 1.5, "5000"):
            self.assertIsNone(accounts._population_band(value))

    def test_comparison_uses_same_band_other_cities_and_includes_actual_zero(self):
        detail = accounts.detail(self.city_id, self.snapshot_path)
        comparison = detail["comparison"]
        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["band"]["id"], "5001_to_10000")
        self.assertEqual(comparison["populationYear"], 2025)
        self.assertEqual(comparison["populationSource"], POPULATION_SOURCE)
        self.assertEqual(comparison["universeCount"], 5)
        self.assertEqual(comparison["reportingCount"], 3)
        self.assertEqual(comparison["metrics"], [{
            "id": "expense:health", "medianCents": 100, "sampleSize": 3,
        }])
        self.assertEqual(detail["metrics"][0]["amountCents"], 500)

    def test_comparison_excludes_other_expense_stages_and_population_years(self):
        self.rows["1234567"]["metrics"][0]["stage"] = "committed"
        snapshot = write_snapshot(self.snapshot_path, rows=self.rows, populations=self.populations)
        result = accounts.detail(self.city_id, self.snapshot_path)["comparison"]
        self.assertEqual(result["metrics"][0]["sampleSize"], 2)
        self.assertIsNone(result["metrics"][0]["medianCents"])
        snapshot["population"]["year"] = 2026
        self.snapshot_path.write_text(json.dumps(snapshot))
        result = accounts.detail(self.city_id, self.snapshot_path)["comparison"]
        self.assertFalse(result["available"])
        self.assertIn("mesmo exercício", result["message"])

    def test_even_median_uses_decimal_half_up_cents(self):
        self.assertEqual(accounts._median_cents([0, 1]), 1)
        self.assertEqual(accounts._median_cents([-2, -1]), -2)

    def test_per_metric_requires_three_peers_and_excludes_null_boolean_and_missing_sources(self):
        self.rows["1234567"] = account_row(metric_amount=None)
        self.rows["7654323"] = account_row(metric_amount=True)
        write_snapshot(self.snapshot_path, rows=self.rows, populations=self.populations)
        comparison = accounts.detail(self.city_id, self.snapshot_path)["comparison"]
        self.assertFalse(comparison["available"])
        self.assertEqual(comparison["reportingCount"], 2)
        self.assertEqual(comparison["metrics"][0]["sampleSize"], 2)
        self.assertIsNone(comparison["metrics"][0]["medianCents"])
        self.assertIn("ao menos 3", comparison["metrics"][0]["message"])

    def test_incomplete_national_collection_suppresses_all_medians(self):
        write_snapshot(self.snapshot_path, rows=self.rows, populations=self.populations, complete=False)
        comparison = accounts.detail(self.city_id, self.snapshot_path)["comparison"]
        self.assertFalse(comparison["available"])
        self.assertEqual(comparison["metrics"], [])
        self.assertIn("coleta nacional", comparison["message"])

    def test_not_filed_status_is_explicit_and_other_absence_does_not_claim_nonfiling(self):
        not_filed_id = "7654321"
        not_filed = accounts.detail(not_filed_id, self.snapshot_path)
        self.assertEqual(not_filed["status"], "not_filed")
        self.assertEqual(not_filed["message"], "Não entregou ao Tesouro.")
        self.assertFalse(not_filed["comparison"]["available"])
        missing = accounts.detail("9999999", self.snapshot_path)
        self.assertEqual(missing["status"], "unavailable")
        self.assertNotIn("Não entregou ao Tesouro", missing["message"])
        self.assertEqual(accounts.detail("../secret", self.snapshot_path), None)

    def test_stale_source_flag_and_message_are_preserved(self):
        stale_source = {**SOURCE, "status": "stale", "note": "A coleta mais recente falhou."}
        write_snapshot(self.snapshot_path, rows=self.rows, populations=self.populations, source=stale_source)
        detail = accounts.detail(self.city_id, self.snapshot_path)
        self.assertEqual(detail["status"], "stale")
        self.assertEqual(detail["source"]["status"], "stale")
        self.assertEqual(detail["source"]["note"], "A coleta mais recente falhou.")
        self.assertEqual(detail["message"], "A coleta mais recente falhou.")

    def test_missing_source_makes_declaration_unavailable(self):
        write_snapshot(self.snapshot_path, rows=self.rows, populations=self.populations, source=None)
        # The helper normally fills the default source; remove it to model an
        # incomplete source manifest in the stored snapshot.
        snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        snapshot["source"] = None
        self.snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        detail = accounts.detail(self.city_id, self.snapshot_path)
        self.assertEqual(detail["status"], "unavailable")
        self.assertEqual(detail["metrics"], [])
        self.assertFalse(detail["comparison"]["available"])

    def test_city_detail_route_includes_accounts_snapshot(self):
        city_snapshot = {
            "municipalities": [
                {"id": self.city_id, "name": "Cidade teste", "uf": "SP", "population": 10_000},
            ],
        }
        (self.root / "cities.json").write_text(json.dumps(city_snapshot), encoding="utf-8")
        with patch.object(cities, "SNAPSHOTS_PATH", self.root):
            result = cities.detail(self.city_id, self.root / "missing.sqlite3")
        self.assertIn("accounts", result)
        self.assertEqual(result["accounts"]["year"], 2025)
        self.assertEqual(result["accounts"]["status"], "available")


if __name__ == "__main__":
    unittest.main()
