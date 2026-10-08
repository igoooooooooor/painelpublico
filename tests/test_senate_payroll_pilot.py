import json
from pathlib import Path
import tempfile
import unittest

from ingest import senate_payroll_pilot as pilot


CSV_FIELDS = pilot.EXPECTED_FIELDS


class FakeResponse:
    def __init__(self, lines):
        self.lines = iter(lines)
        self.read_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def readline(self, _limit):
        self.read_calls += 1
        return next(self.lines, b"")


def encoded_line(value):
    return (value + "\r\n").encode("cp1252")


class SenatePayrollPilotTests(unittest.TestCase):
    def test_fetch_reads_only_metadata_and_header_lines(self):
        private_row = "PRIVATE_STAFF_SENTINEL;PRIVATE_STAFF_SENTINEL;PRIVATE_STAFF_SENTINEL"
        response = FakeResponse([
            encoded_line("ÚLTIMA ATUALIZAÇÃO;30/09/2026 05:00"),
            encoded_line(";".join(CSV_FIELDS)),
            encoded_line(private_row),
        ])

        schema = pilot.fetch_schema(
            opener=lambda _request, timeout: response,
            fetched_at="2026-10-07T12:00:00+00:00",
        )

        self.assertEqual(response.read_calls, 2)
        self.assertEqual(schema["fields"], CSV_FIELDS)
        self.assertEqual(schema["sourceUpdatedAt"], "2026-09-30T05:00")
        self.assertNotIn("NOME", schema["fields"])
        self.assertNotIn("PRIVATE_STAFF_SENTINEL", json.dumps(schema))

    def test_unrecognized_second_line_is_rejected_without_writing_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roster_path = root / pilot.ROSTER_PATH
            roster_path.parent.mkdir(parents=True)
            roster_path.write_text(json.dumps({"authorities": []}), encoding="utf-8")
            cache_path = root / pilot.DEFAULT_CACHE
            response = FakeResponse([
                encoded_line("ÚLTIMA ATUALIZAÇÃO;30/09/2026 05:00"),
                encoded_line("PRIVATE_STAFF_SENTINEL;PRIVATE_STAFF_SENTINEL"),
                encoded_line("PRIVATE_STAFF_SENTINEL;PRIVATE_STAFF_SENTINEL"),
            ])

            with self.assertRaises(pilot.PilotError):
                pilot.run(root=root, collect=True, opener=lambda _request, timeout: response)

            self.assertEqual(response.read_calls, 2)
            self.assertFalse(cache_path.exists())

    def test_header_projection_cache_never_accepts_payroll_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "csv-schema.json"
            schema = {
                "schemaVersion": 1,
                "sourceUrl": pilot.CSV_URL,
                "competence": pilot.COMPETENCE,
                "capturedAt": "2026-10-07T12:00:00+00:00",
                "sourceUpdatedAt": "2026-09-30T05:00",
                "fields": CSV_FIELDS,
            }
            pilot._write_schema_cache(cache_path, schema)
            self.assertEqual(pilot._read_schema_cache(cache_path), schema)

            cache_path.write_text(json.dumps({**schema, "rows": [{"private": "value"}]}), encoding="utf-8")
            self.assertIsNone(pilot._read_schema_cache(cache_path))

    def test_snapshot_records_bounded_roster_and_stops_without_person_month_linkage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_path = root / "csv-schema.json"
            output_path = root / "senate-payroll-pilot.json"
            pilot._write_schema_cache(cache_path, {
                "schemaVersion": 1,
                "sourceUrl": pilot.CSV_URL,
                "competence": pilot.COMPETENCE,
                "capturedAt": "2026-10-07T12:00:00+00:00",
                "sourceUpdatedAt": "2026-09-30T05:00",
                "fields": CSV_FIELDS,
            })
            roster = {"authorities": [
                {
                    "id": f"senado:{number}",
                    "name": f"Public Senator {number}",
                    "role": "senador",
                    "sourceId": pilot.SOURCE_ID,
                }
                for number in range(1, 13)
            ] + [
                {
                    "id": "senado:99",
                    "name": "Historical Senator",
                    "role": "senador",
                    "sourceId": "senado_ceaps",
                }
            ]}

            snapshot, stats = pilot.build_snapshot(
                root=root,
                output=output_path,
                cache_path=cache_path,
                roster_payload=roster,
            )

            self.assertEqual(stats, {"selected": 10, "linked": 0, "verified": 0})
            self.assertEqual(snapshot["status"], "unavailable")
            self.assertEqual(snapshot["pilot"]["selectedSenatorCount"], 10)
            self.assertEqual(snapshot["pilot"]["linkedSenatorCount"], 0)
            self.assertEqual(snapshot["pilot"]["verifiedPersonMonthCount"], 0)
            self.assertEqual(snapshot["pilot"]["individualConsultationCount"], 0)
            self.assertEqual(snapshot["pilot"]["individualConsultationStatus"], "not_attempted")
            self.assertEqual(snapshot["source"]["fields"], CSV_FIELDS)
            serialized = output_path.read_text(encoding="utf-8")
            self.assertNotIn("Public Senator", serialized)
            self.assertNotIn("Historical Senator", serialized)
            self.assertNotIn("rows", snapshot["source"])

    def test_offline_run_does_not_use_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_path = root / pilot.DEFAULT_CACHE
            pilot._write_schema_cache(cache_path, {
                "schemaVersion": 1,
                "sourceUrl": pilot.CSV_URL,
                "competence": pilot.COMPETENCE,
                "capturedAt": "2026-10-07T12:00:00+00:00",
                "sourceUpdatedAt": None,
                "fields": CSV_FIELDS,
            })
            (root / pilot.ROSTER_PATH).parent.mkdir(parents=True)
            (root / pilot.ROSTER_PATH).write_text(json.dumps({"authorities": []}), encoding="utf-8")

            def fail_if_called(*_args, **_kwargs):
                raise AssertionError("offline run attempted network access")

            snapshot, stats = pilot.run(root=root, opener=fail_if_called)

            self.assertEqual(snapshot["status"], "unavailable")
            self.assertEqual(stats["selected"], 0)


if __name__ == "__main__":
    unittest.main()
