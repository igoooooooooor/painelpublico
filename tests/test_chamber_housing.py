import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingest import chamber_housing as housing


def result_row(person_id, *, month=1, year=2026, days=31, allowance="0,00", complement="0,00"):
    numeric_id = person_id.split(":", 1)[-1]
    href = f"57/{year}/{year}/{month:02d}/{month:02d}/{numeric_id}"
    return (
        "<tr>"
        f"<td><a href='{href}'>Deputy {numeric_id}</a></td>"
        f"<td>{days} {'dia' if days == 1 else 'dias'}</td>"
        f"<td>R$ {allowance}</td>"
        f"<td>R$ {complement}</td>"
        "</tr>"
    )


def page_html(rows, total, page=1):
    first = (page - 1) * housing.PAGE_SIZE + 1 if total else 0
    last = min(page * housing.PAGE_SIZE, total) if total else 0
    if total:
        result_label = f"Exibindo resultados de {first} a {last} de {total} encontrados"
    else:
        result_label = "Exibindo 0 resultados encontrados"
    return (
        "<html><body>"
        "<input value='Rua Particular, 123; CPF 12345678901'>"
        f"<p>{result_label}</p><table>{''.join(rows)}</table>"
        "</body></html>"
    )


def parsed_page(rows, total, page=1, *, year=2026, month=1):
    html = page_html(rows, total, page)
    return housing.parse_month_page(
        html,
        housing.query_url(year, month, page),
        year,
        month,
        page,
        hashlib.sha256(html.encode()).hexdigest(),
        "2026-10-07T18:00:00+00:00",
    )


class ChamberHousingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        where = housing.paths(self.root, 2026)
        where["roster"].parent.mkdir(parents=True, exist_ok=True)
        where["roster"].write_text(json.dumps({"authorities": [
            {"id": "camara:100", "name": "Deputy One", "sourceId": "camara_deputies_current"},
            {"id": "camara:200", "name": "Deputy Two", "sourceId": "camara_deputies_current"},
            {"id": "camara:300", "name": "Deputy Missing", "sourceId": "camara_deputies_current"},
            {"id": "senado:400", "name": "Senator", "sourceId": "senado_current"},
            {"id": "camara:500", "name": "Former Deputy", "sourceId": "old_roster"},
        ]}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def save_page(self, page):
        where = housing.paths(self.root, page["year"])
        housing._save_page(where["cache_dir"], page)

    def test_monthly_rows_preserve_explicit_zero_and_positive_complement(self):
        page = parsed_page([
            result_row("camara:100", days=0, allowance="4.253,00", complement="1.747,00"),
            result_row("camara:200", days=31, allowance="0,00", complement="0,00"),
        ], total=2)
        self.assertEqual(page["records"], [
            {
                "id": "camara:100",
                "functionalPropertyDays": 0,
                "housingAllowanceCents": 425300,
                "quotaComplementCents": 174700,
            },
            {
                "id": "camara:200",
                "functionalPropertyDays": 31,
                "housingAllowanceCents": 0,
                "quotaComplementCents": 0,
            },
        ])
        self.assertEqual(page["period"], "2026-01")
        self.assertEqual(page["source"]["url"], housing.query_url(2026, 1, 1))

    def test_snapshot_keeps_missing_person_null_and_excludes_private_html(self):
        page = parsed_page([
            result_row("camara:100", allowance="4.253,00", complement="1.747,00"),
            result_row("camara:200", allowance="0,00", complement="0,00"),
        ], total=2)
        self.save_page(page)

        snapshot, failures = housing.build_snapshot(self.root, 2026, (1,))
        self.assertEqual(failures, {})
        self.assertEqual(snapshot["profiles"]["camara:100"]["months"]["2026-01"]["quotaComplementCents"], 174700)
        self.assertEqual(snapshot["profiles"]["camara:200"]["months"]["2026-01"]["housingAllowanceCents"], 0)
        missing = snapshot["profiles"]["camara:300"]["months"]["2026-01"]
        self.assertEqual(missing["status"], "unavailable")
        self.assertIsNone(missing["housingAllowanceCents"])
        self.assertIsNone(missing["quotaComplementCents"])
        self.assertIsNone(missing["functionalPropertyDays"])

        cache_text = housing.paths(self.root, 2026)["cache_dir"].joinpath("01", "page-1.json").read_text(encoding="utf-8")
        snapshot_text = housing.paths(self.root, 2026)["output"].read_text(encoding="utf-8")
        for private_value in ("Rua Particular", "12345678901"):
            self.assertNotIn(private_value, cache_text)
            self.assertNotIn(private_value, snapshot_text)

    def test_absent_pagination_does_not_turn_unobserved_people_into_zeros(self):
        rows = [result_row(f"camara:{1000 + index}") for index in range(20)]
        rows[0] = result_row("camara:100", allowance="0,00", complement="0,00")
        page = parsed_page(rows, total=21)
        self.save_page(page)

        snapshot, _failures = housing.build_snapshot(self.root, 2026, (1,))
        month = snapshot["coverage"]["months"]["2026-01"]
        self.assertEqual(month["status"], "partial")
        self.assertEqual(month["pagesCollected"], 1)
        observed = snapshot["profiles"]["camara:100"]["months"]["2026-01"]
        self.assertEqual(observed["housingAllowanceCents"], 0)
        absent = snapshot["profiles"]["camara:300"]["months"]["2026-01"]
        self.assertEqual(absent["status"], "unavailable")
        self.assertIsNone(absent["housingAllowanceCents"])

    def test_wrong_query_period_and_wrong_row_period_are_rejected(self):
        html = page_html([result_row("camara:100")], total=1)
        wrong_query = housing.query_url(2026, 2, 1)
        with self.assertRaises(ValueError):
            housing.parse_month_page(
                html, wrong_query, 2026, 1, 1, hashlib.sha256(html.encode()).hexdigest()
            )

        wrong_row = page_html([result_row("camara:100", month=2)], total=1)
        with self.assertRaises(ValueError):
            housing.parse_month_page(
                wrong_row,
                housing.query_url(2026, 1, 1),
                2026,
                1,
                1,
                hashlib.sha256(wrong_row.encode()).hexdigest(),
            )

    def test_resumes_from_atomic_page_cache_and_skips_successful_page(self):
        first_rows = [result_row(f"camara:{1000 + index}") for index in range(20)]
        first_rows[0] = result_row("camara:100", allowance="0,00", complement="0,00")
        page_one = parsed_page(first_rows, total=21, page=1)
        self.save_page(page_one)
        page_two = parsed_page([result_row("camara:200", allowance="1,00", complement="0,00")], total=21, page=2)
        cache_path = housing.paths(self.root, 2026)["cache_dir"] / "01" / "page-2.json"

        with patch.object(housing, "_fetch_page", return_value=page_two) as fetch:
            snapshot, failures = housing.build_snapshot(self.root, 2026, (1,), collect=True)
        self.assertEqual(failures, {})
        fetch.assert_called_once_with(2026, 1, 2)
        self.assertTrue(cache_path.exists())
        self.assertEqual(snapshot["coverage"]["months"]["2026-01"]["status"], "available")
        self.assertEqual(snapshot["profiles"]["camara:200"]["months"]["2026-01"]["housingAllowanceCents"], 100)
        second_person = snapshot["profiles"]["camara:200"]["months"]["2026-01"]
        self.assertEqual(second_person["period"], "2026-01")
        self.assertEqual(second_person["source"]["url"], housing.query_url(2026, 1, 2))
        self.assertEqual(second_person["source"]["sha256"], page_two["sha256"])
        self.assertEqual(second_person["source"]["fetchedAt"], page_two["fetchedAt"])

        with patch.object(housing, "_fetch_page", side_effect=AssertionError("cached pages should be reused")) as fetch:
            housing.build_snapshot(self.root, 2026, (1,), collect=True)
        fetch.assert_not_called()

    def test_refresh_rejects_missing_collect_flag(self):
        with self.assertRaises(SystemExit) as raised:
            housing.main(["--refresh"])
        self.assertEqual(raised.exception.code, 2)
        with self.assertRaisesRegex(ValueError, "--refresh requires --collect"):
            housing.build_snapshot(self.root, 2026, (1,), refresh=True)

    def test_refresh_failure_preserves_good_pages_and_marks_prior_values_stale(self):
        old_rows = [result_row(f"camara:{1000 + index}") for index in range(20)]
        old_rows[0] = result_row("camara:100", allowance="4,00", complement="1,00")
        old_page_one = parsed_page(old_rows, total=21, page=1)
        old_page_two = parsed_page(
            [result_row("camara:200", allowance="2,00", complement="0,00")],
            total=21,
            page=2,
        )
        self.save_page(old_page_one)
        self.save_page(old_page_two)
        old_snapshot, _failures = housing.build_snapshot(self.root, 2026, (1,))
        old_observation = old_snapshot["profiles"]["camara:100"]["months"]["2026-01"]
        cache_dir = housing.paths(self.root, 2026)["cache_dir"]
        old_cached_pages = {
            page: housing._read_json(housing._cache_path(cache_dir, 2026, 1, page))
            for page in (1, 2)
        }

        changed_rows = list(old_rows)
        changed_rows[0] = result_row("camara:100", allowance="99,00", complement="88,00")
        refreshed_page_one = parsed_page(changed_rows, total=21, page=1)
        inconsistent_page_two = parsed_page(
            [
                result_row("camara:200", allowance="22,00", complement="0,00"),
                result_row("camara:300", allowance="33,00", complement="0,00"),
            ],
            total=22,
            page=2,
        )
        with patch.object(
            housing,
            "_fetch_page",
            side_effect=[refreshed_page_one, inconsistent_page_two],
        ) as fetch:
            snapshot, failures = housing.build_snapshot(
                self.root, 2026, (1,), collect=True, refresh=True
            )

        self.assertEqual(fetch.call_args_list, [
            unittest.mock.call(2026, 1, 1),
            unittest.mock.call(2026, 1, 2),
        ])
        self.assertEqual(failures, {"2026-01": "InconsistentPageTotal"})
        for page, old_cached in old_cached_pages.items():
            self.assertEqual(
                housing._read_json(housing._cache_path(cache_dir, 2026, 1, page)),
                old_cached,
            )

        stale = snapshot["profiles"]["camara:100"]["months"]["2026-01"]
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["housingAllowanceCents"], old_observation["housingAllowanceCents"])
        self.assertEqual(stale["source"]["fetchedAt"], old_observation["source"]["fetchedAt"])
        self.assertEqual(stale["source"]["sha256"], old_observation["source"]["sha256"])
        self.assertEqual(stale["source"]["status"], "stale")
        self.assertEqual(stale["source"]["attemptStatus"], "failed")
        self.assertEqual(stale["source"]["attemptError"], "InconsistentPageTotal")
        self.assertEqual(stale["source"]["failedPage"], 2)
        self.assertNotEqual(stale["source"]["attemptedAt"], stale["source"]["fetchedAt"])
        self.assertFalse((cache_dir / "01" / "refresh-staging").exists())

        with patch.object(housing, "_fetch_page", side_effect=AssertionError("offline rebuild must not fetch")):
            offline_snapshot, offline_failures = housing.build_snapshot(self.root, 2026, (1,))
        self.assertEqual(offline_failures, {})
        still_stale = offline_snapshot["profiles"]["camara:100"]["months"]["2026-01"]
        self.assertEqual(still_stale["status"], "stale")
        self.assertEqual(still_stale["housingAllowanceCents"], stale["housingAllowanceCents"])
        self.assertEqual(still_stale["source"]["fetchedAt"], stale["source"]["fetchedAt"])
        self.assertEqual(still_stale["source"]["sha256"], stale["source"]["sha256"])
        self.assertEqual(still_stale["source"]["attemptedAt"], stale["source"]["attemptedAt"])
        self.assertEqual(still_stale["source"]["attemptError"], "InconsistentPageTotal")

    def test_refresh_resumes_staged_pages_and_publishes_one_generation(self):
        old_rows = [result_row(f"camara:{1000 + index}") for index in range(20)]
        old_rows[0] = result_row("camara:100", allowance="4,00", complement="1,00")
        old_page_one = parsed_page(old_rows, total=21, page=1)
        old_page_two = parsed_page(
            [result_row("camara:200", allowance="2,00", complement="0,00")],
            total=21,
            page=2,
        )
        self.save_page(old_page_one)
        self.save_page(old_page_two)
        housing.build_snapshot(self.root, 2026, (1,))
        cache_dir = housing.paths(self.root, 2026)["cache_dir"]

        fresh_rows = list(old_rows)
        fresh_rows[0] = result_row("camara:100", allowance="11,00", complement="0,00")
        fresh_page_one = parsed_page(fresh_rows, total=21, page=1)
        fresh_page_two = parsed_page(
            [result_row("camara:200", allowance="22,00", complement="0,00")],
            total=21,
            page=2,
        )
        with patch.object(
            housing,
            "_fetch_page",
            side_effect=[fresh_page_one, OSError("temporary network failure")],
        ) as fetch:
            first_snapshot, first_failures = housing.build_snapshot(
                self.root, 2026, (1,), collect=True, refresh=True
            )
        self.assertEqual(first_failures, {"2026-01": "OSError"})
        self.assertEqual(fetch.call_args_list, [
            unittest.mock.call(2026, 1, 1),
            unittest.mock.call(2026, 1, 2),
        ])
        stage_dir = housing._staging_dir(cache_dir, 2026, 1)
        self.assertEqual(
            housing._read_json(housing._page_file(stage_dir, 1))["sha256"],
            fresh_page_one["sha256"],
        )
        self.assertFalse(housing._page_file(stage_dir, 2).exists())
        self.assertEqual(
            housing._read_json(housing._cache_path(cache_dir, 2026, 1, 1))["sha256"],
            old_page_one["sha256"],
        )
        self.assertEqual(
            housing._read_json(housing._cache_path(cache_dir, 2026, 1, 2))["sha256"],
            old_page_two["sha256"],
        )
        stale = first_snapshot["profiles"]["camara:100"]["months"]["2026-01"]
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["housingAllowanceCents"], 400)
        self.assertEqual(stale["source"]["fetchedAt"], old_page_one["fetchedAt"])
        self.assertEqual(stale["source"]["attemptError"], "OSError")

        with patch.object(housing, "_fetch_page", return_value=fresh_page_two) as fetch:
            snapshot, failures = housing.build_snapshot(
                self.root, 2026, (1,), collect=True, refresh=True
            )
        fetch.assert_called_once_with(2026, 1, 2)
        self.assertEqual(failures, {})
        self.assertFalse(stage_dir.exists())
        active_dir = housing._active_page_dir(cache_dir, 2026, 1)
        self.assertNotEqual(active_dir, cache_dir / "01")
        self.assertEqual(
            housing._read_json(housing._page_file(active_dir, 1))["sha256"],
            fresh_page_one["sha256"],
        )
        self.assertEqual(
            housing._read_json(housing._page_file(active_dir, 2))["sha256"],
            fresh_page_two["sha256"],
        )
        self.assertEqual(
            snapshot["profiles"]["camara:100"]["months"]["2026-01"]["housingAllowanceCents"],
            1100,
        )
        self.assertEqual(
            snapshot["profiles"]["camara:200"]["months"]["2026-01"]["housingAllowanceCents"],
            2200,
        )
        fresh_observation = snapshot["profiles"]["camara:100"]["months"]["2026-01"]
        self.assertEqual(fresh_observation["status"], "available")
        self.assertEqual(fresh_observation["source"]["sha256"], fresh_page_one["sha256"])
        self.assertNotIn("attemptStatus", fresh_observation["source"])

    def test_successful_refresh_uses_and_commits_only_fresh_pages(self):
        old_page = parsed_page(
            [result_row("camara:100", allowance="1,00", complement="0,00")],
            total=1,
        )
        refreshed_page = parsed_page(
            [result_row("camara:100", allowance="2,00", complement="0,00")],
            total=1,
        )
        self.save_page(old_page)
        with patch.object(housing, "_fetch_page", return_value=refreshed_page) as fetch:
            snapshot, failures = housing.build_snapshot(
                self.root, 2026, (1,), collect=True, refresh=True
            )

        fetch.assert_called_once_with(2026, 1, 1)
        self.assertEqual(failures, {})
        observation = snapshot["profiles"]["camara:100"]["months"]["2026-01"]
        self.assertEqual(observation["housingAllowanceCents"], 200)
        cache_dir = housing.paths(self.root, 2026)["cache_dir"]
        cache = housing._read_json(
            housing._page_file(housing._active_page_dir(cache_dir, 2026, 1), 1)
        )
        self.assertEqual(cache["sha256"], refreshed_page["sha256"])

    def test_failure_in_one_month_does_not_block_another_month(self):
        january = parsed_page([result_row("camara:100", allowance="0,00", complement="0,00")], total=1, month=1)
        with patch.object(housing, "_fetch_page", side_effect=[january, OSError("offline")]):
            snapshot, failures = housing.build_snapshot(
                self.root, 2026, (1, 2), collect=True, limit=1
            )
        self.assertEqual(failures, {"2026-02": "OSError"})
        self.assertEqual(snapshot["profiles"]["camara:100"]["months"]["2026-01"]["housingAllowanceCents"], 0)
        self.assertEqual(snapshot["profiles"]["camara:100"]["months"]["2026-02"]["status"], "unavailable")

    def test_duplicate_person_rows_are_conflicts_and_do_not_use_last_value(self):
        first_rows = [result_row(f"camara:{1000 + index}") for index in range(20)]
        first_rows[0] = result_row("camara:100", allowance="4,00", complement="1,00")
        page_one = parsed_page(first_rows, total=21, page=1)
        page_two = parsed_page(
            [result_row("camara:100", allowance="9,00", complement="8,00")], total=21, page=2
        )
        self.save_page(page_one)
        self.save_page(page_two)

        snapshot, _failures = housing.build_snapshot(self.root, 2026, (1,))
        conflict = snapshot["profiles"]["camara:100"]["months"]["2026-01"]
        self.assertEqual(conflict["status"], "partial")
        self.assertIsNone(conflict["housingAllowanceCents"])
        self.assertIsNone(conflict["quotaComplementCents"])
        self.assertEqual(snapshot["coverage"]["months"]["2026-01"]["duplicateRows"], 1)
        self.assertEqual(snapshot["coverage"]["months"]["2026-01"]["status"], "partial")

    def test_partial_month_rebuild_preserves_other_months_and_previous_observations(self):
        old_january = {
            "period": "2026-01",
            "status": "available",
            "housingAllowanceCents": 9900,
            "quotaComplementCents": 8800,
            "functionalPropertyDays": 31,
            "source": {"label": "old source", "url": "https://example.test/old", "status": "available"},
        }
        old_february = {
            "period": "2026-02",
            "status": "available",
            "housingAllowanceCents": 700,
            "quotaComplementCents": 600,
            "functionalPropertyDays": 28,
            "source": {"label": "old source", "url": "https://example.test/feb", "status": "available"},
        }
        output = housing.paths(self.root, 2026)["output"]
        housing._atomic_json(output, {
            "year": 2026,
            "coverage": {"rosterCount": 3, "months": {"2026-02": {"status": "available"}}},
            "profiles": {"camara:300": {"months": {"2026-01": old_january, "2026-02": old_february}}},
        })
        first_page_rows = [result_row(f"camara:{1000 + index}") for index in range(20)]
        first_page_rows[0] = result_row("camara:100", allowance="0,00", complement="0,00")
        self.save_page(parsed_page(first_page_rows, total=21, page=1))

        snapshot, _failures = housing.build_snapshot(self.root, 2026, (1,))
        previous = snapshot["profiles"]["camara:300"]["months"]
        self.assertEqual(previous["2026-02"], old_february)
        self.assertEqual(previous["2026-01"]["status"], "stale")
        self.assertEqual(previous["2026-01"]["housingAllowanceCents"], 9900)
        self.assertIn("2026-02", snapshot["coverage"]["months"])

    def test_month_cli_parser_accepts_explicit_month_list(self):
        self.assertEqual(housing.parse_months("1,2,9"), (1, 2, 9))
        with self.assertRaises(housing.argparse.ArgumentTypeError):
            housing.parse_months("1,13")


if __name__ == "__main__":
    unittest.main()
