import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ingest import chamber_service as service


class ChamberServiceTests(unittest.TestCase):
    def test_parse_history_keeps_only_official_exercise_dates(self):
        profile_id = "camara:74581"
        final_url = "https://www.camara.leg.br/SitCamaraWS/Deputados.asmx/ObterDetalhesDeputado?ideCadastro=74581&numLegislatura=57"
        body = b"""<?xml version='1.0' encoding='utf-8'?>
        <Deputados><Deputado>
          <email>public-contact@example.invalid</email>
          <nomeCivil>Gilmar Machado</nomeCivil>
          <periodosExercicio><periodoExercicio>
            <situacaoExercicio>Efetivado</situacaoExercicio>
            <dataInicio>15/09/2026</dataInicio><dataFim />
          </periodoExercicio></periodosExercicio>
        </Deputado></Deputados>"""

        history = service.parse_history_xml(body, profile_id, final_url, "2026-10-07T12:00:00+00:00")

        self.assertEqual(history["profileId"], profile_id)
        self.assertEqual(history["periods"], [{"startDate": "2026-09-15", "endDate": None}])
        self.assertEqual(history["source"]["sha256"], hashlib.sha256(body).hexdigest())
        serialized = json.dumps(history, ensure_ascii=False)
        self.assertNotIn("public-contact", serialized)
        self.assertNotIn("Gilmar Machado", serialized)

    def test_parse_history_merges_overlapping_duplicate_periods(self):
        body = b"""<Deputados><Deputado><periodosExercicio>
          <periodoExercicio><dataInicio>01/02/2023</dataInicio><dataFim>05/07/2023</dataFim></periodoExercicio>
          <periodoExercicio><dataInicio>01/02/2023</dataInicio><dataFim>01/01/2025</dataFim></periodoExercicio>
          <periodoExercicio><dataInicio>31/03/2026</dataInicio><dataFim /></periodoExercicio>
        </periodosExercicio></Deputado></Deputados>"""
        history = service.parse_history_xml(body, "camara:154178")
        self.assertEqual(history["periods"], [
            {"startDate": "2023-02-01", "endDate": "2025-01-01"},
            {"startDate": "2026-03-31", "endDate": None},
        ])
        self.assertEqual(service._month_observation(history, 2026, 1)["status"], "outside_mandate")
        self.assertEqual(service._month_observation(history, 2026, 3)["daysInOffice"], 1)

    def test_parse_history_rejects_invalid_dates(self):
        body = b"""<Deputados><Deputado><periodosExercicio>
          <periodoExercicio><dataInicio>31/02/2026</dataInicio><dataFim /></periodoExercicio>
        </periodosExercicio></Deputado></Deputados>"""
        with self.assertRaisesRegex(service.SourceError, "invalid date"):
            service.parse_history_xml(body, "camara:100")

    def test_source_url_requires_the_requested_profile_and_current_legislature(self):
        url = service.source_url("camara:74581")
        self.assertTrue(service._validate_source_url(url, "camara:74581"))
        self.assertFalse(service._validate_source_url(url, "camara:100"))
        self.assertFalse(service._validate_source_url(
            url.replace("numLegislatura=57", "numLegislatura=56"), "camara:74581"
        ))

    def test_actual_periods_count_inclusive_days_and_keep_gaps_outside(self):
        history = {
            "fetchedAt": "2026-10-07T12:00:00+00:00",
            "source": {
                "label": service.SOURCE_LABEL,
                "url": service.source_url("camara:100"),
                "sha256": "a" * 64,
            },
            "periods": [
                {"startDate": "2026-01-01", "endDate": "2026-01-15"},
                {"startDate": "2026-01-20", "endDate": None},
            ],
        }

        january = service._month_observation(history, 2026, 1)
        february = service._month_observation(history, 2026, 2)
        self.assertEqual((january["status"], january["daysInOffice"]), ("in_office", 27))
        self.assertEqual(january["exercisePeriods"], [
            {"startDate": "2026-01-01", "endDate": "2026-01-15"},
            {"startDate": "2026-01-20", "endDate": None},
        ])
        self.assertEqual((february["status"], february["daysInOffice"]), ("in_office", 28))

        gilmar_history = {**history, "periods": [
            {"startDate": "2026-09-15", "endDate": None},
        ]}
        july = service._month_observation(gilmar_history, 2026, 7)
        september = service._month_observation(gilmar_history, 2026, 9)
        self.assertEqual((july["status"], july["daysInOffice"]), ("outside_mandate", 0))
        self.assertEqual((september["status"], september["daysInOffice"]), ("in_office", 16))

    def test_no_periods_or_missing_cache_stays_unknown(self):
        empty_history = {
            "fetchedAt": "2026-10-07T12:00:00+00:00",
            "source": {
                "label": service.SOURCE_LABEL,
                "url": service.source_url("camara:100"),
                "sha256": "a" * 64,
            },
            "periods": [],
        }
        observation = service._month_observation(empty_history, 2026, 1)
        missing = service._month_observation(None, 2026, 1, "MissingCache")
        self.assertEqual(observation["status"], "unknown")
        self.assertIsNone(observation["daysInOffice"])
        self.assertEqual(missing["status"], "unknown")
        self.assertIsNone(missing["daysInOffice"])

    def test_offline_snapshot_uses_minimized_cache_for_roster(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roster_path = service.paths(root)["roster"]
            roster_path.parent.mkdir(parents=True)
            roster_path.write_text(json.dumps({"authorities": [{
                "id": "camara:74581",
                "name": "Gilmar Machado",
                "role": "deputado",
                "sourceId": service.ROSTER_SOURCE_ID,
            }]}), encoding="utf-8")
            history = {
                "schemaVersion": service.SCHEMA_VERSION,
                "profileId": "camara:74581",
                "fetchedAt": "2026-10-07T12:00:00+00:00",
                "source": {
                    "label": service.SOURCE_LABEL,
                    "url": service.source_url("camara:74581"),
                    "sha256": "a" * 64,
                },
                "periods": [{"startDate": "2026-09-15", "endDate": None}],
            }
            service._atomic_json(service._cache_path(service.paths(root)["cache_dir"], "camara:74581"), history)

            snapshot, failures = service.build_snapshot(root, months=(1, 7, 9))

            self.assertEqual(failures, {})
            self.assertEqual(snapshot["coverage"]["months"]["2026-01"]["statusCounts"], {
                "in_office": 0, "outside_mandate": 1, "unknown": 0,
            })
            months = snapshot["profiles"]["camara:74581"]["months"]
            self.assertEqual(months["2026-07"]["daysInOffice"], 0)
            self.assertEqual(months["2026-09"]["daysInOffice"], 16)
            self.assertTrue(service.paths(root)["output"].exists())

    def test_refresh_requires_collect(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "--refresh requires --collect"):
                service.build_snapshot(Path(directory), refresh=True)


if __name__ == "__main__":
    unittest.main()
