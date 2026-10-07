import csv
import gzip
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from ingest import amendments


def source_row(
    amendment_id="A-1",
    year="2026",
    amendment_type="Emenda Individual - Transferências com Finalidade Definida",
    author_id="001",
    author_name="Autora",
    city_id="3550308",
    committed="100,00",
    paid="50,00",
    restos="0,00",
):
    return {
        "Código da Emenda": amendment_id,
        "Ano da Emenda": year,
        "Tipo de Emenda": amendment_type,
        "Código do Autor da Emenda": author_id,
        "Nome do Autor da Emenda": author_name,
        "Localidade de aplicação do recurso": "SAO PAULO - SP",
        "Código Município IBGE": city_id,
        "Município": "SAO PAULO",
        "UF": "SP",
        "Valor Empenhado": committed,
        "Valor Pago": paid,
        "Valor Restos A Pagar Pagos": restos,
    }


def write_cache(path, rows):
    amendments._write_gzip_csv(path, amendments.SOURCE_FIELDS, rows)


def write_city_catalog(root, cities):
    city_path = amendments.paths(root)["cities"]
    city_path.parent.mkdir(parents=True, exist_ok=True)
    city_path.write_text(json.dumps({"municipalities": cities}), encoding="utf-8")


def make_zip(rows, *, extra_member=None, extra_header=()):
    table = io.StringIO()
    fields = list(amendments.SOURCE_FIELDS) + list(extra_header)
    writer = csv.DictWriter(table, fields, delimiter=";", extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(amendments.CSV_MEMBER, table.getvalue().encode("cp1252"))
        if extra_member is not None:
            archive.writestr("PorFavorecido.csv", extra_member.encode("cp1252"))
    return payload.getvalue()


class AmendmentsIngestTests(unittest.TestCase):
    def test_amounts_use_strict_decimal_cents_and_preserve_adjustments(self):
        self.assertEqual(amendments._amount_cents("1.234,56"), 123456)
        self.assertEqual(amendments._amount_cents("-25,00"), -2500)
        self.assertEqual(amendments._amount_cents("0,00"), 0)
        self.assertIsNone(amendments._amount_cents(""))
        self.assertIsNone(amendments._amount_cents("NaN"))
        self.assertIsNone(amendments._amount_cents("Infinity"))
        self.assertIsNone(amendments._amount_cents("1,2345"))
        self.assertIsNone(amendments._amount_cents("1,"))

    def test_zip_projects_allowlisted_main_member_and_never_caches_other_members(self):
        row = source_row()
        row.update({"CPF do favorecido": "private-column-sentinel", "E-mail": "private-email-sentinel"})
        zipped = make_zip(
            [row],
            extra_member="CPF;Nome\nprivate-recipient-sentinel;Pessoa privada\n",
            extra_header=("CPF do favorecido", "E-mail"),
        )
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "emendas.csv.gz"
            manifest = amendments._project_zip_bytes(
                zipped, cache, fetched_at="2026-10-07T12:00:00+00:00", last_modified="Thu, 01 Oct 2026 20:45:39 GMT"
            )
            with gzip.open(cache, "rt", encoding="cp1252") as stream:
                cached_text = stream.read()
        self.assertEqual(manifest["retained_rows"], 1)
        self.assertEqual(manifest["last_modified"], "Thu, 01 Oct 2026 20:45:39 GMT")
        self.assertEqual(manifest["retained_header_fields"], list(amendments.SOURCE_FIELDS))
        for secret in ("private-column-sentinel", "private-email-sentinel", "private-recipient-sentinel"):
            self.assertNotIn(secret, cached_text)

    def test_empty_or_malformed_archive_cannot_replace_a_useful_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "emendas.csv.gz"
            write_cache(cache, [source_row()])
            previous = cache.read_bytes()
            empty_zip = make_zip([])
            with self.assertRaisesRegex(ValueError, "empty CSV|no rows"):
                amendments._project_zip_bytes(empty_zip, cache)
            self.assertEqual(cache.read_bytes(), previous)

    def test_offline_snapshot_aggregates_splits_and_keeps_unknowns_out_of_cities(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            where = amendments.paths(root)
            write_city_catalog(root, [
                {"id": "3550308", "name": "São Paulo", "uf": "SP"},
                {"id": "3304557", "name": "Rio de Janeiro", "uf": "RJ"},
            ])
            where["legacy_cache"].parent.mkdir(parents=True, exist_ok=True)
            rows = [
                source_row("A-1", author_id="002", author_name="Zeta", committed="100,00", paid="10,00", restos="0,00"),
                # Same code + municipality is a dimensional split and must sum.
                source_row("A-1", author_id="002", author_name="Zeta", committed="50,00", paid="5,00", restos="1,00"),
                source_row(
                    "B-2", amendment_type=amendments.SPECIAL_TRANSFER_TYPE, author_id="001", author_name="Alpha",
                    committed="-25,00", paid="0,00", restos="2,50",
                ),
                source_row("C-3", author_id="003", author_name="Invalid", committed="", paid="0,25", restos="0,50"),
                source_row("U-1", city_id="9999999", committed="1,00", paid="0,20", restos="0,00"),
                source_row("M-1", city_id="Sem informação", committed="2,00", paid="0,30", restos="0,00"),
                source_row("OLD", year="2025"),
            ]
            write_cache(where["legacy_cache"], rows)
            where["legacy_manifest"].write_text(json.dumps({
                "status": "available", "retained_rows": len(rows),
                "last_modified": "Thu, 01 Oct 2026 20:45:39 GMT",
            }), encoding="utf-8")
            with patch.object(amendments, "_download_and_project", side_effect=AssertionError("offline build attempted network")):
                snapshot = amendments.build_snapshot(root)

        sp = snapshot["municipalities"]["3550308"]
        rio = snapshot["municipalities"]["3304557"]
        self.assertEqual(sp["status"], "partial")
        self.assertEqual(sp["recordCount"], 4)
        self.assertIsNone(sp["totals"]["committedCents"])
        self.assertEqual(sp["totals"]["paidCents"], 1525)
        self.assertEqual(sp["totals"]["restosPaidCents"], 400)
        self.assertEqual(sp["records"][0]["id"], "A-1")
        ordinary = next(record for record in sp["records"] if record["id"] == "A-1")
        self.assertEqual(ordinary["committedCents"], 15000)
        self.assertEqual(ordinary["paidCents"], 1500)
        self.assertEqual(sp["specialTransfers"]["identified"], True)
        self.assertEqual(sp["specialTransfers"]["recordCount"], 1)
        self.assertEqual(sp["specialTransfers"]["totals"], {
            "committedCents": -2500, "paidCents": 0, "restosPaidCents": 250,
        })
        self.assertEqual(next(record for record in sp["records"] if record["id"] == "C-3")["committedCents"], None)
        self.assertEqual(next(record for record in sp["records"] if record["id"] == "C-3")["paidCents"], 25)
        self.assertEqual(next(record for record in sp["records"] if record["id"] == "C-3")["restosPaidCents"], 50)
        self.assertEqual([author["name"] for author in sp["authors"]], ["Alpha", "Invalid", "Zeta"])
        self.assertEqual(rio["status"], "no_records")
        self.assertIsNone(rio["totals"]["committedCents"])
        self.assertEqual(snapshot["coverage"]["availableYears"], [2025, 2026])
        self.assertEqual(snapshot["coverage"]["nationalRows"], 6)
        self.assertEqual(snapshot["coverage"]["municipalRows"], 4)
        self.assertEqual(snapshot["coverage"]["excludedRowsByReason"], {
            "missingMunicipalityCode": 1, "unknownMunicipalityCode": 1,
        })
        self.assertEqual(snapshot["coverage"]["invalidAmountRows"], 1)
        self.assertEqual(snapshot["coverage"]["invalidAmountsByMetric"], {"committedCents": 1})
        self.assertIsNone(snapshot["coverage"]["nationalTotals"]["committedCents"])
        self.assertEqual(snapshot["coverage"]["nationalTotalReconciliation"]["rows"], 6)
        global_author = next(author for author in snapshot["authors"] if author["id"] == "001")
        self.assertEqual(global_author["nameVariants"], ["Alpha", "Autora"])
        self.assertTrue(global_author["nameConflict"])
        self.assertEqual(global_author["recordCount"], 3)
        self.assertEqual(snapshot["source"]["status"], "cached")

    def test_legacy_utf8_bom_cache_is_read_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.csv.gz"
            table = io.StringIO()
            writer = csv.DictWriter(table, amendments.SOURCE_FIELDS, delimiter=";", lineterminator="\n")
            writer.writeheader()
            writer.writerow(source_row(author_name="João"))
            with gzip.open(path, "wb") as compressed:
                compressed.write(table.getvalue().encode("utf-8-sig"))
            before = path.read_bytes()
            rows = list(amendments._iter_cache_rows(path))
            after = path.read_bytes()
        self.assertEqual(rows[0]["Nome do Autor da Emenda"], "João")
        self.assertEqual(after, before)

    def test_requested_year_absent_from_cache_is_unavailable_not_no_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            where = amendments.paths(root)
            write_city_catalog(root, [{"id": "3550308", "name": "São Paulo", "uf": "SP"}])
            where["legacy_cache"].parent.mkdir(parents=True, exist_ok=True)
            write_cache(where["legacy_cache"], [source_row(year="2025")])
            snapshot = amendments.build_snapshot(root, year=2026)
        self.assertEqual(snapshot["source"]["status"], "unavailable")
        self.assertIn("não consta", snapshot["source"]["note"])
        self.assertEqual(snapshot["municipalities"]["3550308"]["status"], "unavailable")
        self.assertFalse(snapshot["coverage"]["yearAvailable"])

    def test_refresh_failure_preserves_cache_and_marks_source_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            where = amendments.paths(Path(temp))
            where["cache"].parent.mkdir(parents=True, exist_ok=True)
            write_cache(where["cache"], [source_row()])
            where["manifest"].write_text(json.dumps({"status": "available", "retained_rows": 1}), encoding="utf-8")
            previous = where["cache"].read_bytes()
            with patch.object(amendments, "_download_and_project", side_effect=ValueError("bad archive")):
                status = amendments._collect_source(where, refresh=True)
            manifest = json.loads(where["manifest"].read_text(encoding="utf-8"))
            after = where["cache"].read_bytes()
        self.assertEqual(status, "stale")
        self.assertEqual(manifest["status"], "stale")
        self.assertIn("preservados", manifest["note"])
        self.assertEqual(after, previous)

    def test_useful_snapshot_is_not_replaced_when_requested_source_is_unavailable(self):
        previous = {"year": 2026, "coverage": {"municipalitiesWithRecords": 1}}
        current = {
            "year": 2026,
            "source": {"status": "unavailable"},
            "coverage": {"yearAvailable": False, "municipalRows": 0},
        }
        with self.assertRaisesRegex(RuntimeError, "Refusing to replace"):
            amendments._guard_snapshot_replacement(previous, current)


if __name__ == "__main__":
    unittest.main()
