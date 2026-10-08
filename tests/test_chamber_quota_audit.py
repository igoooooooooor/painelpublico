import csv
import io
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from ingest import chamber_quota_audit as audit
from ingest.legislative import load_chamber_expenses, sanitize_expense_suppliers


CSV_FIELDS = [
    "txNomeParlamentar", "cpf", "ideCadastro", "nuCarteiraParlamentar", "nuLegislatura",
    "sgUF", "sgPartido", "codLegislatura", "numSubCota", "txtDescricao",
    "numEspecificacaoSubCota", "txtDescricaoEspecificacao", "txtFornecedor", "txtCNPJCPF",
    "txtNumero", "indTipoDocumento", "datEmissao", "vlrDocumento", "vlrGlosa",
    "vlrLiquido", "numMes", "numAno", "numParcela", "txtPassageiro", "txtTrecho",
    "numLote", "numRessarcimento", "datPagamentoRestituicao", "vlrRestituicao",
    "nuDeputadoId", "ideDocumento", "urlDocumento",
]


def source_row(profile_id, month, category, liquid, document, document_id):
    return {
        "txNomeParlamentar": f"Deputy {profile_id}",
        "ideCadastro": str(profile_id),
        "nuDeputadoId": str(profile_id),
        "sgUF": "DF",
        "sgPartido": "P",
        "txtDescricao": category,
        "txtFornecedor": "Fornecedor público",
        "txtCNPJCPF": "",
        "txtNumero": document_id,
        "datEmissao": "",
        "vlrDocumento": document,
        "vlrGlosa": "",
        "vlrLiquido": liquid,
        "numMes": str(month),
        "numAno": "2026",
        "vlrRestituicao": "0.0",
        "ideDocumento": document_id,
        "urlDocumento": "",
    }


class ChamberQuotaAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.archive_path = self.root / "camara-2026.csv.zip"
        self.database_path = self.root / "database.sqlite3"
        self.rows = [
            source_row(1, 1, audit.COMPLEMENT_CATEGORY, "-10", "10", "100"),
            source_row(1, 7, "MANUTENÇÃO DE ESCRITÓRIO", "100.50", "100.50", "101"),
            source_row(1, 8, audit.COMPLEMENT_CATEGORY, "0", "0", "102"),
            source_row(2, 2, audit.COMPLEMENT_CATEGORY, "3.25", "3.25", "200"),
        ]
        self._write_archive()

    def tearDown(self):
        self.temporary.cleanup()

    def _write_archive(self):
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, delimiter=";", lineterminator="\n")
        writer.writeheader()
        writer.writerows(self.rows)
        with zipfile.ZipFile(self.archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Ano-2026.csv", buffer.getvalue().encode("utf-8"))

    def _write_database(self, omit_ids=()):
        authorities = {}
        expenses, _ = load_chamber_expenses(self.archive_path, 2026, authorities, audit.CEAP_SOURCE_ID)
        sanitize_expense_suppliers(expenses)
        normalized = [audit._normalized_import_row(expense) for expense in expenses
                      if expense["authorityId"] == "camara:1" and expense["id"] not in set(omit_ids)]
        connection = sqlite3.connect(self.database_path)
        connection.executescript("""
            CREATE TABLE authorities(id TEXT PRIMARY KEY, name TEXT, role TEXT);
            CREATE TABLE roster(sourceId TEXT, authorityId TEXT);
            CREATE TABLE meta(key TEXT, value TEXT);
            CREATE TABLE sources(id TEXT, url TEXT, fetchedAt TEXT);
            CREATE TABLE expenses(
                id TEXT PRIMARY KEY, authorityId TEXT, sourceId TEXT, year INTEGER, month INTEGER,
                date TEXT, category TEXT, amountCents INTEGER, documentId TEXT, documentUrl TEXT,
                supplierKey TEXT, kind TEXT
            );
            INSERT INTO authorities VALUES ('camara:1', 'Current Deputy', 'deputado');
            INSERT INTO authorities VALUES ('camara:2', 'Former Deputy', 'deputado');
            INSERT INTO roster VALUES ('camara_deputies_current', 'camara:1');
            INSERT INTO meta VALUES ('snapshotAt', '2026-10-06T22:22:49+00:00');
            INSERT INTO sources VALUES ('camara_ceap', 'https://www.camara.leg.br/cotas/Ano-2026.csv.zip', '2026-10-06T22:22:49+00:00');
        """)
        connection.executemany(
            """INSERT INTO expenses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [tuple(row[key] for key in (
                "id", "authorityId", "sourceId", "year", "month", "date", "category",
                "amountCents", "documentId", "documentUrl", "supplierKey", "kind",
            )) for row in normalized],
        )
        connection.commit()
        connection.close()

    def test_signed_quota_composition_uses_integer_cents_and_current_roster(self):
        self._write_database()
        result = audit.build_audit(self.archive_path, self.database_path, generated_at="2026-10-08T00:00:00+00:00")
        whole = result["wholeArchive"]["housingComplement"]
        self.assertEqual(whole["rows"], 3)
        self.assertEqual(whole["uniqueDeputies"], 2)
        self.assertEqual(whole["vlrLiquidoSignCounts"], {
            "negative": 1, "zero": 1, "positive": 1, "missing": 0,
        })
        self.assertEqual(whole["vlrLiquidoSignedTotalCents"], -675)
        current = result["currentRoster"]
        self.assertEqual(current["archive"]["housingComplement"]["allYear"]["rows"], 2)
        self.assertEqual(current["databaseProfileTotals"]["year"]["displayedTotalCents"], 9050)
        self.assertEqual(current["databaseProfileTotals"]["year"]["totalWithoutAuditedRowsCents"], 10050)
        self.assertEqual(current["databaseProfileTotals"]["year"]["removalDeltaCents"], 1000)
        self.assertTrue(current["sourceCompleteness"]["completeSnapshot"])
        self.assertTrue(current["sourceCompleteness"]["profiles"]["camara:1"]["months"]["2026-01"]["completeSnapshot"])
        self.assertEqual(current["sourceCompleteness"]["profiles"]["camara:1"]["months"]["2026-01"]["sourceSignedTotalCents"], -1000)

    def test_january_rowset_gap_stays_visible_after_later_months(self):
        self._write_database(omit_ids={"camara_ceap:record:100"})
        result = audit.build_audit(self.archive_path, self.database_path, generated_at="2026-10-08T00:00:00+00:00")
        completeness = result["currentRoster"]["sourceCompleteness"]
        profile_months = completeness["profiles"]["camara:1"]["months"]
        self.assertFalse(completeness["completeSnapshot"])
        self.assertEqual(completeness["missingDatabaseRows"], 1)
        self.assertFalse(profile_months["2026-01"]["completeSnapshot"])
        self.assertTrue(profile_months["2026-07"]["completeSnapshot"])
        self.assertTrue(profile_months["2026-12"]["completeSnapshot"])
        self.assertIsNone(profile_months["2026-12"]["sourceSignedTotalCents"])


if __name__ == "__main__":
    unittest.main()
