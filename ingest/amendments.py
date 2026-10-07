"""Offline-first municipal emenda snapshots from the public CGU bulk file."""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import re
import sys
import tempfile
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, BinaryIO, Iterable
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

YEAR = 2026
DOWNLOAD_TIMEOUT = 180
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
SOURCE_URL = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
SOURCE_LABEL = "Portal da Transparência — Emendas parlamentares"
CSV_MEMBER = "EmendasParlamentares.csv"
SPECIAL_TRANSFER_TYPE = "Emenda Individual - Transferências Especiais"

SOURCE_FIELDS = (
    "Código da Emenda",
    "Ano da Emenda",
    "Tipo de Emenda",
    "Código do Autor da Emenda",
    "Nome do Autor da Emenda",
    "Localidade de aplicação do recurso",
    "Código Município IBGE",
    "Município",
    "UF",
    "Valor Empenhado",
    "Valor Pago",
    "Valor Restos A Pagar Pagos",
)
AMOUNT_FIELDS = {
    "committedCents": "Valor Empenhado",
    "paidCents": "Valor Pago",
    "restosPaidCents": "Valor Restos A Pagar Pagos",
}


def paths(root: Path = ROOT) -> dict[str, Path]:
    raw = root / "data" / "raw" / "amendments"
    return {
        "cache": raw / "emendas-parlamentares-unico-main.csv.gz",
        "manifest": raw / "emendas-parlamentares-unico-main.manifest.json",
        "legacy_cache": raw / "emendas-parlamentares-unico-main-2026-10-01.csv.gz",
        "legacy_manifest": raw / "emendas-parlamentares-unico-main-2026-10-01.manifest.json",
        "cities": root / "data" / "snapshots" / "cities.json",
        "output": root / "data" / "snapshots" / "amendments.json",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError:
        return default


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temp_name = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def _active_cache(where: dict[str, Path]) -> tuple[Path | None, Path | None]:
    if where["cache"].exists():
        return where["cache"], where["manifest"]
    if where["legacy_cache"].exists():
        return where["legacy_cache"], where["legacy_manifest"]
    return None, None


def _indexes(header: list[str]) -> dict[str, int]:
    columns = {name.strip().lstrip("\ufeff"): index for index, name in enumerate(header)}
    missing = [field for field in SOURCE_FIELDS if field not in columns]
    if missing:
        raise ValueError("Official emendas CSV is missing safe columns: " + ", ".join(missing))
    return {field: columns[field] for field in SOURCE_FIELDS}


def _project_row(cells: list[str], indexes: dict[str, int]) -> dict[str, str]:
    return {
        field: cells[index].strip() if index < len(cells) else ""
        for field, index in indexes.items()
    }


def _write_gzip_csv(path: Path, header: Iterable[str], rows: Iterable[dict[str, str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    count = 0
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as raw:
            temp_name = raw.name
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                text = io.TextIOWrapper(compressed, encoding="cp1252", newline="")
                writer = csv.writer(text, delimiter=";", lineterminator="\n")
                writer.writerow(list(header))
                for row in rows:
                    writer.writerow([row.get(field, "") for field in header])
                    count += 1
                text.flush()
                text.detach()
                if not count:
                    raise ValueError("Refusing to replace an emendas cache with an empty CSV")
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return count


def _project_zip_bytes(
    archive_bytes: bytes, cache_path: Path, *, fetched_at: str | None = None,
    last_modified: str | None = None, response_url: str | None = None,
) -> dict[str, Any]:
    """Project only the main safe CSV member; the downloaded ZIP stays in memory."""
    rows_seen = 0
    years: Counter[str] = Counter()

    def safe_rows(binary: BinaryIO):
        nonlocal rows_seen
        reader = csv.reader(io.TextIOWrapper(binary, encoding="cp1252", newline=""), delimiter=";")
        try:
            indexes = _indexes(next(reader))
        except StopIteration as error:
            raise ValueError("Official emendas CSV is empty") from error
        for cells in reader:
            row = _project_row(cells, indexes)
            year = row["Ano da Emenda"]
            if not re.fullmatch(r"\d{4}", year):
                raise ValueError("Official emendas CSV has an invalid proposal year")
            rows_seen += 1
            years[year] += 1
            yield row

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        # Never inspect or read any other ZIP member (notably PorFavorecido).
        try:
            member_info = archive.getinfo(CSV_MEMBER)
        except KeyError as error:
            raise ValueError(f"Official emendas ZIP is missing {CSV_MEMBER}") from error
        with archive.open(member_info) as binary:
            count = _write_gzip_csv(cache_path, SOURCE_FIELDS, safe_rows(binary))
    if not count:
        raise ValueError("Official emendas CSV contains no rows")
    return {
        "requested_url": SOURCE_URL,
        "final_url": response_url,
        "http_status": 200,
        "last_modified": last_modified,
        "fetched_at": fetched_at or _utc_now(),
        "projection": "Only allowlisted public columns from EmendasParlamentares.csv are retained; other archive members are not read.",
        "retained_member": CSV_MEMBER,
        "retained_header_fields": list(SOURCE_FIELDS),
        "retained_rows": count,
        "rows_by_emenda_year": dict(sorted(years.items())),
        "retained_size_gzip_bytes": cache_path.stat().st_size,
        "status": "available",
    }


def _download_and_project(where: dict[str, Path]) -> dict[str, Any]:
    request = Request(SOURCE_URL, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        archive_bytes = response.read()
        last_modified = response.headers.get("Last-Modified")
        response_url = response.geturl()
        response_status = getattr(response, "status", 200)
    if response_status != 200:
        raise ValueError(f"Official emendas source returned HTTP {response_status}")
    manifest = _project_zip_bytes(
        archive_bytes,
        where["cache"],
        fetched_at=_utc_now(),
        last_modified=last_modified,
        response_url=response_url,
    )
    manifest["http_status"] = response_status
    _atomic_json(where["manifest"], manifest)
    return manifest


def _mark_failure(manifest_path: Path | None, error: Exception) -> None:
    if manifest_path is None:
        return
    prior = _read_json(manifest_path, {})
    if not isinstance(prior, dict):
        prior = {}
    has_previous_data = bool(prior.get("retained_rows"))
    prior.update({
        "status": "stale" if has_previous_data else "unavailable",
        "attempted_at": _utc_now(),
        "error": type(error).__name__,
        "note": "A última atualização falhou; os dados locais anteriores foram preservados." if has_previous_data
                else "A fonte não foi carregada; os dados desta seção permanecem indisponíveis.",
    })
    _atomic_json(manifest_path, prior)


def _collect_source(where: dict[str, Path], refresh: bool = False) -> str:
    cache_path, manifest_path = _active_cache(where)
    if cache_path and not refresh:
        manifest = _read_json(manifest_path, {}) if manifest_path else {}
        return "stale" if isinstance(manifest, dict) and manifest.get("status") == "stale" else "cached"
    try:
        _download_and_project(where)
        return "available"
    except Exception as error:
        _mark_failure(manifest_path, error)
        print(f"emendas: {type(error).__name__}: {error}", file=sys.stderr)
        return "stale" if cache_path else "unavailable"


def _load_city_catalog(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path, None)
    if not isinstance(payload, dict) or not isinstance(payload.get("municipalities"), list):
        raise ValueError("IBGE city catalog snapshot is unavailable or malformed")
    cities = []
    seen: set[str] = set()
    for row in payload["municipalities"]:
        if not isinstance(row, dict) or not row.get("id") or not row.get("name"):
            continue
        identifier = str(row["id"])
        if identifier in seen:
            raise ValueError(f"Duplicate IBGE city code in catalog: {identifier}")
        seen.add(identifier)
        cities.append({"id": identifier, "name": str(row["name"]), "uf": row.get("uf")})
    if not cities:
        raise ValueError("IBGE city catalog snapshot contains no municipalities")
    return cities


def _amount_cents(value: Any) -> int | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    if "," in text:
        if text.count(",") != 1:
            return None
        integer, fraction = text.split(",", 1)
        if not fraction:
            return None
        sign = ""
        if integer.startswith(("-", "+")):
            sign, integer = integer[0], integer[1:]
        if "." in integer:
            if not re.fullmatch(r"\d{1,3}(?:\.\d{3})+", integer):
                return None
            integer = integer.replace(".", "")
        elif not re.fullmatch(r"\d+", integer):
            return None
        if fraction and not fraction.isdigit():
            return None
        text = f"{sign}{integer}.{fraction or '0'}"
    elif not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return None
    try:
        value_decimal = Decimal(text)
        if not value_decimal.is_finite():
            return None
        scaled = value_decimal * 100
        if scaled != scaled.to_integral_value():
            return None
        return int(scaled)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _new_total() -> dict[str, Any]:
    return {"sum": 0, "invalid": False, "observed": 0}


def _add_amount(total: dict[str, Any], value: int | None) -> None:
    if value is None:
        total["invalid"] = True
    else:
        total["sum"] += value
    total["observed"] += 1


def _new_metrics() -> dict[str, dict[str, Any]]:
    return {metric: _new_total() for metric in AMOUNT_FIELDS}


def _add_row_metrics(metrics: dict[str, dict[str, Any]], row: dict[str, str]) -> dict[str, int | None]:
    values = {metric: _amount_cents(row.get(source_field)) for metric, source_field in AMOUNT_FIELDS.items()}
    for metric, value in values.items():
        _add_amount(metrics[metric], value)
    return values


def _final_metrics(metrics: dict[str, dict[str, Any]]) -> dict[str, int | None]:
    return {
        metric: None if item["observed"] == 0 or item["invalid"] else item["sum"]
        for metric, item in metrics.items()
    }


def _iter_cache_rows(path: Path):
    stream = None
    reader = None
    indexes = None
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1252"):
        candidate = gzip.open(path, "rt", encoding=encoding, newline="")
        try:
            candidate_reader = csv.reader(candidate, delimiter=";")
            indexes = _indexes(next(candidate_reader))
            stream, reader = candidate, candidate_reader
            break
        except StopIteration as error:
            candidate.close()
            last_error = ValueError("Cached emendas CSV is empty")
            last_error.__cause__ = error
        except (UnicodeDecodeError, ValueError) as error:
            candidate.close()
            last_error = error
    if stream is None or reader is None or indexes is None:
        raise ValueError("Cached emendas CSV has no recognized safe header") from last_error
    with stream:
        count = 0
        for cells in reader:
            row = _project_row(cells, indexes)
            if not re.fullmatch(r"\d{4}", row["Ano da Emenda"]):
                raise ValueError("Cached emendas CSV has an invalid proposal year")
            count += 1
            yield row
        if not count:
            raise ValueError("Cached emendas CSV contains no rows")


def _new_city_state() -> dict[str, Any]:
    return {
        "recordCount": 0,
        "totals": _new_metrics(),
        "specialRecordCount": 0,
        "specialTotals": _new_metrics(),
        "authors": {},
        "records": {},
    }


def _add_named_amounts(metrics: dict[str, dict[str, Any]], values: dict[str, int | None]) -> None:
    for metric, value in values.items():
        _add_amount(metrics[metric], value)


def _aggregate(
    city_catalog: list[dict[str, Any]], rows: Iterable[dict[str, str]], year: int,
    cache_available: bool,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    catalog_ids = {city["id"] for city in city_catalog}
    city_states: dict[str, dict[str, Any]] = {}
    year_rows = 0
    national_metrics = _new_metrics()
    available_years: set[int] = set()
    excluded: Counter[str] = Counter()
    invalid_amount_rows = 0
    invalid_by_metric: Counter[str] = Counter()
    special_rows = 0
    municipalities_with_special: set[str] = set()
    special_amendment_codes: set[str] = set()
    special_municipality_codes: set[str] = set()
    national_authors: dict[str, dict[str, Any]] = {}

    for row in rows:
        row_year = int(row["Ano da Emenda"])
        available_years.add(row_year)
        if row_year != year:
            continue
        year_rows += 1
        national_values = _add_row_metrics(national_metrics, row)
        invalid_fields = [field for field, value in national_values.items() if value is None]
        if invalid_fields:
            invalid_amount_rows += 1
            invalid_by_metric.update(invalid_fields)

        author_id = row["Código do Autor da Emenda"].strip() or "(sem código)"
        author_name = row["Nome do Autor da Emenda"].strip() or "Sem informação"
        amendment_type = row["Tipo de Emenda"].strip() or "Sem informação"
        national_author = national_authors.setdefault(author_id, {
            "id": author_id,
            "nameVariants": set(),
            "types": set(),
            "recordCount": 0,
            "specialTransferCount": 0,
        })
        national_author["nameVariants"].add(author_name)
        national_author["types"].add(amendment_type)
        national_author["recordCount"] += 1
        is_special = amendment_type == SPECIAL_TRANSFER_TYPE
        if is_special:
            national_author["specialTransferCount"] += 1
            if row["Código da Emenda"].strip():
                special_amendment_codes.add(row["Código da Emenda"].strip())
            if row["Código Município IBGE"].strip():
                special_municipality_codes.add(row["Código Município IBGE"].strip())

        city_id = row["Código Município IBGE"].strip()
        if city_id not in catalog_ids:
            if city_id.casefold() in {"", "sem informação", "s/i", "sem codigo", "sem código"}:
                excluded["missingMunicipalityCode"] += 1
            elif not re.fullmatch(r"\d{7}", city_id):
                excluded["malformedMunicipalityCode"] += 1
            else:
                excluded["unknownMunicipalityCode"] += 1
            continue

        city = city_states.setdefault(city_id, _new_city_state())
        city["recordCount"] += 1
        city_values = _add_row_metrics(city["totals"], row)
        if is_special:
            special_rows += 1
            municipalities_with_special.add(city_id)
            city["specialRecordCount"] += 1
            _add_named_amounts(city["specialTotals"], city_values)

        author = city["authors"].setdefault(author_id, {
            "id": author_id,
            "nameVariants": set(),
            "types": set(),
            "recordCount": 0,
            "specialTransferCount": 0,
            "totals": _new_metrics(),
        })
        author["nameVariants"].add(author_name)
        author["types"].add(amendment_type)
        author["recordCount"] += 1
        if is_special:
            author["specialTransferCount"] += 1
        _add_named_amounts(author["totals"], city_values)

        amendment_id = row["Código da Emenda"].strip() or "Sem informação"
        record_key = (amendment_id, author_id, amendment_type)
        record = city["records"].setdefault(record_key, {
            "id": amendment_id,
            "authorName": author_name,
            "type": amendment_type,
            "specialTransfer": is_special,
            "recordCount": 0,
            "totals": _new_metrics(),
        })
        record["recordCount"] += 1
        _add_named_amounts(record["totals"], city_values)

    municipalities: dict[str, Any] = {}
    year_available = year in available_years
    for city in city_catalog:
        identifier = city["id"]
        state = city_states.get(identifier)
        if not state:
            empty_metrics = _new_metrics()
            empty_special_metrics = _new_metrics()
            municipalities[identifier] = {
                "status": "no_records" if cache_available and year_available else "unavailable",
                "totals": _final_metrics(empty_metrics),
                "recordCount": 0,
                "specialTransfers": {
                    "identified": True,
                    "totals": _final_metrics(empty_special_metrics),
                    "recordCount": 0,
                },
                "authors": [],
                "records": [],
            }
            continue

        authors = []
        for author in state["authors"].values():
            name_variants = sorted(author["nameVariants"], key=str.casefold)
            normalized_name_count = len({_name_key(value) for value in name_variants})
            authors.append({
                "id": author["id"],
                "name": name_variants[0] if name_variants else None,
                "nameVariants": name_variants,
                "nameConflict": normalized_name_count > 1,
                "types": sorted(author["types"], key=str.casefold),
                **_final_metrics(author["totals"]),
                "recordCount": author["recordCount"],
                "specialTransferCount": author["specialTransferCount"],
            })
        authors.sort(key=lambda item: (item["name"].casefold(), item["id"]))
        records = [
            {
                "id": record["id"],
                "authorName": record["authorName"],
                "type": record["type"],
                "specialTransfer": record["specialTransfer"],
                **_final_metrics(record["totals"]),
            }
            for record in state["records"].values()
        ]
        records.sort(key=lambda item: (item["id"].casefold(), item["authorName"].casefold(), item["type"].casefold()))
        special_totals = _final_metrics(state["specialTotals"])
        if state["specialRecordCount"] == 0:
            special_totals = {metric: None for metric in AMOUNT_FIELDS}
        municipalities[identifier] = {
            "status": "partial" if any(metric["invalid"] for metric in state["totals"].values()) else "available",
            "totals": _final_metrics(state["totals"]),
            "recordCount": state["recordCount"],
            "specialTransfers": {
                "identified": True,
                "totals": special_totals,
                "recordCount": state["specialRecordCount"],
            },
            "authors": authors,
            "records": records,
        }

    national_totals = _final_metrics(national_metrics)
    national_author_rows = [
        {
            "id": author["id"],
            "nameVariants": sorted(author["nameVariants"], key=str.casefold),
            "nameConflict": len({_name_key(value) for value in author["nameVariants"]}) > 1,
            "types": sorted(author["types"], key=str.casefold),
            "recordCount": author["recordCount"],
            "specialTransferCount": author["specialTransferCount"],
        }
        for author in national_authors.values()
    ]
    national_author_rows.sort(key=lambda item: item["id"])
    coverage = {
        "year": year,
        "yearAvailable": year_available,
        "availableYears": sorted(available_years),
        "nationalRows": year_rows,
        "nationalTotals": national_totals,
        "nationalTotalReconciliation": {
            "scope": "all proposal-year rows before municipality mapping",
            "rows": year_rows,
            "totals": national_totals,
        },
        "nationalAuthors": len(national_author_rows),
        "nationalAuthorsWithNameConflicts": sum(author["nameConflict"] for author in national_author_rows),
        "municipalRows": sum(state["recordCount"] for state in city_states.values()),
        "municipalitiesWithRecords": len(city_states),
        "municipalitiesWithoutRecords": max(0, len(city_catalog) - len(city_states)),
        "excludedRows": sum(excluded.values()),
        "excludedRowsByReason": dict(sorted(excluded.items())),
        "invalidAmountRows": invalid_amount_rows,
        "invalidAmountsByMetric": dict(sorted(invalid_by_metric.items())),
        "specialTransferRows": special_rows,
        "distinctSpecialTransferAmendments": len(special_amendment_codes),
        "specialTransferMunicipalityCodes": len(special_municipality_codes),
        "municipalitiesWithSpecialTransfers": len(municipalities_with_special),
    }
    return municipalities, coverage, national_author_rows


def _source_metadata(
    cache_path: Path | None, manifest_path: Path | None, year: int, status: str,
    note: str | None = None,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path, {}) if manifest_path else {}
    if not isinstance(manifest, dict):
        manifest = {}
    source = {
        "label": SOURCE_LABEL,
        "url": SOURCE_URL,
        "period": f"Emendas propostas em {year}; execução acumulada na fonte",
        "fetchedAt": manifest.get("fetched_at") or (_mtime_iso(cache_path) if cache_path else None),
        "status": status,
    }
    if manifest.get("last_modified"):
        source["lastModified"] = manifest["last_modified"]
    if note:
        source["note"] = note
    elif manifest.get("note"):
        source["note"] = manifest["note"]
    elif status == "unavailable":
        source["note"] = "A fonte não foi carregada; os dados desta seção permanecem indisponíveis."
    return source


def _guard_snapshot_replacement(previous: Any, current: dict[str, Any]) -> None:
    if not isinstance(previous, dict):
        return
    previous_coverage = previous.get("coverage") if isinstance(previous.get("coverage"), dict) else {}
    if previous.get("year") != current.get("year") or previous_coverage.get("municipalitiesWithRecords", 0) <= 0:
        return
    current_coverage = current.get("coverage") if isinstance(current.get("coverage"), dict) else {}
    if (current.get("source", {}).get("status") == "unavailable"
            or not current_coverage.get("yearAvailable")
            or current_coverage.get("municipalRows", 0) == 0):
        raise RuntimeError("Refusing to replace a useful amendments snapshot while its source is unavailable")


def build_snapshot(root: Path = ROOT, year: int = YEAR, collect: bool = False, refresh: bool = False) -> dict[str, Any]:
    where = paths(root)
    if refresh and not collect:
        raise ValueError("--refresh requires --collect")
    outcome = _collect_source(where, refresh=refresh) if collect else None
    cache_path, manifest_path = _active_cache(where)
    city_catalog = _load_city_catalog(where["cities"])
    rows = _iter_cache_rows(cache_path) if cache_path else ()
    cache_available = cache_path is not None
    municipalities, coverage, authors = _aggregate(city_catalog, rows, year, cache_available)
    if outcome:
        source_status = outcome
    elif not cache_path:
        source_status = "unavailable"
    else:
        manifest = _read_json(manifest_path, {}) if manifest_path else {}
        source_status = "stale" if isinstance(manifest, dict) and manifest.get("status") == "stale" else "cached"
    note = None
    if not coverage["yearAvailable"]:
        source_status = "unavailable"
        note = f"O ano de proposta {year} não consta entre as edições locais disponíveis."
    snapshot = {
        "generatedAt": _utc_now(),
        "year": year,
        "source": _source_metadata(cache_path, manifest_path, year, source_status, note),
        "coverage": coverage,
        "authors": authors,
        "municipalities": municipalities,
    }
    previous = _read_json(where["output"], None)
    _guard_snapshot_replacement(previous, snapshot)
    _atomic_json(where["output"], snapshot)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monta uma fotografia municipal de emendas parlamentares")
    parser.add_argument("--collect", action="store_true", help="atualiza a fonte oficial em data/raw e monta o snapshot")
    parser.add_argument("--refresh", action="store_true", help="força o download; exige --collect")
    parser.add_argument("--year", type=int, default=YEAR, help="ano da proposta da emenda (padrão: 2026)")
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error("--refresh exige --collect")
    snapshot = build_snapshot(collect=args.collect, refresh=args.refresh, year=args.year)
    print("emendas", json.dumps(snapshot["coverage"], ensure_ascii=False, sort_keys=True))
    print("fonte", json.dumps(snapshot["source"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
