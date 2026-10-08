"""Offline audit of negative CEAP housing-complement entries.

Reads the already downloaded annual Câmara ZIP and SQLite in read-only mode.
It does not change imports, stored amounts, or production totals.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from typing import Any
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.public_store import money as database_money
from backend.public_store import public_document_id, safe_url
from ingest.legislative import load_chamber_expenses, sanitize_expense_suppliers

COMPLEMENT_CATEGORY = "COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA"
CURRENT_ROSTER_SOURCE = "camara_deputies_current"
CEAP_SOURCE_ID = "camara_ceap"
CEAP_DOWNLOAD_URL = "https://www.camara.leg.br/cotas/Ano-{year}.csv.zip"
DATA_DICTIONARY_URL = "https://dadosabertos.camara.leg.br/howtouse/2023-12-26-dados-ceap.html"
CEAP_RULES_URL = (
    "https://www2.camara.leg.br/a-camara/documentos-e-pesquisa/arquivo/"
    "acervo-por-tipo/sites-tematicos/57a-legislatura/no-exercicio-do-mandato/"
    "cota-para-o-exercicio-da-atividade-parlamentar-ceap"
)


def amount_cents(value: Any) -> int | None:
    """Parse a source amount into integer cents; a blank source value stays missing."""
    if value is None:
        return None
    text = str(value).strip().replace("R$", "").replace("\u00a0", "")
    text = re.sub(r"\s+", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        value_decimal = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"Invalid monetary source value: {value!r}") from error
    scaled = value_decimal * 100
    if not value_decimal.is_finite() or scaled != scaled.to_integral_value():
        raise ValueError(f"Source value has invalid precision: {value!r}")
    return int(scaled)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clean_fields(fields: list[str] | None) -> list[str]:
    return [str(field).lstrip("\ufeff\xef\xbb\xbf\"") for field in (fields or [])]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_category_row(row: dict[str, Any], year: int, member: str, line_number: int) -> dict[str, Any] | None:
    category = str(row.get("txtDescricao") or "").strip()
    if category != COMPLEMENT_CATEGORY:
        return None
    row_year = _int_or_none(row.get("numAno")) or year
    if row_year != year:
        return None
    month = _int_or_none(row.get("numMes"))
    if month is not None and not 1 <= month <= 12:
        month = None
    raw_profile_id = str(row.get("ideCadastro") or "").strip()
    profile_id = f"camara:{raw_profile_id}" if re.fullmatch(r"\d+", raw_profile_id) else None
    return {
        "profileId": profile_id,
        "month": month,
        "amountCents": amount_cents(row.get("vlrLiquido")),
        "documentCents": amount_cents(row.get("vlrDocumento")),
        "glosaCents": amount_cents(row.get("vlrGlosa")),
        "glosaBlank": not str(row.get("vlrGlosa") or "").strip(),
        "restitutionCents": amount_cents(row.get("vlrRestituicao")),
        "member": member,
        "lineNumber": line_number,
    }


def _read_archive(path: Path, year: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    category_rows: list[dict[str, Any]] = []
    all_profile_rows: list[dict[str, Any]] = []
    csv_members: list[str] = []
    with zipfile.ZipFile(path) as archive:
        csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_members:
            raise ValueError(f"No CSV member found in {path}")
        for member in csv_members:
            with archive.open(member) as binary:
                text = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
                reader = csv.DictReader(text, delimiter=";")
                if not reader.fieldnames:
                    raise ValueError(f"CSV has no header: {member}")
                reader.fieldnames = _clean_fields(reader.fieldnames)
                for line_number, raw in enumerate(reader, start=2):
                    row = {
                        str(key).lstrip("\ufeff\xef\xbb\xbf\""): value
                        for key, value in raw.items()
                        if key is not None
                    }
                    row_year = _int_or_none(row.get("numAno")) or year
                    if row_year != year:
                        continue
                    raw_profile_id = str(row.get("ideCadastro") or "").strip()
                    profile_id = f"camara:{raw_profile_id}" if re.fullmatch(r"\d+", raw_profile_id) else None
                    amount = amount_cents(row.get("vlrLiquido"))
                    if profile_id:
                        all_profile_rows.append({
                            "profileId": profile_id,
                            "month": _int_or_none(row.get("numMes")),
                            "amountCents": amount,
                            "category": str(row.get("txtDescricao") or "").strip(),
                        })
                    projected = _source_category_row(row, year, member, line_number)
                    if projected is not None:
                        category_rows.append(projected)
    return category_rows, all_profile_rows, ", ".join(csv_members)


def _sign(value: int | None) -> str:
    if value is None:
        return "missing"
    if value < 0:
        return "negative"
    if value > 0:
        return "positive"
    return "zero"


def _row_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    signs = Counter(_sign(row.get("amountCents")) for row in rows)
    negative = [row["amountCents"] for row in rows
                if isinstance(row.get("amountCents"), int) and row["amountCents"] < 0]
    positive = [row["amountCents"] for row in rows
                if isinstance(row.get("amountCents"), int) and row["amountCents"] > 0]
    signed = [row["amountCents"] for row in rows if isinstance(row.get("amountCents"), int)]
    return {
        "rows": len(rows),
        "uniqueDeputies": len({row["profileId"] for row in rows if row.get("profileId")}),
        "rowsWithoutDeputyId": sum(not row.get("profileId") for row in rows),
        "vlrLiquidoSignCounts": {key: signs.get(key, 0) for key in ("negative", "zero", "positive", "missing")},
        "vlrLiquidoSignedTotalCents": sum(signed),
        "negativeVlrLiquidoCents": sum(negative),
        "positiveVlrLiquidoCents": sum(positive),
    }


def _source_field_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count_fields = {
        "positiveVlrDocumentoRows": 0,
        "zeroVlrDocumentoRows": 0,
        "negativeVlrDocumentoRows": 0,
        "missingVlrDocumentoRows": 0,
        "blankVlrGlosaRows": 0,
        "zeroVlrGlosaRows": 0,
        "nonzeroVlrGlosaRows": 0,
        "missingVlrGlosaRows": 0,
        "vlrLiquidoIsNegativeVlrDocumentoRows": 0,
        "zeroVlrRestituicaoRows": 0,
        "missingVlrRestituicaoRows": 0,
    }
    for row in rows:
        document = row.get("documentCents")
        if document is None:
            count_fields["missingVlrDocumentoRows"] += 1
        elif document > 0:
            count_fields["positiveVlrDocumentoRows"] += 1
        elif document < 0:
            count_fields["negativeVlrDocumentoRows"] += 1
        else:
            count_fields["zeroVlrDocumentoRows"] += 1
        glosa = row.get("glosaCents")
        if row.get("glosaBlank"):
            count_fields["blankVlrGlosaRows"] += 1
        elif glosa is None:
            count_fields["missingVlrGlosaRows"] += 1
        elif glosa == 0:
            count_fields["zeroVlrGlosaRows"] += 1
        else:
            count_fields["nonzeroVlrGlosaRows"] += 1
        amount = row.get("amountCents")
        if amount is not None and document is not None and amount == -document:
            count_fields["vlrLiquidoIsNegativeVlrDocumentoRows"] += 1
        restitution = row.get("restitutionCents")
        if restitution == 0:
            count_fields["zeroVlrRestituicaoRows"] += 1
        elif restitution is None:
            count_fields["missingVlrRestituicaoRows"] += 1
    return count_fields


def _open_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _database_evidence(path: Path, year: int) -> dict[str, Any]:
    connection = _open_database(path)
    try:
        roster = {
            row["id"]: row["name"]
            for row in connection.execute(
                """SELECT DISTINCT a.id, a.name FROM authorities a
                   JOIN roster r ON r.authorityId=a.id
                   WHERE a.role='deputado' AND r.sourceId=? ORDER BY a.id""",
                (CURRENT_ROSTER_SOURCE,),
            )
        }
        if not roster:
            raise ValueError("The read-only SQLite database has no current Câmara roster")
        snapshot_row = connection.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone()
        source = connection.execute("SELECT url,fetchedAt FROM sources WHERE id=?", (CEAP_SOURCE_ID,)).fetchone()
        records = list(connection.execute(
            """SELECT e.authorityId,e.year,e.month,e.category,e.amountCents,e.sourceId
               FROM expenses e JOIN (SELECT DISTINCT authorityId FROM roster WHERE sourceId=?) r
                 ON r.authorityId=e.authorityId
               JOIN authorities a ON a.id=e.authorityId
               WHERE a.role='deputado' AND e.kind IN ('reembolso','complemento_moradia')""",
            (CURRENT_ROSTER_SOURCE,),
        ))
        source_rows = list(connection.execute(
            """SELECT e.id,e.authorityId,e.year,e.month,e.date,e.category,e.amountCents,
                      e.documentId,e.documentUrl,e.supplierKey,e.sourceId,e.kind
               FROM expenses e JOIN (SELECT DISTINCT authorityId FROM roster WHERE sourceId=?) r
                 ON r.authorityId=e.authorityId
               JOIN authorities a ON a.id=e.authorityId
               WHERE a.role='deputado' AND e.sourceId=? AND e.year=? AND e.kind IN ('reembolso','complemento_moradia')""",
            (CURRENT_ROSTER_SOURCE, CEAP_SOURCE_ID, year),
        ))

        profile_periods: dict[str, dict[str, dict[str, int]]] = {}
        roster_totals = {
            "allTime": {"displayedTotalCents": 0, "totalWithoutAuditedRowsCents": 0,
                        "housingComplementRows": 0, "housingComplementSignedCents": 0,
                        "profilesWithExpenses": set()},
            "year": {"displayedTotalCents": 0, "totalWithoutAuditedRowsCents": 0,
                     "housingComplementRows": 0, "housingComplementSignedCents": 0,
                     "profilesWithExpenses": set()},
            "janToJuly": {"displayedTotalCents": 0, "totalWithoutAuditedRowsCents": 0,
                          "housingComplementRows": 0, "housingComplementSignedCents": 0,
                          "profilesWithExpenses": set()},
        }
        for row in records:
            profile_id = row["authorityId"]
            amount = row["amountCents"]
            if not isinstance(amount, int):
                raise ValueError(f"Non-integer expense amount in SQLite for {profile_id}")
            is_complement = (row["sourceId"] == CEAP_SOURCE_ID and row["year"] == year
                             and row["category"] == COMPLEMENT_CATEGORY)
            period = profile_periods.setdefault(profile_id, {
                "allTime": {"displayedTotalCents": 0, "housingComplementRows": 0,
                            "housingComplementSignedCents": 0},
                "year": {"displayedTotalCents": 0, "housingComplementRows": 0,
                         "housingComplementSignedCents": 0},
                "janToJuly": {"displayedTotalCents": 0, "housingComplementRows": 0,
                              "housingComplementSignedCents": 0},
            })
            scopes = ["allTime"]
            if row["year"] == year:
                scopes.append("year")
                if isinstance(row["month"], int) and 1 <= row["month"] <= 7:
                    scopes.append("janToJuly")
            for scope in scopes:
                profile_scope = period[scope]
                aggregate = roster_totals[scope]
                profile_scope["displayedTotalCents"] += amount
                aggregate["displayedTotalCents"] += amount
                aggregate["profilesWithExpenses"].add(profile_id)
                if is_complement:
                    profile_scope["housingComplementRows"] += 1
                    profile_scope["housingComplementSignedCents"] += amount
                    aggregate["housingComplementRows"] += 1
                    aggregate["housingComplementSignedCents"] += amount
                aggregate["totalWithoutAuditedRowsCents"] = (
                    aggregate["displayedTotalCents"] - aggregate["housingComplementSignedCents"]
                )
                profile_scope["totalWithoutAuditedRowsCents"] = (
                    profile_scope["displayedTotalCents"] - profile_scope["housingComplementSignedCents"]
                )

        for aggregate in roster_totals.values():
            aggregate["profilesWithExpenses"] = len(aggregate["profilesWithExpenses"])
            aggregate["removalDeltaCents"] = (
                aggregate["totalWithoutAuditedRowsCents"] - aggregate["displayedTotalCents"]
            )
        per_profile = {}
        for profile_id, scopes in profile_periods.items():
            per_profile[profile_id] = {
                scope: {
                    **values,
                    "removalDeltaCents": values["totalWithoutAuditedRowsCents"] - values["displayedTotalCents"],
                }
                for scope, values in scopes.items()
            }
        return {
            "roster": roster,
            "profileTotals": per_profile,
            "rosterTotals": roster_totals,
            "snapshotAt": snapshot_row[0] if snapshot_row else None,
            "ceapSource": {"url": source["url"], "fetchedAt": source["fetchedAt"]} if source else None,
            "expenseRows": len(records),
            "sourceRows": [dict(row) for row in source_rows],
        }
    finally:
        connection.close()


def _normalized_import_row(expense: dict[str, Any]) -> dict[str, Any]:
    """Project the same persisted columns used by the importer, without writing them."""
    supplier = expense.get("supplier") if isinstance(expense.get("supplier"), dict) else None
    supplier_key = None
    if supplier:
        supplier_key = f"cnpj:{supplier['cnpj']}" if supplier.get("cnpj") else supplier.get("key")
    return {
        "id": expense["id"],
        "authorityId": expense["authorityId"],
        "year": expense["year"],
        "month": expense["month"],
        "date": expense.get("date"),
        "category": expense.get("category") or "Não informada",
        "amountCents": database_money(expense["amount"]),
        "documentId": public_document_id(expense.get("documentId")),
        "documentUrl": safe_url(expense.get("documentUrl")),
        "supplierKey": supplier_key,
        "sourceId": expense["sourceId"],
        "kind": expense["kind"],
    }


def _row_set_hash(rows: list[dict[str, Any]]) -> str:
    projection = [
        [row[key] for key in (
            "id", "authorityId", "year", "month", "date", "category", "amountCents",
            "documentId", "documentUrl", "supplierKey", "sourceId", "kind",
        )]
        for row in sorted(rows, key=lambda item: item["id"])
    ]
    content = json.dumps(projection, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _source_completeness(archive_path: Path, year: int, database: dict[str, Any]) -> dict[str, Any]:
    """Verify the current-roster SQLite rows against importer-normalized ZIP rows."""
    authorities: dict[str, dict[str, Any]] = {}
    expected_expenses, importer_stats = load_chamber_expenses(
        archive_path, year, authorities, CEAP_SOURCE_ID
    )
    sanitize_expense_suppliers(expected_expenses)
    roster_ids = set(database["roster"])
    expected = {
        row["id"]: _normalized_import_row(row)
        for row in expected_expenses
        if row["authorityId"] in roster_ids
    }
    actual = {
        row["id"]: dict(row)
        for row in database["sourceRows"]
    }
    expected_ids, actual_ids = set(expected), set(actual)
    missing_ids = expected_ids - actual_ids
    unexpected_ids = actual_ids - expected_ids
    shared_ids = expected_ids & actual_ids
    mismatched_ids = {
        row_id for row_id in shared_ids
        if any(expected[row_id].get(key) != actual[row_id].get(key) for key in expected[row_id])
    }
    exact_match = not (missing_ids or unexpected_ids or mismatched_ids)

    def grouped(rows: dict[str, dict[str, Any]], key_fn) -> dict[Any, list[dict[str, Any]]]:
        result: dict[Any, list[dict[str, Any]]] = {}
        for row in rows.values():
            result.setdefault(key_fn(row), []).append(row)
        return result

    expected_months = grouped(expected, lambda row: (row["year"], row["month"]))
    actual_months = grouped(actual, lambda row: (row["year"], row["month"]))
    month_keys = set(expected_months) | set(actual_months) | {(year, month) for month in range(1, 13)}
    by_month: dict[str, Any] = {}
    per_profile_month: dict[str, dict[str, Any]] = {
        profile_id: {"name": database["roster"][profile_id], "months": {}}
        for profile_id in sorted(roster_ids)
    }
    source_person_months = grouped(expected, lambda row: (row["authorityId"], row["month"]))
    database_person_months = grouped(actual, lambda row: (row["authorityId"], row["month"]))
    for year_month in sorted(month_keys, key=lambda item: (item[0], item[1] or 0)):
        source_rows = expected_months.get(year_month, [])
        database_rows = actual_months.get(year_month, [])
        source_by_id = {row["id"]: row for row in source_rows}
        database_by_id = {row["id"]: row for row in database_rows}
        month_exact = (
            set(source_by_id) == set(database_by_id)
            and all(source_by_id[row_id] == database_by_id[row_id] for row_id in source_by_id)
        )
        period = f"{year_month[0]:04d}-{year_month[1]:02d}" if year_month[1] else f"{year_month[0]:04d}-unknown"
        source_sum = sum(row["amountCents"] for row in source_rows)
        database_sum = sum(row["amountCents"] for row in database_rows)
        by_month[period] = {
            "expectedRowCount": len(source_rows),
            "databaseRowCount": len(database_rows),
            "expectedSignedTotalCents": source_sum if source_rows else None,
            "databaseSignedTotalCents": database_sum if database_rows else None,
            "expectedRowSetSha256": _row_set_hash(source_rows),
            "databaseRowSetSha256": _row_set_hash(database_rows),
            "completeSnapshot": month_exact,
        }
    for profile_id in roster_ids:
        # Include all months explicitly: an empty rowset remains absent data,
        # while the global importer-to-SQLite equality certifies the snapshot.
        for month in range(1, 13):
            key = (profile_id, month)
            profile_source_rows = source_person_months.get(key, [])
            profile_database_rows = database_person_months.get(key, [])
            profile_source_by_id = {row["id"]: row for row in profile_source_rows}
            profile_database_by_id = {row["id"]: row for row in profile_database_rows}
            profile_match = (
                set(profile_source_by_id) == set(profile_database_by_id)
                and all(profile_source_by_id[row_id] == profile_database_by_id[row_id]
                        for row_id in profile_source_by_id)
            )
            per_profile_month[profile_id]["months"][f"{year:04d}-{month:02d}"] = {
                "sourceRowCount": len(profile_source_rows),
                "databaseRowCount": len(profile_database_rows),
                "sourceSignedTotalCents": sum(row["amountCents"] for row in profile_source_rows) if profile_source_rows else None,
                "databaseSignedTotalCents": sum(row["amountCents"] for row in profile_database_rows) if profile_database_rows else None,
                "sourceRowSetSha256": _row_set_hash(profile_source_rows),
                "databaseRowSetSha256": _row_set_hash(profile_database_rows),
                "completeSnapshot": profile_match,
            }
    return {
        "method": "ingest.legislative.load_chamber_expenses with the same source ID and stable-row dedup, filtered to the current Câmara roster, compared to SQLite persisted fields",
        "sourceFetchedAt": database["ceapSource"]["fetchedAt"] if database["ceapSource"] else None,
        "sourceArchiveSha256": _sha256(archive_path),
        "importerArchiveRowCount": importer_stats["rows"],
        "expectedCurrentRosterRowCount": len(expected),
        "databaseCurrentRosterRowCount": len(actual),
        "missingDatabaseRows": len(missing_ids),
        "unexpectedDatabaseRows": len(unexpected_ids),
        "mismatchedDatabaseRows": len(mismatched_ids),
        "completeSnapshot": exact_match,
        "byMonth": by_month,
        "profiles": per_profile_month,
    }


def _archive_totals(rows: list[dict[str, Any]], profile_ids: set[str], year_rows: list[dict[str, Any]]) -> dict[str, Any]:
    roster_category_rows = [row for row in rows if row.get("profileId") in profile_ids]
    scopes = {
        "allYear": roster_category_rows,
        "janToJuly": [row for row in roster_category_rows
                      if row.get("month") is not None and 1 <= row["month"] <= 7],
    }
    matching_rows = [row for row in year_rows if row.get("profileId") in profile_ids]
    quota_scopes = {
        "allYear": matching_rows,
        "janToJuly": [row for row in matching_rows if row.get("month") is not None and 1 <= row["month"] <= 7],
    }
    result: dict[str, Any] = {"housingComplement": {}, "quotaByCurrentRoster": {}}
    for name, source_rows in scopes.items():
        result["housingComplement"][name] = _row_stats(source_rows)
    for name, source_rows in quota_scopes.items():
        values = [row["amountCents"] for row in source_rows if isinstance(row.get("amountCents"), int)]
        complement_rows = [row for row in source_rows if row.get("category") == COMPLEMENT_CATEGORY]
        complement_sum = sum(row["amountCents"] for row in complement_rows if isinstance(row.get("amountCents"), int))
        result["quotaByCurrentRoster"][name] = {
            "rows": len(source_rows),
            "profilesWithRows": len({row["profileId"] for row in source_rows}),
            "displayedTotalCents": sum(values),
            "housingComplementRows": len(complement_rows),
            "housingComplementSignedCents": complement_sum,
            "totalWithoutHousingComplementRowsCents": sum(values) - complement_sum,
            "removalDeltaCents": -complement_sum,
        }
    return result


def _month_summaries(rows: list[dict[str, Any]], year: int) -> dict[str, Any]:
    by_month: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        month = row.get("month")
        if isinstance(month, int) and 1 <= month <= 12:
            by_month.setdefault(month, []).append(row)
    return {f"{year:04d}-{month:02d}": _row_stats(by_month[month])
            for month in sorted(by_month)}


def build_audit(archive_path: Path, database_path: Path, year: int = 2026,
                generated_at: str | None = None) -> dict[str, Any]:
    """Build the audit from a ZIP and SQLite, both read-only."""
    archive_path = Path(archive_path)
    database_path = Path(database_path)
    category_rows, archive_profile_rows, csv_member_names = _read_archive(archive_path, year)
    database = _database_evidence(database_path, year)
    source_completeness = _source_completeness(archive_path, year, database)
    roster_ids = set(database["roster"])
    archive = _archive_totals(category_rows, roster_ids, archive_profile_rows)
    source_checks = {
        "allYear": _source_field_check(category_rows),
        "janToJuly": _source_field_check([row for row in category_rows
                                           if row.get("month") is not None and 1 <= row["month"] <= 7]),
    }
    months = _month_summaries(category_rows, year)
    affected_profiles = []
    for profile_id in sorted(roster_ids):
        yearly = database["profileTotals"].get(profile_id, {}).get("year")
        if not yearly or not yearly["housingComplementRows"]:
            continue
        affected_profiles.append({
            "id": profile_id,
            "name": database["roster"][profile_id],
            "housingComplementRows": yearly["housingComplementRows"],
            "housingComplementSignedCents": yearly["housingComplementSignedCents"],
            "quotaWithRowsCents": yearly["displayedTotalCents"],
            "quotaWithoutRowsCents": yearly["totalWithoutAuditedRowsCents"],
            "removalDeltaCents": yearly["removalDeltaCents"],
            "janToJuly": database["profileTotals"][profile_id]["janToJuly"],
        })
    focus_ids = ("camara:73604", "camara:204528", "camara:74581")
    focus_profiles = []
    for profile_id in focus_ids:
        all_scopes = database["profileTotals"].get(profile_id, {})
        if not all_scopes:
            total_scope = lambda: {"displayedTotalCents": None, "totalWithoutAuditedRowsCents": None,
                                   "housingComplementRows": 0, "housingComplementSignedCents": 0,
                                   "removalDeltaCents": None}
        else:
            total_scope = lambda scope: all_scopes.get(scope, {
                "displayedTotalCents": None, "totalWithoutAuditedRowsCents": None,
                "housingComplementRows": 0, "housingComplementSignedCents": 0,
                "removalDeltaCents": None,
            })
        focus_profiles.append({
            "id": profile_id,
            "name": database["roster"].get(profile_id),
            "allTime": total_scope("allTime") if all_scopes else total_scope(),
            "year": total_scope("year") if all_scopes else total_scope(),
            "janToJuly": total_scope("janToJuly") if all_scopes else total_scope(),
            "interpretation": "No observed reembolso rows in this SQLite snapshot" if not all_scopes else None,
        })
    roster_stats = {
        scope: {key: value for key, value in totals.items() if key != "profilesWithExpenses"}
        | {"profilesWithExpenses": totals["profilesWithExpenses"]}
        for scope, totals in database["rosterTotals"].items()
    }
    generated_at = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "schemaVersion": 1,
        "kind": "offline-ceap-housing-complement-sign-audit-not-production-total",
        "year": year,
        "generatedAt": generated_at,
        "category": COMPLEMENT_CATEGORY,
        "inputs": {
            "archive": {
                "path": str(archive_path),
                "sha256": _sha256(archive_path),
                "url": CEAP_DOWNLOAD_URL.format(year=year),
                "csvMembers": csv_member_names,
            },
            "database": {
                "path": str(database_path),
                "snapshotAt": database["snapshotAt"],
                "currentRosterSourceId": CURRENT_ROSTER_SOURCE,
                "currentRosterSize": len(roster_ids),
                "ceapSource": database["ceapSource"],
            },
        },
        "officialDocumentation": {
            "dataDictionaryUrl": DATA_DICTIONARY_URL,
            "ceapRulesUrl": CEAP_RULES_URL,
            "scopeNote": (
                "The data dictionary defines vlrLiquido as the amount debited from CEAP, "
                "corresponding to vlrDocumento minus vlrGlosa. It does not give a specific "
                "interpretation for negative vlrLiquido in this category."
            ),
        },
        "wholeArchive": {
            "housingComplement": _row_stats(category_rows),
            "sourceFieldCheck": source_checks["allYear"],
            "janToJuly": {
                "housingComplement": _row_stats([row for row in category_rows
                                                  if row.get("month") is not None and 1 <= row["month"] <= 7]),
                "sourceFieldCheck": source_checks["janToJuly"],
            },
            "byMonth": months,
        },
        "currentRoster": {
            "rosterSize": len(roster_ids),
            "archive": archive,
            "databaseProfileTotals": roster_stats,
            "affectedProfiles": affected_profiles,
            "focusProfiles": focus_profiles,
            "archiveDatabaseReconciliation": {
                scope: {
                    "archiveDisplayedQuotaCents": archive["quotaByCurrentRoster"][name]["displayedTotalCents"],
                    "databaseDisplayedQuotaCents": database["rosterTotals"][db_scope]["displayedTotalCents"],
                    "differenceDatabaseMinusArchiveCents": (
                        database["rosterTotals"][db_scope]["displayedTotalCents"]
                        - archive["quotaByCurrentRoster"][name]["displayedTotalCents"]
                    ),
                }
                for scope, name, db_scope in (("allYear", "allYear", "year"),
                                               ("janToJuly", "janToJuly", "janToJuly"))
            },
            "sourceCompleteness": source_completeness,
        },
        "accountingAssessment": {
            "removingNegativeRowsRaisesProfileQuotaTotals": True,
            "method": "quotaWithoutRowsCents = currently displayed signed total minus the audited rows' signed cents",
            "interpretationLimit": (
                "This is a counterfactual recomposition, not a correction to source records. "
                "The source CSV and SQLite keep the original negative cents. The separate "
                "housing-complement amount must be reconciled to the housing source before "
                "it is added once to any combined presentation."
            ),
        },
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         delete=False) as stream:
            temporary_name = stream.name
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
            stream.flush()
        Path(temporary_name).replace(path)
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()
    archive_path = args.root / "data" / "raw" / "legislative" / f"camara-{args.year}.csv.zip"
    database_path = args.root / "data" / "na-lupa.sqlite3"
    result = build_audit(archive_path, database_path, args.year)
    snapshot_path = args.root / "data" / "snapshots" / "chamber-quota-audit.json"
    raw_manifest_path = args.root / "data" / "raw" / "mandate-cost" / "quota-audit" / "manifest.json"
    manifest = {
        "kind": "offline-quota-audit-input-manifest",
        "generatedAt": result["generatedAt"],
        "year": args.year,
        "sourceArchive": result["inputs"]["archive"],
        "databaseSnapshotAt": result["inputs"]["database"]["snapshotAt"],
        "reproduction": "python3 ingest/chamber_quota_audit.py",
        "noNetwork": True,
        "noDatabaseWrites": True,
        "noRawPersonOrEmployeeRowsPersisted": True,
    }
    _atomic_json(snapshot_path, result)
    _atomic_json(raw_manifest_path, manifest)
    print(json.dumps({
        "snapshot": str(snapshot_path),
        "rawManifest": str(raw_manifest_path),
        "wholeArchive": result["wholeArchive"]["housingComplement"],
        "currentRosterTotals": result["currentRoster"]["databaseProfileTotals"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
