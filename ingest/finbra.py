"""Offline staging importer for national FINBRA municipal extracts.

The importer reads only the five account indicators used by the city view.
It stages a separate national extract and can explicitly install missing
city caches or quarantine verified disagreements without replacing snapshots.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid
from collections import Counter, defaultdict
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest import accounts

YEAR = 2025
FINBRA_URL = "https://siconfi.tesouro.gov.br/siconfi/pages/public/consulta_finbra/finbra_list.jsf"
CSV_FIELDS = (
    "Instituição", "Cod.IBGE", "UF", "População", "Coluna", "Conta",
    "Identificador da Conta", "Valor",
)

FILE_TABLES = {
    "revenue": ("finbra.csv", "Tabela: Receitas Orçamentárias (Anexo I-C)"),
    "expenses": ("finbra-expenses.csv", "Tabela: Despesas Orçamentárias (Anexo I-D)"),
    "functions": ("finbra-functions.csv", "Tabela: Despesas por Função (Anexo I-E)"),
}
METRIC_FILES = {
    "revenue": "revenue",
    "total-expense": "expenses",
    "personnel": "expenses",
    "health": "functions",
    "education": "functions",
}


def paths(root: Path = ROOT, year: int = YEAR) -> dict[str, Path]:
    raw = root / "data" / "raw"
    return {
        "revenue": raw / "finbra.csv",
        "expenses": raw / "finbra-expenses.csv",
        "functions": raw / "finbra-functions.csv",
        "city_catalog": root / "data" / "snapshots" / "cities.json",
        "entities": raw / "siconfi" / "entes.json",
        "api_cache_dir": raw / "siconfi" / f"accounts-{year}",
        "output": raw / "siconfi" / f"finbra-{year}",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mtime_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat()


def _parse_csv_line(line: str, strict: bool) -> list[str]:
    return next(csv.reader([line], delimiter=";", strict=strict))


def _brl_cents(raw: str) -> int | None:
    text = raw.strip()
    if not text:
        return None
    # FINBRA uses Brazilian decimal commas and optional dots as thousands
    # separators. Dot-only values are treated as standard decimal notation.
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    cents = amount * Decimal(100)
    if cents != cents.to_integral_value():
        return None
    return int(cents)


def _amount_token(raw: str, cents: int | None) -> tuple[str, Any]:
    if cents is not None:
        return ("cents", cents)
    text = raw.strip()
    return ("missing", None) if not text else ("invalid", text)


def _metric_source(file_info: dict[str, Any], year: int) -> dict[str, Any]:
    return {
        "label": f"Tesouro Nacional — Siconfi, FINBRA — {file_info['tableLabel']}",
        "url": FINBRA_URL,
        "period": f"exercício de {year}",
        "fetchedAt": file_info["fetchedAt"],
        "status": "imported",
        "file": file_info["file"],
        "sha256": file_info["sha256"],
        "table": file_info["table"],
        "evidenceType": "national_finbra_export",
    }


def _read_finbra_file(path: Path, file_key: str, year: int,
                      items_by_city: dict[str, list[dict[str, Any]]],
                      city_ufs: dict[str, set[str]]) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"FINBRA input file not found: {path}")
    file_name, table_header = FILE_TABLES[file_key]
    before = path.stat()
    digest = hashlib.sha256()
    line_number = 0
    malformed_quote_rows = 0
    invalid_width_rows = 0
    data_rows = 0
    selected_rows: Counter[str] = Counter()
    selected_codes: dict[str, set[str]] = defaultdict(set)
    invalid_code_rows: Counter[str] = Counter()
    invalid_uf_rows: Counter[str] = Counter()
    non_municipal_institution_rows: Counter[str] = Counter()
    invalid_values: Counter[str] = Counter()
    duplicate_selections: Counter[str] = Counter()
    seen: dict[tuple[str, str], tuple[tuple[str, Any], str, str]] = {}

    source_specs = [spec for spec in accounts.METRIC_SPECS
                    if METRIC_FILES[spec["id"]] == file_key]

    def read_line(stream) -> str:
        raw = stream.readline()
        if raw:
            digest.update(raw)
        return raw.decode("cp1252")

    with path.open("rb") as stream:
        metadata = [read_line(stream).strip() for _ in range(3)]
        expected_metadata = [f"Exercício: {year}", "Escopo: Municípios", table_header]
        if metadata != expected_metadata:
            raise ValueError(f"{path.name}: metadata does not match the requested year, scope, and table")

        header_line = read_line(stream)
        line_number = 4
        try:
            header = _parse_csv_line(header_line, True)
        except csv.Error as exc:
            raise ValueError(f"{path.name}: malformed CSV header") from exc
        if tuple(header) != CSV_FIELDS:
            raise ValueError(f"{path.name}: unexpected CSV columns")
        column = {name: index for index, name in enumerate(header)}

        for line in stream:
            line_number += 1
            digest.update(line)
            decoded = line.decode("cp1252")
            if not decoded.strip():
                continue
            try:
                fields = _parse_csv_line(decoded, True)
            except csv.Error:
                malformed_quote_rows += 1
                try:
                    fields = _parse_csv_line(decoded, False)
                except csv.Error as exc:
                    invalid_width_rows += 1
                    raise ValueError(f"{path.name}:{line_number}: malformed quoted row") from exc
            if len(fields) != len(CSV_FIELDS):
                invalid_width_rows += 1
                raise ValueError(f"{path.name}:{line_number}: expected exactly 8 CSV fields")
            data_rows += 1

            for spec in source_specs:
                selector = spec["selector"]
                expected_identifier = f"siconfi-cor_{selector['cod_conta']}"
                if (fields[column["Identificador da Conta"]].strip() != expected_identifier
                        or fields[column["Coluna"]].strip() != selector["coluna"]):
                    continue
                expected_conta = selector.get("conta")
                if expected_conta and fields[column["Conta"]].strip() != expected_conta:
                    continue

                metric_id = spec["id"]
                selected_rows[metric_id] += 1
                municipality_id = fields[column["Cod.IBGE"]].strip()
                if not re.fullmatch(r"\d{7}", municipality_id):
                    invalid_code_rows[metric_id] += 1
                    continue
                uf = fields[column["UF"]].strip().upper()
                if not re.fullmatch(r"[A-Z]{2}", uf):
                    invalid_uf_rows[metric_id] += 1
                    continue
                institution = fields[column["Instituição"]].strip()
                if not accounts._is_municipal_institution(institution):
                    non_municipal_institution_rows[metric_id] += 1
                    continue

                raw_amount = fields[column["Valor"]]
                amount_cents = _brl_cents(raw_amount)
                if amount_cents is None and raw_amount.strip():
                    invalid_values[metric_id] += 1
                selected_codes[metric_id].add(municipality_id)
                city_ufs[municipality_id].add(uf)
                token = _amount_token(raw_amount, amount_cents)
                duplicate_key = (municipality_id, metric_id)
                prior = seen.get(duplicate_key)
                if prior is not None:
                    if prior != (token, uf, institution):
                        raise ValueError(
                            f"{path.name}:{line_number}: conflicting duplicate {metric_id} selection "
                            f"for IBGE code {municipality_id}"
                        )
                    duplicate_selections[metric_id] += 1
                    continue
                seen[duplicate_key] = (token, uf, institution)
                normalized = {
                    "exercicio": year,
                    "cod_ibge": municipality_id,
                    "instituicao": institution,
                    "anexo": selector["anexo"],
                    "rotulo": selector["rotulo"],
                    "coluna": selector["coluna"],
                    "cod_conta": selector["cod_conta"],
                    "conta": fields[column["Conta"]].strip(),
                    "valor": Decimal(amount_cents).scaleb(-2) if amount_cents is not None else None,
                }
                items_by_city[municipality_id].append(normalized)

    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"{path.name}: input changed during import")
    fetched_at = _mtime_iso(after.st_mtime)
    table_label = table_header.removeprefix("Tabela: ")
    return {
        "file": path.name,
        "table": table_header.removeprefix("Tabela: "),
        "tableLabel": table_label,
        "metadata": metadata,
        "sha256": digest.hexdigest(),
        "sizeBytes": after.st_size,
        "fetchedAt": fetched_at,
        "dataRows": data_rows,
        "malformedQuotedRows": malformed_quote_rows,
        "invalidWidthRows": invalid_width_rows,
        "selectedRowsByMetric": dict(selected_rows),
        "selectedCodesByMetric": {key: len(value) for key, value in selected_codes.items()},
        "invalidCodeRowsByMetric": dict(invalid_code_rows),
        "invalidUfRowsByMetric": dict(invalid_uf_rows),
        "nonMunicipalInstitutionRowsByMetric": dict(non_municipal_institution_rows),
        "invalidSelectedValuesByMetric": dict(invalid_values),
        "duplicateSelectionsByMetric": dict(duplicate_selections),
    }


def _load_api_row(cache_dir: Path, municipality_id: str, year: int) -> dict[str, Any] | None:
    value = accounts._read_json(accounts._cache_path(cache_dir, municipality_id), None)
    if not isinstance(value, dict) or str(value.get("id")) != municipality_id or value.get("year") != year:
        return None
    return value


def _metric_values(row: dict[str, Any] | None) -> dict[str, int | None]:
    values: dict[str, int | None] = {}
    metrics = row.get("metrics") if isinstance(row, dict) else None
    if not isinstance(metrics, list):
        return values
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        metric_id = str(metric.get("id", ""))
        value = metric.get("amountCents")
        values[metric_id] = value if isinstance(value, int) and not isinstance(value, bool) else None
    return values


def _compare_api(rows: dict[str, dict[str, Any]], api_cache_dir: Path,
                 year: int) -> dict[str, Any]:
    metrics = [spec["id"] for spec in accounts.METRIC_SPECS]
    comparison = {metric_id: Counter() for metric_id in metrics}
    api_statuses: Counter[str] = Counter()
    delivery_conflicts = []
    differences: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for municipality_id, staged in rows.items():
        api = _load_api_row(api_cache_dir, municipality_id, year)
        if api is None:
            api_statuses["no_cache"] += 1
        else:
            api_statuses[str(api.get("status") or "missing-status")] += 1
        api_values = _metric_values(api)
        finbra_values = _metric_values(staged)
        for metric_id in metrics:
            finbra_value = finbra_values.get(metric_id)
            api_value = api_values.get(metric_id)
            counter = comparison[metric_id]
            if finbra_value is None:
                counter["finbra_missing"] += 1
            elif api_value is None:
                counter["api_value_missing"] += 1
            else:
                counter["matched"] += 1
                if finbra_value == api_value:
                    counter["identical"] += 1
                else:
                    counter["different"] += 1
                    differences[metric_id].append({
                        "id": municipality_id,
                        "finbraCents": finbra_value,
                        "apiCents": api_value,
                        "differenceCents": finbra_value - api_value,
                    })
        declaration = api.get("declaration") if isinstance(api, dict) else None
        if isinstance(declaration, dict) and declaration.get("status") == "not_filed":
            observed = [metric_id for metric_id, value in finbra_values.items() if value is not None]
            if observed:
                delivery_conflicts.append({
                    "id": municipality_id,
                    "apiDeclarationStatus": "not_filed",
                    "apiStatus": api.get("status"),
                    "finbraObservedMetrics": sorted(observed),
                })
    return {
        "apiCacheStatusesForStagedMunicipalities": dict(api_statuses),
        "metricComparisons": {key: dict(value) for key, value in comparison.items()},
        "differences": dict(differences),
        "apiNotFiledWithFinbraValues": delivery_conflicts,
    }


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _is_cents(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _append_note(source: dict[str, Any], note: str) -> dict[str, Any]:
    result = dict(source)
    current = str(result.get("note") or "").strip()
    result["note"] = f"{current} {note}".strip()
    return result


def _load_stage(stage_dir: Path, year: int) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        manifest = json.loads((stage_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"FINBRA stage manifest is missing or malformed: {stage_dir}") from exc
    if (not isinstance(manifest, dict) or manifest.get("generator") != "ingest.finbra"
            or manifest.get("year") != year
            or not isinstance(manifest.get("source"), dict)
            or manifest["source"].get("evidenceType") != "national_finbra_export_not_delivery_status"):
        raise ValueError("FINBRA stage manifest is incompatible or has the wrong year")
    filenames = manifest.get("municipalityFiles")
    if not isinstance(filenames, list):
        raise ValueError("FINBRA stage manifest is missing its municipality file list")
    rows: dict[str, dict[str, Any]] = {}
    for filename in filenames:
        if not isinstance(filename, str) or not re.fullmatch(r"\d{7}\.json", filename):
            raise ValueError("FINBRA stage contains an invalid municipality filename")
        path = stage_dir / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"FINBRA stage municipality file is missing: {filename}")
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"FINBRA stage municipality file is malformed: {filename}") from exc
        municipality_id = filename[:-5]
        if (not isinstance(row, dict) or str(row.get("id")) != municipality_id
                or row.get("year") != year or row.get("identityVerified") is not True
                or not isinstance(row.get("metrics"), list)):
            raise ValueError(f"FINBRA stage municipality identity is invalid: {filename}")
        rows[municipality_id] = row
    return manifest, rows


def install_missing(root: Path = ROOT, stage_dir: Path | None = None,
                    year: int = YEAR) -> dict[str, Any]:
    """Install missing city caches and quarantine source disagreements."""
    configured = paths(root, year)
    stage_dir = stage_dir or configured["output"]
    manifest, staged_rows = _load_stage(stage_dir, year)
    configured["api_cache_dir"].mkdir(parents=True, exist_ok=True)

    report_path = stage_dir / "reconciliation.json"
    previous_report = accounts._read_json(report_path, {})
    prior_entries = previous_report.get("entries", []) if isinstance(previous_report, dict) else []
    entries = list(prior_entries) if isinstance(prior_entries, list) else []
    entry_keys = {(str(entry.get("action")), str(entry.get("id")))
                  for entry in entries if isinstance(entry, dict)}

    planned_writes: list[tuple[Path, dict[str, Any]]] = []
    counts: Counter[str] = Counter()
    current_entries = []
    for municipality_id, finbra_row in staged_rows.items():
        cache_path = accounts._cache_path(configured["api_cache_dir"], municipality_id)
        if not cache_path.exists():
            planned_writes.append((cache_path, _copy_json(finbra_row)))
            counts["installedMissing"] += 1
            continue
        api_row = accounts._read_json(cache_path, None)
        if (not isinstance(api_row, dict) or str(api_row.get("id")) != municipality_id
                or api_row.get("year") != year):
            counts["existingInvalid"] += 1
            continue

        staged_values = _metric_values(finbra_row)
        api_values = _metric_values(api_row)
        api_declaration = api_row.get("declaration") if isinstance(api_row.get("declaration"), dict) else {}
        observed_finbra = [metric_id for metric_id, amount in staged_values.items() if _is_cents(amount)]
        if api_declaration.get("status") == "not_filed" and observed_finbra:
            updated = _copy_json(api_row)
            message = (
                "Conflito de fontes: o extrato do Siconfi informa ausência de DCA, mas a exportação FINBRA "
                "contém valores. A entrega e os indicadores permanecem sem conclusão até conciliação."
            )
            updated["status"] = "partial"
            updated["declaration"] = {"status": "unknown"}
            updated["metrics"] = []
            updated["collectionComplete"] = True
            updated["message"] = message
            original_source = updated.get("source") if isinstance(updated.get("source"), dict) else {}
            updated["source"] = _append_note(original_source, message)
            current_entries.append({
                "action": "delivery_conflict",
                "id": municipality_id,
                "apiDeclarationStatus": "not_filed",
                "finbraObservedMetrics": sorted(observed_finbra),
                "originalApiRow": _copy_json(api_row),
                "finbraStageRow": _copy_json(finbra_row),
            })
            planned_writes.append((cache_path, updated))
            counts["deliveryConflictRows"] += 1
            continue

        updated = _copy_json(api_row)
        changed_metrics = []
        metrics = updated.get("metrics")
        if isinstance(metrics, list):
            for metric in metrics:
                if not isinstance(metric, dict):
                    continue
                metric_id = str(metric.get("id") or "")
                api_value = metric.get("amountCents")
                finbra_value = staged_values.get(metric_id)
                if (_is_cents(api_value) and _is_cents(finbra_value)
                        and api_value != finbra_value):
                    changed_metrics.append({
                        "id": metric_id,
                        "apiCents": api_value,
                        "finbraCents": finbra_value,
                        "differenceCents": finbra_value - api_value,
                    })
                    metric["amountCents"] = None
                    metric_source = metric.get("source") if isinstance(metric.get("source"), dict) else {}
                    metric["source"] = _append_note(
                        metric_source,
                        "Valor ocultado por divergência com a exportação nacional FINBRA; consulte a conciliação da fonte.",
                    )
        if changed_metrics:
            message = "Conflito de fontes: alguns indicadores da API Siconfi diferem da exportação FINBRA e foram ocultados até conciliação."
            updated["status"] = "partial"
            updated["message"] = message
            original_source = updated.get("source") if isinstance(updated.get("source"), dict) else {}
            updated["source"] = _append_note(original_source, message)
            current_entries.append({
                "action": "numeric_conflict",
                "id": municipality_id,
                "conflictingMetrics": changed_metrics,
                "originalApiRow": _copy_json(api_row),
                "finbraStageRow": _copy_json(finbra_row),
            })
            planned_writes.append((cache_path, updated))
            counts["numericConflictRows"] += 1
            counts["numericConflictMetrics"] += len(changed_metrics)
        else:
            counts["existingUnchanged"] += 1

    for entry in current_entries:
        key = (str(entry["action"]), str(entry["id"]))
        if key not in entry_keys:
            entries.append(entry)
            entry_keys.add(key)

    report = {
        "generator": "ingest.finbra",
        "year": year,
        "generatedAt": _utc_now(),
        "stageManifest": "manifest.json",
        "counts": dict(counts),
        "entries": entries,
    }
    # Keep complete original API rows and FINBRA comparisons on disk before
    # changing any existing account cache.
    accounts._atomic_json(report_path, report)
    for cache_path, row in planned_writes:
        accounts._atomic_json(cache_path, row)

    manifest["reconciliation"] = {"report": "reconciliation.json", "counts": dict(counts)}
    accounts._atomic_json(stage_dir / "manifest.json", manifest)
    return report


def _publish(output_dir: Path, rows: dict[str, dict[str, Any]], manifest: dict[str, Any]) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    old_reconciliation = None
    if output_dir.exists():
        if (output_dir.is_symlink() or not output_dir.is_dir()
                or not (output_dir / "manifest.json").is_file()):
            raise FileExistsError(f"Refusing to replace unrecognized FINBRA stage: {output_dir}")
        try:
            old_manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FileExistsError(f"Refusing to replace unreadable FINBRA stage: {output_dir}") from exc
        if old_manifest.get("generator") != "ingest.finbra":
            raise FileExistsError(f"Refusing to replace unrecognized FINBRA stage: {output_dir}")
        old_reconciliation = accounts._read_json(output_dir / "reconciliation.json", None)

    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    backup = None
    try:
        for municipality_id, row in rows.items():
            accounts._atomic_json(temporary / f"{municipality_id}.json", row)
        if isinstance(old_reconciliation, dict):
            accounts._atomic_json(temporary / "reconciliation.json", old_reconciliation)
            manifest["reconciliation"] = {
                "report": "reconciliation.json",
                "counts": old_reconciliation.get("counts", {}),
                "preservedFromPreviousStage": True,
            }
        accounts._atomic_json(temporary / "manifest.json", manifest)
        if output_dir.exists():
            backup = output_dir.with_name(f".{output_dir.name}.backup-{uuid.uuid4().hex}")
            os.replace(output_dir, backup)
        try:
            os.replace(temporary, output_dir)
        except Exception:
            if backup is not None and backup.exists():
                os.replace(backup, output_dir)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def collect(root: Path = ROOT, year: int = YEAR,
            revenue_path: Path | None = None, expenses_path: Path | None = None,
            functions_path: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    configured = paths(root, year)
    inputs = {
        "revenue": revenue_path or configured["revenue"],
        "expenses": expenses_path or configured["expenses"],
        "functions": functions_path or configured["functions"],
    }
    output_dir = output_dir or configured["output"]
    catalog = accounts._catalog(configured["city_catalog"])
    catalog_by_id = {str(city["id"]): city for city in catalog}
    verified_ids = accounts._verified_ente_ids(configured["entities"], catalog)
    if not verified_ids:
        raise RuntimeError("A complete official SICONFI /entes cache is required to verify FINBRA city codes.")

    items_by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
    city_ufs: dict[str, set[str]] = defaultdict(set)
    file_info: dict[str, dict[str, Any]] = {}
    for file_key in ("revenue", "expenses", "functions"):
        file_info[file_key] = _read_finbra_file(inputs[file_key], file_key, year,
                                                items_by_city, city_ufs)

    rows: dict[str, dict[str, Any]] = {}
    excluded_codes: dict[str, str] = {}
    for municipality_id, items in items_by_city.items():
        if municipality_id in accounts.SPECIAL_MUNICIPALITIES:
            excluded_codes[municipality_id] = "special_territory"
            continue
        city = catalog_by_id.get(municipality_id)
        if city is None:
            excluded_codes[municipality_id] = "unknown_ibge_code"
            continue
        ufs = city_ufs[municipality_id]
        if len(ufs) != 1:
            raise ValueError(f"FINBRA files disagree on the UF for IBGE code {municipality_id}")
        source_uf = next(iter(ufs))
        if source_uf != str(city.get("uf") or "").upper():
            excluded_codes[municipality_id] = "uf_mismatch"
            continue
        if municipality_id not in verified_ids:
            excluded_codes[municipality_id] = "not_in_verified_entes_registry"
            continue

        summary_source = {
            "label": "Tesouro Nacional — Siconfi, FINBRA (exportação nacional)",
            "url": FINBRA_URL,
            "period": f"exercício de {year}",
            "fetchedAt": max(file_info[key]["fetchedAt"] for key in file_info),
            "status": "imported",
            "note": "Valores da exportação nacional; este arquivo não é um registro da situação de entrega da DCA.",
            "evidenceType": "national_finbra_export",
        }
        row = accounts._project_dca_items(items, municipality_id, year, summary_source,
                                          collection_complete=True)
        sources_by_metric = {
            spec["id"]: _metric_source(file_info[METRIC_FILES[spec["id"]]], year)
            for spec in accounts.METRIC_SPECS
        }
        for metric in row["metrics"]:
            metric["source"] = sources_by_metric[metric["id"]]
        complete_metrics = all(isinstance(metric.get("amountCents"), int)
                               and not isinstance(metric.get("amountCents"), bool)
                               for metric in row["metrics"])
        row.update({
            "identityVerified": True,
            "identityEvidence": "cadastro oficial Siconfi /entes; código IBGE e UF conferem com o catálogo IBGE",
            "collectionComplete": complete_metrics,
            "declaration": {"status": "unknown"},
            "message": "" if complete_metrics else
                "Exportação FINBRA parcial para esta cidade; indicadores ausentes permanecem sem valor. Situação de entrega da DCA não é inferida.",
        })
        rows[municipality_id] = row

    metric_coverage: dict[str, dict[str, int]] = {}
    fully_observed = 0
    for metric in accounts.METRIC_SPECS:
        values = [row_metric.get("amountCents")
                  for row in rows.values()
                  for row_metric in row["metrics"] if row_metric.get("id") == metric["id"]]
        metric_coverage[metric["id"]] = {
            "municipalitiesWithValue": sum(isinstance(value, int) and not isinstance(value, bool) for value in values),
            "municipalitiesMissingValue": sum(value is None for value in values),
        }
    for row in rows.values():
        if all(isinstance(metric.get("amountCents"), int) and not isinstance(metric.get("amountCents"), bool)
               for metric in row["metrics"]):
            fully_observed += 1

    api_comparison = _compare_api(rows, configured["api_cache_dir"], year)
    source_times = [info["fetchedAt"] for info in file_info.values()]
    output_files = [f"{municipality_id}.json" for municipality_id in sorted(rows)]
    manifest = {
        "generator": "ingest.finbra",
        "year": year,
        "generatedAt": _utc_now(),
        "source": {
            "label": "Tesouro Nacional — Siconfi, FINBRA (exportação nacional)",
            "url": FINBRA_URL,
            "period": f"exercício de {year}",
            "fetchedAtRange": {"earliest": min(source_times), "latest": max(source_times)},
            "status": "imported",
            "evidenceType": "national_finbra_export_not_delivery_status",
        },
        "files": file_info,
        "coverage": {
            "catalogMunicipalities": len(catalog),
            "verifiedEntesCodes": len(verified_ids),
            "inputMunicipalityCodes": len(items_by_city),
            "stagedMunicipalities": len(rows),
            "fullyObservedMunicipalities": fully_observed,
            "partialMunicipalities": len(rows) - fully_observed,
            "excludedCodesByReason": dict(Counter(excluded_codes.values())),
            "excludedCodes": excluded_codes,
            "metrics": metric_coverage,
            "apiDeliveryConflicts": len(api_comparison["apiNotFiledWithFinbraValues"]),
        },
        "apiComparison": api_comparison,
        "municipalityFiles": output_files,
    }
    _publish(output_dir, rows, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa os extratos nacionais FINBRA para uma área de estágio offline")
    parser.add_argument("--year", type=int, default=YEAR)
    parser.add_argument("--revenue", type=Path)
    parser.add_argument("--expenses", type=Path)
    parser.add_argument("--functions", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--install-missing", action="store_true",
                        help="instala municípios sem cache e concilia divergências comprovadas")
    args = parser.parse_args(argv)
    if args.year < 2014 or args.year > datetime.now(timezone.utc).year:
        parser.error("--year precisa ser um exercício disponível do Siconfi")
    if args.install_missing:
        if any(value is not None for value in (args.revenue, args.expenses, args.functions)):
            parser.error("--install-missing cannot be combined with input CSV overrides")
        report = install_missing(ROOT, args.output, args.year)
        result = {
            "output": str(args.output or paths(ROOT, args.year)["output"]),
            "reconciliation": report["counts"],
        }
    else:
        manifest = collect(ROOT, args.year, args.revenue, args.expenses, args.functions, args.output)
        result = {
            "output": str(args.output or paths(ROOT, args.year)["output"]),
            "coverage": manifest["coverage"],
            "apiComparison": {
                "apiCacheStatusesForStagedMunicipalities": manifest["apiComparison"]["apiCacheStatusesForStagedMunicipalities"],
                "metricComparisons": manifest["apiComparison"]["metricComparisons"],
                "apiNotFiledWithFinbraValues": len(manifest["apiComparison"]["apiNotFiledWithFinbraValues"]),
            },
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
