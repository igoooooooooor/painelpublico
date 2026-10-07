"""Cached municipal and election data from IBGE and TSE.

Offline snapshot: python3 ingest/cities.py
Refresh official sources: python3 ingest/cities.py --collect

The TSE candidate archives contain identity fields that this collector does
not need. Candidate ZIPs are read from a temporary stream; only an explicit
allowlist of public result fields is written to local caches and snapshots.
"""
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
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

YEAR = 2026
MUNICIPAL_ELECTION_YEAR = 2024
POPULATION_YEAR = 2026
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
DOWNLOAD_TIMEOUT = 180
CHUNK_SIZE = 1024 * 1024
TOP_VOTE_LIMIT = 10
CANDIDATE_CACHE_VERSION = 2

IBGE_MUNICIPALITIES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?orderBy=nome"
IBGE_POPULATION_URL = "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/{year}/variaveis/9324?localidades=N6%5Ball%5D"
IBGE_POPULATION_LABEL = "IBGE — Estimativas de população residente por município"
TSE_CROSSWALK_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/municipio_tse_ibge/municipio_tse_ibge.zip"
TSE_CANDIDATES_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{year}.zip"
TSE_VOTES_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2026.zip"
TSE_CANDIDATES_DATASET_URL = "https://dadosabertos.tse.jus.br/dataset/candidatos-{year}"
TSE_RESULTS_DATASET_URL = "https://dadosabertos.tse.jus.br/dataset/resultados-2026"
TSE_CROSSWALK_DATASET_URL = "https://dadosabertos.tse.jus.br/dataset/codigos-oficiais-de-uf-e-municipios-segundo-o-tse-e-o-ibge"

MUNICIPAL_OFFICES = {"PREFEITO", "VICE-PREFEITO", "VEREADOR"}
STATE_OFFICES = {
    "GOVERNADOR",
    "VICE-GOVERNADOR",
    "DEPUTADO ESTADUAL",
    "DEPUTADO DISTRITAL",
    "DEPUTADO FEDERAL",
    "SENADOR",
}
FEDERAL_OFFICE = "DEPUTADO FEDERAL"
ORDINARY_ELECTIONS = {
    2024: {"typeCode": "2", "typeName": "ELEICAO ORDINARIA", "dates": {"2024-10-06", "2024-10-27"}},
    2026: {"typeCode": "2", "typeName": "ELEICAO ORDINARIA", "dates": {"2026-10-04"}},
}
UF_CODES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

# The archive headers are projected by index. Do not replace this with a
# DictReader: it would materialize fields such as CPF, voter registration,
# birth date, email, or website in each candidate row.
CANDIDATE_FIELDS = (
    "SQ_CANDIDATO", "NR_TURNO", "CD_TIPO_ELEICAO", "NM_TIPO_ELEICAO", "DT_ELEICAO",
    "SG_UF", "SG_UE", "NM_UE",
    "DS_CARGO", "NM_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO",
    "DS_SIT_TOT_TURNO", "DT_GERACAO",
)
CANDIDATE_REQUIRED_FIELDS = {
    "SQ_CANDIDATO", "NR_TURNO", "CD_TIPO_ELEICAO", "NM_TIPO_ELEICAO", "DT_ELEICAO",
    "SG_UF", "SG_UE", "NM_UE", "DS_CARGO",
    "NM_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "DS_SIT_TOT_TURNO", "DT_GERACAO",
}
VOTE_FIELDS = (
    "NR_TURNO", "CD_MUNICIPIO", "NM_MUNICIPIO", "SG_UF", "DS_CARGO",
    "SQ_CANDIDATO", "QT_VOTOS_NOMINAIS_VALIDOS", "QT_VOTOS_NOMINAIS", "DT_GERACAO",
)
VOTE_REQUIRED_FIELDS = {
    "NR_TURNO", "CD_MUNICIPIO", "NM_MUNICIPIO", "SG_UF", "DS_CARGO", "SQ_CANDIDATO",
    "QT_VOTOS_NOMINAIS",
}


