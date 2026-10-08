import json
import tempfile
import unittest
from pathlib import Path

from ingest import chamber_housing as housing
from ingest import chamber_mandate_history as history


def presence_row(date, status):
    return (f'<td class="info-data__data-formatada">{date}</td><td>Sessão</td>'
            f'<td class="info-presenca-dia"> {status} </td>')


class MandateHistoryTests(unittest.TestCase):
    def test_presence_is_grouped_by_month_from_mandate_start(self):
        page = "".join([
            presence_row("10/01/2023", "Presença"),
            presence_row("07/02/2023", "Presença"),
            presence_row("08/02/2023", "Ausência"),
            presence_row("09/02/2023", "Ausência justificada"),
            presence_row("03/01/2024", "Presença"),
        ])
        days = history.parse_presence(page, 2023)
        self.assertEqual(len(days), 4)  # o dia de 2024 não pertence à página de 2023
        months = history.presence_months(days)
        self.assertNotIn("2023-01", months)
        self.assertEqual(months["2023-02"], {"days": 3, "present": 1, "absent": 1, "justified": 1})

    def test_office_months_skip_pre_mandate_and_missing_pages(self):
        office = {"status": "partial", "months": {"1": 10.0, "2": 20.5, "11": 0.0}}
        self.assertEqual(history.office_months(office, 2023), {"2023-02": 20.5, "2023-11": 0.0})
        self.assertEqual(history.office_months({"status": "unavailable", "months": {}}, 2024), {})

    def test_offline_build_keeps_absence_and_counts_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            where = history.paths(root)
            where["roster"].parent.mkdir(parents=True)
            where["roster"].write_text(json.dumps({"authorities": [
                {"id": "camara:1", "name": "A", "sourceId": "camara_deputies_current"},
                {"id": "camara:2", "name": "B", "sourceId": "camara_deputies_current"},
            ]}), encoding="utf-8")
            where["office"].mkdir(parents=True)
            (where["office"] / "office-1-2024.json").write_text(json.dumps(
                {"status": "partial", "months": {"11": 5.0}, "sourceUrl": "u"}), encoding="utf-8")
            snapshot = history.build_snapshot(root, years=(2024,), workers=1)
        self.assertEqual(snapshot["profiles"]["camara:1"]["office"], {"2024-11": 5.0})
        self.assertEqual(snapshot["profiles"]["camara:2"]["office"], {})
        self.assertIsNone(snapshot["profiles"]["camara:2"]["sources"]["2024"]["presence"])
        self.assertEqual(snapshot["coverage"], {"2024-11": {"office": 1, "presence": 0}})

    def test_presence_rows_sum_the_mandate_in_the_snapshot_format(self):
        snapshot = {"profiles": {"camara:7": {"name": "A", "presenceReasons": {"Missão Autorizada": 2, "Atestado": 1},
            "presence": {"2023-02": {"days": 10, "present": 7, "absent": 1, "justified": 2},
                         "2026-09": {"days": 5, "present": 4, "absent": 0, "justified": 1}}},
            "camara:8": {"name": "B", "presence": {}}}}
        rows = history.presence_rows(snapshot, {"camara:7": {"party": "PX", "uf": "SP"}})
        self.assertEqual(rows, [{"id": 7, "nome": "A", "partido": "PX", "uf": "SP", "dias": 15, "presente": 11,
                                 "falta": 1, "justificadas": 3, "motivos": [["Missão Autorizada", 2], ["Atestado", 1]],
                                 "inicio": "2023-02", "fim": "2026-09"}])

    def test_years_outside_the_mandate_history_are_rejected(self):
        with self.assertRaises(Exception):
            history.parse_years("2022")


class HousingOutputTests(unittest.TestCase):
    def test_previous_years_do_not_overwrite_the_current_snapshot(self):
        root = Path("/tmp/x")
        self.assertEqual(housing.paths(root, 2026)["output"].name, "chamber-housing.json")
        self.assertEqual(housing.paths(root, 2024)["output"].name, "chamber-housing-2024.json")


if __name__ == "__main__":
    unittest.main()
