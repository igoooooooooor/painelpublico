import unittest

from ingest import state_tax_revenue as revenue


def item(conta, coluna, valor):
    return {"anexo": "RREO-Anexo 03", "esfera": "E", "conta": conta, "coluna": coluna, "valor": valor}


def full_items(period, value=10.0):
    return [item(conta, coluna, value) for conta in ("ICMS", "IPVA", "ITCD") for coluna in revenue.month_columns(period)]


class StateTaxRevenueTest(unittest.TestCase):
    def test_month_columns_stay_inside_the_report_year(self):
        self.assertEqual(revenue.month_columns(1), {"<MR>": 2, "<MR-1>": 1})
        self.assertEqual(revenue.month_columns(4)["<MR-7>"], 1)
        self.assertNotIn("<MR-8>", revenue.month_columns(4))

    def test_only_own_taxes_of_the_year_are_read_and_twelve_month_totals_are_ignored(self):
        items = full_items(1) + [
            item("ICMS", "TOTAL (ÚLTIMOS 12 MESES)", 999.0),
            item("ICMS", "<MR-5>", 999.0),
            item("Cota-Parte do FPE", "<MR>", 999.0),
        ]
        taxes = revenue.state_taxes(items, 1)
        self.assertEqual(taxes, {"icms": {2: 10.0, 1: 10.0}, "ipva": {2: 10.0, 1: 10.0}, "itcd": {2: 10.0, 1: 10.0}})

    def test_a_report_missing_a_month_is_not_counted_as_zero(self):
        items = [entry for entry in full_items(2) if not (entry["conta"] == "IPVA" and entry["coluna"] == "<MR-3>")]
        self.assertIsNone(revenue.state_taxes(items, 2))

    def test_summary_lists_missing_states_and_only_completes_with_all_27(self):
        by_state = {uf: revenue.state_taxes(full_items(1), 1) for uf in revenue.STATE_IDS.values()}
        complete = revenue.summarize(2026, 1, by_state, "2026-03-31T00:00:00+00:00")
        self.assertEqual(complete["ate"], "2026-02-28")
        self.assertEqual(complete["acumulado"], 27 * 3 * 2 * 10.0)
        self.assertEqual(complete["estadosComDado"], 27)
        self.assertEqual(complete["estadosSemDado"], [])
        by_state["RR"] = None
        partial = revenue.summarize(2026, 1, by_state, "2026-03-31T00:00:00+00:00")
        self.assertEqual(partial["estadosComDado"], 26)
        self.assertEqual(partial["estadosSemDado"], ["RR"])

    def test_latest_complete_falls_back_when_a_state_has_not_delivered(self):
        calls = []

        def fetch(url):
            calls.append(url)
            period = int(url.split("nr_periodo=")[1].split("&")[0])
            state_id = int(url.split("id_ente=")[1])
            if period == 4 and state_id == 14:
                return {"items": []}
            return {"items": full_items(period)}

        period, by_state = revenue.latest_complete(2026, 4, fetch=fetch, pause=0)
        self.assertEqual(period, 3)
        self.assertTrue(all(taxes is not None for taxes in by_state.values()))
        self.assertEqual(len(calls), 54)


if __name__ == "__main__":
    unittest.main()