def paths(root: Path = ROOT) -> dict[str, Path]:
    raw = root / "data" / "raw"
    ibge = raw / "ibge"
    tse = raw / "tse"
    return {
        "municipalities": ibge / "municipalities.json",
        "municipalities_meta": ibge / "municipalities.meta.json",
        "population": ibge / "population.json",
        "population_meta": ibge / "population.meta.json",
        "crosswalk": tse / "municipio_tse_ibge.json",
        "crosswalk_meta": tse / "municipio_tse_ibge.meta.json",
        "municipal_candidates": tse / "candidacies_2024_v2.jsonl",
        "municipal_candidates_meta": tse / "candidacies_2024_v2.meta.json",
        "state_candidates": tse / "candidacies_2026_v2.jsonl",
        "state_candidates_meta": tse / "candidacies_2026_v2.meta.json",
        "state_candidate_ids": tse / "federal_candidate_ids_2026.json",
        "votes": tse / "votacao_candidato_munzona_2026.zip",
        "votes_meta": tse / "votacao_candidato_munzona_2026.meta.json",
        # This archive predates this collector. It is read only when no
        # sanitized cache exists, and the CSV reader still uses an allowlist.
        "existing_state_candidates_zip": tse / "consulta_cand_2026.zip",
        "output": root / "data" / "snapshots" / "cities.json",
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
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


def _atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    count = 0
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temp_name = stream.name
            for row in rows:
                json.dump(row, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                stream.write("\n")
                count += 1
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return count


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError:
        return default


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _meta(path: Path) -> dict[str, Any]:
    value = _read_json(path, {})
    return value if isinstance(value, dict) else {}


def _store_source_meta(path: Path, url: str, **values: Any) -> dict[str, Any]:
    payload = {"url": url, "fetchedAt": utc_now(), "status": "available", **values}
    _atomic_json(path, payload)
    return payload


def _mark_source_failure(meta_path: Path, url: str, error: Exception) -> None:
    prior = _meta(meta_path)
    stale = bool(prior.get("fetchedAt"))
    prior.update({
        "url": url,
        "status": "stale" if stale else "unavailable",
        "attemptedAt": utc_now(),
        "error": type(error).__name__,
        "note": "A última atualização falhou; os dados locais anteriores foram preservados." if stale
                else "A fonte não foi carregada; os dados desta seção permanecem indisponíveis.",
    })
    _atomic_json(meta_path, prior)


def _source(
    label: str,
    url: str,
    period: str | int | None,
    cache_path: Path,
    meta_path: Path,
    outcomes: dict[str, str],
    key: str,
) -> dict[str, Any]:
    meta = _meta(meta_path)
    present = cache_path.exists()
    status = outcomes.get(key)
    if not status:
        if not present:
            status = "unavailable"
        elif meta.get("status") == "stale":
            status = "stale"
        else:
            status = "cached"
    source_period = meta.get("period", period)
    if source_period in {"current", "TSE ↔ IBGE"}:
        source_period = "cadastro vigente na consulta"
    source = {
        "label": label,
        "url": url,
        "period": source_period,
        "fetchedAt": meta.get("fetchedAt") or _mtime_iso(cache_path),
        "status": status,
    }
    note = meta.get("note")
    if note:
        source["note"] = note
    return source


def _mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()


def _request(url: str):
    return urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}), timeout=DOWNLOAD_TIMEOUT)


def _read_response_bytes(response) -> bytes:
    body = response.read()
    if response.headers.get("Content-Encoding", "").lower() == "gzip" or body[:2] == b"\x1f\x8b":
        return gzip.decompress(body)
    return body


def _fetch_json(url: str, destination: Path, period: str | int | None = None) -> dict[str, Any]:
    with _request(url) as response:
        body = _read_response_bytes(response)
        last_modified = response.headers.get("Last-Modified")
    payload = json.loads(body.decode("utf-8"))
    if destination.name == "municipalities.json":
        _ibge_municipalities(payload)
    elif destination.name == "population.json":
        year, series = _population_series(payload)
        if year is None or not series:
            raise ValueError("IBGE population response contains no municipality series")
    _atomic_json(destination, payload)
    meta = _store_source_meta(
        destination.with_name(destination.stem + ".meta.json"), url,
        lastModified=last_modified, period=period, byteLength=len(body),
    )
    return meta


def _fetch_population(root_paths: dict[str, Path]) -> dict[str, Any]:
    errors: list[Exception] = []
    previous = _meta(root_paths["population_meta"])
    previous_year = previous.get("period")
    if not previous_year and root_paths["population"].exists():
        previous_year, _values = _population_series(_read_json(root_paths["population"], []))
    for year in (POPULATION_YEAR, POPULATION_YEAR - 1):
        if year < POPULATION_YEAR and previous_year and int(previous_year) >= year:
            break
        url = IBGE_POPULATION_URL.format(year=year)
        try:
            return _fetch_json(url, root_paths["population"], period=year)
        except Exception as error:
            errors.append(error)
    if errors:
        raise errors[-1]
    raise RuntimeError("No population period configured")


def _name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _code_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.isdigit():
        return str(int(text))
    return text


def _date_iso(value: Any) -> str | None:
    text = str(value or "").strip()[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    found = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", text)
    if found:
        return f"{found[3]}-{found[2]}-{found[1]}"
    return None


def _integer(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text or not re.fullmatch(r"\d+", text):
        return None
    return int(text)


def _normalize_office(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _is_ordinary_election(row: dict[str, Any], year: int) -> bool:
    expected = ORDINARY_ELECTIONS.get(year)
    return bool(
        expected
        and _code_key(row.get("CD_TIPO_ELEICAO")) == expected["typeCode"]
        and _name_key(row.get("NM_TIPO_ELEICAO")).upper() == expected["typeName"]
        and _date_iso(row.get("DT_ELEICAO")) in expected["dates"]
    )


ELECTED_STATUSES = {"ELEITO", "ELEITO POR QP", "ELEITO POR MEDIA"}


def _is_elected(value: Any) -> bool:
    return _name_key(value).upper() in ELECTED_STATUSES


def _turn(value: Any) -> int:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else 0


def _municipality_uf(row: dict[str, Any]) -> str | None:
    locality = row.get("microrregiao") or {}
    state = ((locality.get("mesorregiao") or {}).get("UF") or {})
    if not state:
        immediate = row.get("regiao-imediata") or {}
        state = (((immediate.get("regiao-intermediaria") or {}).get("UF")) or {})
    sigla = state.get("sigla")
    return str(sigla).upper() if sigla else None


def _ibge_municipalities(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("IBGE municipalities response is not a non-empty list")
    municipalities = []
    seen: set[str] = set()
    for row in payload:
        if not isinstance(row, dict) or not row.get("id") or not row.get("nome"):
            continue
        identifier = str(row["id"])
        name = str(row["nome"]).strip()
        uf = _municipality_uf(row)
        if not uf:
            # IBGE municipality IDs start with their official two-digit UF code.
            # Preserve the municipality, but leave an unknown UF unmapped.
            uf = None
        if identifier in seen:
            raise ValueError(f"Duplicate IBGE municipality code: {identifier}")
        seen.add(identifier)
        municipalities.append({"id": identifier, "name": name, "uf": uf})
    if not municipalities:
        raise ValueError("IBGE municipalities response contains no valid municipality")
    return sorted(municipalities, key=lambda item: (item["uf"] or "", _name_key(item["name"]), item["id"]))


def _population_series(payload: Any) -> tuple[int | None, dict[str, int]]:
    if not isinstance(payload, list):
        return None, {}
    values: dict[str, int] = {}
    year: int | None = None
    for aggregate in payload:
        if not isinstance(aggregate, dict):
            continue
        for result in aggregate.get("resultados") or []:
            for series in result.get("series") or []:
                locality = series.get("localidade") or {}
                identifier = str(locality.get("id") or "")
                observations = series.get("serie") or {}
                for key, raw_value in observations.items():
                    if not str(key).isdigit():
                        continue
                    parsed = _integer(raw_value)
                    if parsed is not None:
                        values[identifier] = parsed
                        year = max(year or 0, int(key))
    return year, values


def _csv_reader(binary: BinaryIO, encoding: str = "latin-1"):
    text = io.TextIOWrapper(binary, encoding=encoding, newline="")
    return csv.reader(text, delimiter=";")


def _header_indexes(header: list[str], fields: Iterable[str], required: set[str]) -> dict[str, int]:
    positions = {name.strip().lstrip("\ufeff"): index for index, name in enumerate(header)}
    missing = sorted(required.difference(positions))
    if missing:
        raise ValueError("Official CSV is missing required allowlisted columns: " + ", ".join(missing))
    return {field: positions[field] for field in fields if field in positions}


def _candidate_member(archive: zipfile.ZipFile, year: int) -> str:
    suffix = f"_{year}_BRASIL.CSV"
    member = next((name for name in archive.namelist() if name.upper().endswith(suffix)), None)
    if member is None:
        raise ValueError(f"TSE candidate archive has no national CSV for {year}")
    if not any(name.lower().endswith("leiame.pdf") for name in archive.namelist()):
        raise ValueError(f"TSE candidate archive has no {year} leiame.pdf")
    return member


def _candidate_projected_rows(
    binary: BinaryIO, year: int
) -> tuple[list[dict[str, Any]], set[str], dict[str, int], int, int]:
    reader = _csv_reader(binary)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError(f"Empty TSE candidate CSV for {year}") from exc
    indexes = _header_indexes(header, CANDIDATE_FIELDS, CANDIDATE_REQUIRED_FIELDS)
    municipal = year == MUNICIPAL_ELECTION_YEAR
    relevant_offices = MUNICIPAL_OFFICES if municipal else STATE_OFFICES
    eligible: dict[str, dict[str, Any]] = {}
    latest_rank: dict[str, tuple[int, str]] = {}
    federal_candidate_ids: set[str] = set()
    status_counts: Counter[str] = Counter()
    rows_seen = 0
    election_rows_excluded = 0

    for cells in reader:
        rows_seen += 1
        # Materialize only the approved columns immediately after CSV parsing.
        row = {field: (cells[index].strip() if index < len(cells) else "") for field, index in indexes.items()}
        if not _is_ordinary_election(row, year):
            election_rows_excluded += 1
            continue
        office = _normalize_office(row.get("DS_CARGO"))
        identifier = row.get("SQ_CANDIDATO", "")
        status = row.get("DS_SIT_TOT_TURNO", "")
        if status:
            status_counts[status] += 1
        if not municipal and office == FEDERAL_OFFICE and identifier:
            federal_candidate_ids.add(identifier)
        if office not in relevant_offices or not identifier:
            continue
        rank = (_turn(row.get("NR_TURNO")), _date_iso(row.get("DT_GERACAO")) or "")
        previous_rank = latest_rank.get(identifier)
        if previous_rank is not None and rank < previous_rank:
            continue
        latest_rank[identifier] = rank
        if not _is_elected(status):
            eligible.pop(identifier, None)
            continue
        eligible[identifier] = {
            "id": identifier,
            "name": row.get("NM_CANDIDATO", ""),
            "ballotName": row.get("NM_URNA_CANDIDATO", ""),
            "office": office,
            "party": row.get("SG_PARTIDO", ""),
            "uf": row.get("SG_UF", "").upper(),
            "year": year,
            "round": _turn(row.get("NR_TURNO")),
            "result": status,
            "sourceDate": _date_iso(row.get("DT_GERACAO")),
            **({"_tseCode": row.get("SG_UE", "")} if municipal else {}),
        }

    return (
        sorted(eligible.values(), key=lambda item: (item["uf"], item["office"], item["id"])),
        federal_candidate_ids,
        dict(status_counts),
        rows_seen,
        election_rows_excluded,
    )


def _project_candidate_archive(source: BinaryIO, destination: Path, year: int) -> tuple[dict[str, Any], set[str]]:
    source.seek(0)
    with zipfile.ZipFile(source) as archive:
        member = _candidate_member(archive, year)
        with archive.open(member) as binary:
            candidates, federal_ids, status_counts, rows_seen, election_rows_excluded = _candidate_projected_rows(binary, year)
    _atomic_jsonl(destination, candidates)
    meta = {
        "year": year,
        "period": year,
        "projectionVersion": CANDIDATE_CACHE_VERSION,
        "rowsSeen": rows_seen,
        "electionRowsExcluded": election_rows_excluded,
        "electedRows": len(candidates),
        "statusCounts": status_counts,
        "status": "available",
        "fetchedAt": utc_now(),
        "url": TSE_CANDIDATES_URL.format(year=year),
    }
    _atomic_json(destination.with_name(destination.stem + ".meta.json"), meta)
    if year == YEAR:
        _write_candidate_ids(destination.parent / "federal_candidate_ids_2026.json", federal_ids)
    return meta, federal_ids


def _download_candidate_archive(year: int, destination: Path) -> tuple[dict[str, Any], set[str]]:
    url = TSE_CANDIDATES_URL.format(year=year)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        last_modified = response.headers.get("Last-Modified")
        compressed_archive = response.read()
    size = len(compressed_archive)
    # The compressed candidacy archive is bounded (about 64 MB for 2024) and
    # lives only in memory. Its rows are projected before any persistent write.
    meta, federal_ids = _project_candidate_archive(io.BytesIO(compressed_archive), destination, year)
    meta.update({"lastModified": last_modified, "byteLength": size})
    _atomic_json(destination.with_name(destination.stem + ".meta.json"), meta)
    return meta, federal_ids


def _candidate_cache(path: Path, year: int, legacy_zip: Path | None = None) -> tuple[list[dict[str, Any]], set[str] | None, str]:
    if path.exists():
        meta = _meta(path.with_name(path.stem + ".meta.json"))
        if meta.get("projectionVersion") != CANDIDATE_CACHE_VERSION:
            return [], None, "unavailable"
        return _read_jsonl(path), None, "cached"
    if year == YEAR and legacy_zip and legacy_zip.exists():
        with zipfile.ZipFile(legacy_zip) as archive:
            member = _candidate_member(archive, year)
            with archive.open(member) as binary:
                candidates, federal_ids, _statuses, _rows, _excluded = _candidate_projected_rows(binary, year)
        return candidates, federal_ids, "cached"
    return [], None, "unavailable"


def _crosswalk_header(header: list[str]) -> dict[str, int]:
    normalized = {_name_key(value).replace(" ", ""): index for index, value in enumerate(header)}
    aliases = {
        "tseCode": ("cdmunicipiotse",),
        "tseName": ("nmmunicipiotse",),
        "ibgeId": ("cdmunicipioibge",),
        "ibgeName": ("nmmunicipioibge",),
        "uf": ("sguf",),
    }
    indexes: dict[str, int] = {}
    for target, names in aliases.items():
        index = next((normalized[name] for name in names if name in normalized), None)
        if index is not None:
            indexes[target] = index
    required = {"tseCode", "ibgeId", "uf"}
    if not required.issubset(indexes):
        raise ValueError("TSE crosswalk is missing required TSE/IBGE code columns")
    return indexes


def _read_crosswalk_archive(source: BinaryIO) -> list[dict[str, str]]:
    source.seek(0)
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if not any(name.lower().endswith("leiame.pdf") for name in names):
            raise ValueError("TSE municipality crosswalk has no leiame.pdf")
        member = next((name for name in names if name.lower().endswith(".csv")), None)
        if not member:
            raise ValueError("TSE municipality crosswalk has no CSV")
        with archive.open(member) as binary:
            reader = _csv_reader(binary)
            header = next(reader)
            indexes = _crosswalk_header(header)
            output = []
            for cells in reader:
                row = {key: cells[index].strip() if index < len(cells) else "" for key, index in indexes.items()}
                row["uf"] = row.get("uf", "").upper()
                if row.get("tseCode") and row.get("ibgeId") and row.get("uf"):
                    output.append(row)
    return output


def _download_crosswalk(destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as temp:
        request = Request(TSE_CROSSWALK_URL, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            last_modified = response.headers.get("Last-Modified")
            size = 0
            while True:
                block = response.read(CHUNK_SIZE)
                if not block:
                    break
                temp.write(block)
                size += len(block)
        rows = _read_crosswalk_archive(temp)
    _atomic_json(destination, rows)
    meta = _store_source_meta(destination.with_name(destination.stem + ".meta.json"), TSE_CROSSWALK_URL,
                              period="cadastro vigente na consulta", lastModified=last_modified,
                              byteLength=size, rows=len(rows))
    return meta


def _valid_tse_crosswalk(
    municipalities: list[dict[str, str]], rows: list[dict[str, str]]
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], set[str]]:
    ibge = {row["id"]: row for row in municipalities}
    by_tse: dict[str, dict[str, str]] = {}
    by_ibge: dict[str, dict[str, str]] = {}
    invalid: set[str] = set()
    valid_rows: list[dict[str, str]] = []
    tse_to_ibge: dict[str, set[str]] = defaultdict(set)
    ibge_to_tse: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        tse_code = str(row.get("tseCode") or "").strip()
        ibge_id = str(row.get("ibgeId") or "").strip()
        uf = str(row.get("uf") or "").strip().upper()
        city = ibge.get(ibge_id)
        if not tse_code or not city or city.get("uf") != uf:
            invalid.add(_code_key(tse_code) or "(missing)")
            continue
        normalized_code = _code_key(tse_code)
        valid_rows.append({"tseCode": tse_code, "ibgeId": ibge_id, "uf": uf,
                           "tseName": str(row.get("tseName") or ""), "ibgeName": str(row.get("ibgeName") or "")})
        tse_to_ibge[normalized_code].add(ibge_id)
        ibge_to_tse[ibge_id].add(normalized_code)
    conflicted_tse = {code for code, identifiers in tse_to_ibge.items() if len(identifiers) > 1}
    conflicted_ibge = {identifier for identifier, codes in ibge_to_tse.items() if len(codes) > 1}
    invalid.update(conflicted_tse)
    invalid.update(f"ibge:{identifier}" for identifier in conflicted_ibge)
    for row in valid_rows:
        code = _code_key(row["tseCode"])
        identifier = row["ibgeId"]
        if code in conflicted_tse or identifier in conflicted_ibge:
            continue
        by_tse[code] = row
        by_ibge[identifier] = row
    return by_tse, by_ibge, invalid


def _read_candidate_ids(path: Path) -> set[str] | None:
    value = _read_json(path, None)
    if not isinstance(value, list):
        return None
    return {str(identifier) for identifier in value if identifier}


def _write_candidate_ids(path: Path, identifiers: set[str]) -> None:
    _atomic_json(path, sorted(identifiers, key=lambda value: (not value.isdigit(), value)))


def _vote_csv_members(archive: zipfile.ZipFile) -> list[str]:
    members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    state_members = []
    for name in members:
        base = Path(name).stem.upper()
        match = re.search(r"_([A-Z]{2})$", base)
        if match and match.group(1) in UF_CODES:
            state_members.append(name)
    if state_members:
        return sorted(state_members)
    national = [name for name in members if Path(name).stem.upper().endswith("_BRASIL")]
    return sorted(national[:1])


def _parse_vote_archive(
    archive_path: Path,
    municipalities: list[dict[str, str]],
    tse_by_code: dict[str, dict[str, str]],
    elected_candidates: dict[str, dict[str, Any]],
    all_candidate_ids: set[str] | None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    observed: dict[str, dict[str, int]] = defaultdict(dict)
    unknown_ids: set[str] = set()
    non_elected_ids: set[str] = set()
    unmapped_codes: set[str] = set()
    invalid_pairs: set[tuple[str, str]] = set()
    candidate_state_mismatches = 0
    invalid_rows = 0
    votes_source_date: str | None = None
    if not archive_path.exists():
        return {}, {"unknownVoteCandidates": None, "unmappedVoteMunicipalCodes": None,
                    "voteRowsWithoutValidTotal": None, "municipalityCount": 0, "status": "unavailable"}
    if not elected_candidates:
        return {}, {"unknownVoteCandidates": 0 if all_candidate_ids is not None else None,
                    "unmappedVoteMunicipalCodes": 0, "voteRowsWithoutValidTotal": 0,
                    "municipalityCount": 0, "status": "available"}

    with zipfile.ZipFile(archive_path) as archive:
        members = _vote_csv_members(archive)
        if not members:
            raise ValueError("TSE vote archive has no municipal-zone CSV")
        for member in members:
            with archive.open(member) as binary:
                reader = _csv_reader(binary)
                try:
                    header = next(reader)
                except StopIteration:
                    continue
                indexes = _header_indexes(header, VOTE_FIELDS, VOTE_REQUIRED_FIELDS)
                for cells in reader:
                    office = _normalize_office(cells[indexes["DS_CARGO"]] if indexes["DS_CARGO"] < len(cells) else "")
                    if office != FEDERAL_OFFICE:
                        continue
                    identifier = cells[indexes["SQ_CANDIDATO"]].strip() if indexes["SQ_CANDIDATO"] < len(cells) else ""
                    if not identifier:
                        unknown_ids.add("")
                        continue
                    candidate = elected_candidates.get(identifier)
                    if not candidate:
                        if all_candidate_ids is not None and identifier not in all_candidate_ids:
                            unknown_ids.add(identifier)
                        elif all_candidate_ids is not None:
                            non_elected_ids.add(identifier)
                        continue
                    code = cells[indexes["CD_MUNICIPIO"]].strip() if indexes["CD_MUNICIPIO"] < len(cells) else ""
                    normalized_code = _code_key(code)
                    mapping = tse_by_code.get(normalized_code)
                    state = cells[indexes["SG_UF"]].strip().upper() if indexes["SG_UF"] < len(cells) else ""
                    if not mapping or mapping["uf"] != state:
                        unmapped_codes.add(normalized_code or "(missing)")
                        continue
                    turn = _turn(cells[indexes["NR_TURNO"]] if indexes["NR_TURNO"] < len(cells) else "")
                    if turn != 1:
                        continue
                    if candidate.get("uf") != state:
                        candidate_state_mismatches += 1
                        continue
                    vote_index = indexes.get("QT_VOTOS_NOMINAIS_VALIDOS", indexes["QT_VOTOS_NOMINAIS"])
                    raw_votes = cells[vote_index].strip() if vote_index < len(cells) else ""
                    votes = _integer(raw_votes)
                    if votes is None:
                        invalid_rows += 1
                        invalid_pairs.add((mapping["ibgeId"], identifier))
                        continue
                    date_index = indexes.get("DT_GERACAO")
                    if date_index is not None and date_index < len(cells) and votes_source_date is None:
                        votes_source_date = _date_iso(cells[date_index])
                    city_id = mapping["ibgeId"]
                    city_candidates = observed[city_id]
                    if votes > 0:
                        city_candidates[identifier] = city_candidates.get(identifier, 0) + votes

    result: dict[str, list[dict[str, Any]]] = {}
    for city_id, candidates in observed.items():
        for invalid_city, invalid_candidate in invalid_pairs:
            if city_id == invalid_city:
                candidates.pop(invalid_candidate, None)
        ordered = sorted(
            candidates.items(),
            key=lambda item: (
                -item[1],
                _name_key(elected_candidates[item[0]].get("ballotName") or elected_candidates[item[0]].get("name")),
                item[0],
            ),
        )
        if not ordered:
            continue
        selected = ordered[:TOP_VOTE_LIMIT]
        if len(ordered) > TOP_VOTE_LIMIT:
            cutoff = selected[-1][1]
            selected.extend(item for item in ordered[TOP_VOTE_LIMIT:] if item[1] == cutoff)
        result[city_id] = [
            {**_public_candidate(elected_candidates[identifier]), "votes": votes,
             "sourceDate": votes_source_date, "round": 1}
            for identifier, votes in selected
        ]
    return result, {
        "unknownVoteCandidates": len(unknown_ids),
        "nonElectedVoteCandidates": len(non_elected_ids) if all_candidate_ids is not None else None,
        "unmappedVoteMunicipalCodes": len(unmapped_codes),
        "unmappedVoteCodes": sorted(unmapped_codes),
        "voteCandidateStateMismatches": candidate_state_mismatches,
        "voteRowsWithoutValidTotal": invalid_rows,
        "municipalityCount": len(result),
        "status": "available",
    }


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    fields = ("id", "name", "ballotName", "office", "party", "uf", "year", "round", "result", "sourceDate")
    return {field: candidate.get(field) for field in fields}


def _download_votes(destination: Path, meta_path: Path, refresh: bool = False) -> dict[str, Any]:
    url = TSE_VOTES_URL
    destination.parent.mkdir(parents=True, exist_ok=True)
    prior = _meta(meta_path)
    if destination.exists() and not refresh:
        # A prior local archive can be reused after checking it is a valid TSE
        # ZIP. This avoids another hundreds-of-megabytes transfer.
        with zipfile.ZipFile(destination) as archive:
            if not _vote_csv_members(archive):
                raise ValueError("Cached TSE vote archive has no municipal-zone CSV")
        if prior.get("fetchedAt"):
            return {**prior, "status": "cached"}
        return _store_source_meta(meta_path, url, period=YEAR, status="cached",
                                  byteLength=destination.stat().st_size,
                                  lastModified=None, fetchedAt=_mtime_iso(destination))

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response, temporary.open("wb") as target:
            last_modified = response.headers.get("Last-Modified")
            expected = _integer(response.headers.get("Content-Length"))
            size = 0
            while True:
                block = response.read(CHUNK_SIZE)
                if not block:
                    break
                target.write(block)
                size += len(block)
            target.flush()
            os.fsync(target.fileno())
        if expected is not None and size != expected:
            raise ValueError(f"Incomplete TSE vote ZIP: {size} of {expected} bytes")
        with zipfile.ZipFile(temporary) as archive:
            if not _vote_csv_members(archive):
                raise ValueError("TSE vote archive has no municipal-zone CSV")
        os.replace(temporary, destination)
        return _store_source_meta(meta_path, url, period=YEAR, lastModified=last_modified, byteLength=size)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fetch_sources(root_paths: dict[str, Path], refresh: bool = False) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    tasks: list[tuple[str, Callable[[], Any], Path, str]] = [
        ("municipalities", lambda: _fetch_json(IBGE_MUNICIPALITIES_URL, root_paths["municipalities"], "cadastro vigente na consulta"), root_paths["municipalities_meta"], IBGE_MUNICIPALITIES_URL),
        ("population", lambda: _fetch_population(root_paths), root_paths["population_meta"], IBGE_POPULATION_URL.format(year=POPULATION_YEAR)),
        ("crosswalk", lambda: _download_crosswalk(root_paths["crosswalk"]), root_paths["crosswalk_meta"], TSE_CROSSWALK_URL),
        ("municipalCandidates", lambda: _download_candidate_archive(MUNICIPAL_ELECTION_YEAR, root_paths["municipal_candidates"]), root_paths["municipal_candidates_meta"], TSE_CANDIDATES_URL.format(year=MUNICIPAL_ELECTION_YEAR)),
        ("stateCandidates", lambda: _download_candidate_archive(YEAR, root_paths["state_candidates"]), root_paths["state_candidates_meta"], TSE_CANDIDATES_URL.format(year=YEAR)),
        ("votes", lambda: _download_votes(root_paths["votes"], root_paths["votes_meta"], refresh=refresh), root_paths["votes_meta"], TSE_VOTES_URL),
    ]
    for key, action, meta_path, url in tasks:
        cache_key = {
            "municipalities": "municipalities", "population": "population", "crosswalk": "crosswalk",
            "municipalCandidates": "municipal_candidates", "stateCandidates": "state_candidates", "votes": "votes",
        }[key]
        destination = root_paths[cache_key]
        if destination.exists() and not refresh and (key not in ("votes", "stateCandidates") or meta_path.exists()):
            outcomes[key] = "stale" if _meta(meta_path).get("status") == "stale" else "cached"
            continue
        try:
            action()
            outcomes[key] = "available"
        except Exception as error:
            _mark_source_failure(meta_path, url, error)
            outcomes[key] = "stale" if destination.exists() else "unavailable"
            print(f"{key}: {type(error).__name__}: {error}", file=sys.stderr)
    # If a sanitized cache predates the ID-only check, recover the set from the
    # pre-existing 2026 archive with the same CSV allowlist. No names or other
    # candidate fields are retained by this fallback.
    if root_paths["state_candidates"].exists() and not root_paths["state_candidate_ids"].exists():
        legacy = root_paths["existing_state_candidates_zip"]
        if legacy.exists():
            try:
                with zipfile.ZipFile(legacy) as archive:
                    member = _candidate_member(archive, YEAR)
                    with archive.open(member) as binary:
                        _candidates, federal_ids, _statuses, _rows, _excluded = _candidate_projected_rows(binary, YEAR)
                _write_candidate_ids(root_paths["state_candidate_ids"], federal_ids)
            except Exception as error:
                print(f"candidate-id-check: {type(error).__name__}: {error}", file=sys.stderr)
    return outcomes


def _load_snapshot_inputs(root_paths: dict[str, Path]) -> dict[str, Any]:
    municipalities_payload = _read_json(root_paths["municipalities"], None)
    municipalities = _ibge_municipalities(municipalities_payload) if municipalities_payload is not None else []
    population_payload = _read_json(root_paths["population"], [])
    population_year, population = _population_series(population_payload)
    if root_paths["population"].exists() and (population_year is None or not population):
        raise ValueError("Cached IBGE population response contains no municipality series")
    crosswalk_rows = _read_json(root_paths["crosswalk"], [])
    if not isinstance(crosswalk_rows, list):
        raise ValueError("Cached TSE–IBGE crosswalk is not a list")
    if root_paths["crosswalk"].exists() and not crosswalk_rows:
        raise ValueError("Cached TSE–IBGE crosswalk is empty")
    municipal_candidates, _unused_ids, municipal_status = _candidate_cache(root_paths["municipal_candidates"], MUNICIPAL_ELECTION_YEAR)
    state_candidates, legacy_ids, state_status = _candidate_cache(
        root_paths["state_candidates"], YEAR, root_paths["existing_state_candidates_zip"]
    )
    candidate_ids = _read_candidate_ids(root_paths["state_candidate_ids"])
    if candidate_ids is None:
        candidate_ids = legacy_ids
    return {
        "municipalities": municipalities,
        "population": population,
        "populationYear": population_year,
        "crosswalkRows": crosswalk_rows,
        "municipalCandidates": municipal_candidates,
        "municipalCandidateStatus": municipal_status,
        "stateCandidates": state_candidates,
        "stateCandidateStatus": state_status,
        "stateCandidateIds": candidate_ids,
    }


def _guard_snapshot_replacement(previous: Any, current: dict[str, Any]) -> None:
    if not isinstance(previous, dict):
        return
    current_sources = current.get("sources") or {}
    checks = (
        ("municipalities", bool(previous.get("municipalities")), "municipalities"),
        ("population", any(row.get("population") is not None for row in previous.get("municipalities", []) if isinstance(row, dict)), "population"),
        ("tseIbgeMapping", any(row.get("tseCode") for row in previous.get("municipalities", []) if isinstance(row, dict)), "tseIbgeMapping"),
        ("municipalElection", bool(previous.get("municipalElected")), "municipalElected"),
        ("generalElection", bool(previous.get("stateElected")), "stateElected"),
        ("votes", bool(previous.get("municipalVotes")), "municipalVotes"),
    )
    for source_key, had_data, _section in checks:
        if not had_data:
            continue
        source = current_sources.get(source_key) or {}
        if source.get("status") == "unavailable":
            raise RuntimeError(
                f"Refusing to replace cities snapshot: {source_key} cache is unavailable; "
                "restore its local cache or run --collect before rebuilding."
            )


def build_snapshot(root: Path = ROOT, collect: bool = False, refresh: bool = False) -> dict[str, Any]:
    where = paths(root)
    outcomes = _fetch_sources(where, refresh=refresh) if collect else {}
    inputs = _load_snapshot_inputs(where)
    municipalities = inputs["municipalities"]
    if not municipalities and inputs["population"]:
        # A cached population response includes all IBGE locality names and
        # codes. Without the main locality endpoint, no names/UFs are guessed.
        municipalities = []
    tse_by_code, tse_by_ibge, invalid_tse_codes = _valid_tse_crosswalk(
        municipalities, inputs["crosswalkRows"]
    )

    population = inputs["population"]
    population_year = inputs["populationYear"]
    city_rows = [
        {
            "id": city["id"],
            "name": city["name"],
            "uf": city.get("uf"),
            "population": population.get(city["id"]),
            "populationYear": population_year if city["id"] in population else None,
            "tseCode": (tse_by_ibge.get(city["id"]) or {}).get("tseCode"),
        }
        for city in municipalities
    ]
    municipality_by_id = {city["id"]: city for city in city_rows}
    municipal_elected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unmapped_municipal_candidate_codes: set[str] = set()
    for candidate in inputs["municipalCandidates"]:
        code = _code_key(candidate.get("_tseCode"))
        mapping = tse_by_code.get(code)
        if not mapping or mapping["uf"] != candidate.get("uf"):
            unmapped_municipal_candidate_codes.add(code or "(missing)")
            continue
        municipal_elected[mapping["ibgeId"]].append(_public_candidate(candidate))
    for candidates in municipal_elected.values():
        candidates.sort(key=lambda item: (
            _normalize_office(item["office"]),
            _name_key(item.get("ballotName") or item.get("name")),
            item["id"],
        ))

    state_elected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    elected_federal: dict[str, dict[str, Any]] = {}
    for candidate in inputs["stateCandidates"]:
        uf = str(candidate.get("uf") or "").upper()
        if uf not in UF_CODES:
            continue
        public = _public_candidate(candidate)
        state_elected[uf].append(public)
        if _normalize_office(candidate.get("office")) == FEDERAL_OFFICE:
            elected_federal[str(candidate["id"])] = candidate
    for candidates in state_elected.values():
        candidates.sort(key=lambda item: (
            _normalize_office(item["office"]),
            _name_key(item.get("ballotName") or item.get("name")),
            item["id"],
        ))

    vote_payload, vote_coverage = _parse_vote_archive(
        where["votes"], municipalities, tse_by_code, elected_federal, inputs["stateCandidateIds"]
    )
    municipal_votes = {
        city_id: candidates
        for city_id, candidates in vote_payload.items()
        if city_id in municipality_by_id and candidates
    }
    mapped_codes = set(tse_by_ibge)
    cities_with_municipal_elected = set(municipal_elected)
    cities_with_votes = set(municipal_votes)
    population_available = sum(city["population"] is not None for city in city_rows)

    sources = {
        "municipalities": _source("IBGE — Municípios e unidades da Federação", IBGE_MUNICIPALITIES_URL,
                                  "cadastro vigente na consulta", where["municipalities"], where["municipalities_meta"], outcomes, "municipalities"),
        "population": _source(IBGE_POPULATION_LABEL, IBGE_POPULATION_URL.format(year=population_year or POPULATION_YEAR),
                              population_year or POPULATION_YEAR, where["population"], where["population_meta"], outcomes, "population"),
        "municipalElection": _source("TSE — Candidaturas e resultado municipal", TSE_CANDIDATES_DATASET_URL.format(year=MUNICIPAL_ELECTION_YEAR),
                                     MUNICIPAL_ELECTION_YEAR, where["municipal_candidates"], where["municipal_candidates_meta"], outcomes, "municipalCandidates"),
        "generalElection": _source("TSE — Candidaturas e resultado geral", TSE_CANDIDATES_DATASET_URL.format(year=YEAR),
                                    YEAR, where["state_candidates"], where["state_candidates_meta"], outcomes, "stateCandidates"),
        "votes": _source("TSE — Votação nominal por município e zona", TSE_RESULTS_DATASET_URL,
                         YEAR, where["votes"], where["votes_meta"], outcomes, "votes"),
        "tseIbgeMapping": _source("TSE — Códigos oficiais de municípios TSE e IBGE", TSE_CROSSWALK_DATASET_URL,
                                  "cadastro vigente na consulta", where["crosswalk"], where["crosswalk_meta"], outcomes, "crosswalk"),
    }
    if any(vote_coverage.get(key) for key in (
        "unknownVoteCandidates", "unmappedVoteMunicipalCodes", "voteRowsWithoutValidTotal", "voteCandidateStateMismatches"
    )):
        sources["votes"]["status"] = "partial"
        sources["votes"]["note"] = (
            (sources["votes"].get("note") or "") +
            " Há registros sem correspondência ou totais incompletos na base nacional de votos. "
            "O destaque é parcial; agregados incompletos não são apresentados como totais confirmados."
        ).strip()
    coverage = {
        "municipalities": len(city_rows),
        "populationAvailable": population_available,
        "municipalitiesWithTseMapping": len(mapped_codes),
        "municipalitiesWithoutTseMapping": max(0, len(city_rows) - len(mapped_codes)),
        "unmappedTseCodes": len(invalid_tse_codes),
        "electedMunicipalCandidates": sum(len(candidates) for candidates in municipal_elected.values()),
        "municipalitiesWithMappedElection": len(cities_with_municipal_elected),
        "municipalitiesWithoutMappedElection": max(0, len(city_rows) - len(cities_with_municipal_elected)),
        "unmappedMunicipalCandidateCodes": len(unmapped_municipal_candidate_codes),
        "electedStateCandidates": sum(len(candidates) for candidates in state_elected.values()),
        "stateUfsWithElectedCandidates": len(state_elected),
        "municipalitiesWithObservedFederalVotes": len(cities_with_votes),
        "municipalitiesWithoutObservedFederalVotes": max(0, len(city_rows) - len(cities_with_votes)),
        "unknownVoteCandidates": vote_coverage.get("unknownVoteCandidates"),
        "nonElectedVoteCandidates": vote_coverage.get("nonElectedVoteCandidates"),
        "unmappedVoteMunicipalCodes": vote_coverage.get("unmappedVoteMunicipalCodes"),
        "voteRowsWithoutValidTotal": vote_coverage.get("voteRowsWithoutValidTotal"),
        "voteCandidateStateMismatches": vote_coverage.get("voteCandidateStateMismatches"),
    }
    snapshot = {
        "generatedAt": utc_now(),
        "sources": sources,
        "coverage": coverage,
        "municipalities": city_rows,
        "municipalElected": dict(sorted(municipal_elected.items())),
        "stateElected": dict(sorted(state_elected.items())),
        "municipalVotes": dict(sorted(municipal_votes.items())),
    }
    previous_snapshot = _read_json(where["output"], None)
    if inputs["stateCandidateStatus"] == "cached" and not where["state_candidates"].exists():
        sources["generalElection"]["status"] = "cached"
        sources["generalElection"]["fetchedAt"] = _mtime_iso(where["existing_state_candidates_zip"])
    _guard_snapshot_replacement(previous_snapshot, snapshot)
    _atomic_json(where["output"], snapshot)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monta a fotografia nacional de municípios e eleições")
    parser.add_argument("--collect", action="store_true", help="atualiza os dados oficiais em data/raw e monta o snapshot")
    parser.add_argument("--refresh", action="store_true", help="força o download dos arquivos já presentes; exige --collect")
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error("--refresh exige --collect")
    snapshot = build_snapshot(collect=args.collect, refresh=args.refresh)
    print("cidades", json.dumps(snapshot["coverage"], ensure_ascii=False, sort_keys=True))
    print("fontes", json.dumps({key: value["status"] for key, value in snapshot["sources"].items()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
