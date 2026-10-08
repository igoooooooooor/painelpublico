#!/usr/bin/env python3
"""Build a monthly picture of actual Câmara exercise periods.

The default run is offline and rebuilds the snapshot from minimized XML caches.
``--collect`` fetches missing official exercise histories one deputy at a time
with low concurrency; each successful cache is saved atomically so a later run
can resume. Dates come from the Câmara's ``periodosExercicio`` field, not the
election or legislative-term dates.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YEAR = 2026
DEFAULT_MONTHS = tuple(range(1, 10))
ROSTER_SOURCE_ID = "camara_deputies_current"
SOURCE_LABEL = "Câmara dos Deputados — períodos de exercício parlamentar"
SOURCE_BASE_URL = "https://www.camara.gov.br/SitCamaraWS/Deputados.asmx/ObterDetalhesDeputado"
TRUSTED_HOSTS = {"www.camara.gov.br", "www.camara.leg.br"}
LEGISLATURE = 57
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
HTTP_TIMEOUT = 45
HTTP_RETRIES = 2
MAX_WORKERS = 2
MIN_REQUEST_INTERVAL = 0.4
SCHEMA_VERSION = 1
_REQUEST_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0
_PERSON_ID = re.compile(r"^camara:(\d+)$")


class SourceError(RuntimeError):
    """Raised when an official response cannot support a safe observation."""


def paths(root: Path = ROOT) -> dict[str, Path]:
    return {
        "cache_dir": root / "data" / "raw" / "mandate-cost" / "service",
        "roster": root / "data" / "imports" / "legislative.json",
        "output": root / "data" / "snapshots" / "chamber-service.json",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _person_id(value: Any) -> str | None:
    match = _PERSON_ID.fullmatch(str(value or "").strip())
    return f"camara:{match.group(1)}" if match else None


def load_roster(path: Path) -> list[dict[str, str]]:
    """Read only the current Câmara deputies from the local legislative import."""
    payload = _read_json(path)
    authorities = payload.get("authorities") if isinstance(payload, dict) else None
    if not isinstance(authorities, list):
        raise ValueError(f"Current Câmara roster is missing from {path}")
    roster: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in authorities:
        if not isinstance(row, dict) or row.get("sourceId") != ROSTER_SOURCE_ID:
            continue
        identifier = _person_id(row.get("id"))
        name = row.get("name")
        if identifier and isinstance(name, str) and name.strip() and identifier not in seen:
            roster.append({"id": identifier, "name": name.strip()})
            seen.add(identifier)
    if not roster:
        raise ValueError("The local legislative import contains no current Câmara deputies")
    return roster


def parse_months(value: str | None) -> tuple[int, ...]:
    """Parse comma-separated months and ranges such as ``1-9`` or ``1..9``."""
    if value is None:
        return DEFAULT_MONTHS
    months: set[int] = set()
    for part in re.split(r"[,;]", value):
        token = part.strip()
        match = re.fullmatch(r"(\d{1,2})(?:(?:-|\.\.)(\d{1,2}))?", token)
        if not match:
            raise ValueError(f"Invalid month: {token}")
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if not 1 <= first <= 12 or not 1 <= last <= 12 or last < first:
            raise ValueError(f"Month outside valid range: {token}")
        months.update(range(first, last + 1))
    if not months:
        raise ValueError("At least one month is required")
    return tuple(sorted(months))


def source_url(profile_id: str) -> str:
    match = _PERSON_ID.fullmatch(profile_id)
    if not match:
        raise ValueError("Invalid Câmara profile ID")
    return f"{SOURCE_BASE_URL}?{urlencode({'ideCadastro': match.group(1), 'numLegislatura': str(LEGISLATURE)})}"


def _validate_source_url(value: Any, profile_id: str) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    match = _PERSON_ID.fullmatch(profile_id)
    return bool(
        match
        and parts.scheme == "https"
        and parts.hostname in TRUSTED_HOSTS
        and parts.path == urlsplit(SOURCE_BASE_URL).path
        and parse_qs(parts.query) == {
            "ideCadastro": [match.group(1)],
            "numLegislatura": [str(LEGISLATURE)],
        }
    )


def _date_value(value: str | None) -> date | None:
    normalized = " ".join((value or "").replace("\xa0", " ").split())
    if not normalized:
        return None
    candidates = [normalized]
    if "T" in normalized:
        candidates.append(normalized.split("T", 1)[0])
    if " " in normalized:
        candidates.append(normalized.split(" ", 1)[0])
    for candidate in candidates:
        for format_string in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
            try:
                return datetime.strptime(candidate, format_string).date()
            except ValueError:
                pass
    raise SourceError("Official exercise history contains an invalid date")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_history_xml(
    body: bytes,
    profile_id: str,
    final_url: str | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Keep only dates from official exercise periods; discard personal details."""
    if final_url is not None and not _validate_source_url(final_url, profile_id):
        raise SourceError("Official exercise history URL does not match the requested deputy")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise SourceError("Official exercise history is not valid XML") from exc

    containers = [node for node in root.iter() if _local_name(node.tag) == "periodosExercicio"]
    if len(containers) != 1:
        raise SourceError("Official response has no unique periodosExercicio field")
    rows = [node for node in containers[0] if _local_name(node.tag) == "periodoExercicio"]
    periods: list[dict[str, str | None]] = []
    for row in rows:
        fields = {_local_name(child.tag): (child.text or "").strip() for child in row}
        start = _date_value(fields.get("dataInicio"))
        end = _date_value(fields.get("dataFim"))
        if start is None or (end is not None and end < start):
            raise SourceError("Official exercise history contains an invalid period")
        periods.append({
            "startDate": start.isoformat(),
            "endDate": end.isoformat() if end else None,
        })

    periods.sort(key=lambda item: (item["startDate"], item["endDate"] or "9999-12-31"))
    periods = _merge_overlapping_periods(periods)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "profileId": profile_id,
        "fetchedAt": fetched_at or _utc_now(),
        "source": {
            "label": SOURCE_LABEL,
            "url": final_url or source_url(profile_id),
            "sha256": hashlib.sha256(body).hexdigest(),
        },
        "periods": periods,
    }


def _merge_overlapping_periods(
    periods: list[dict[str, str | None]],
) -> list[dict[str, str | None]]:
    """Union duplicate/overlapping official intervals before counting days."""
    merged: list[dict[str, str | None]] = []
    for period in periods:
        start = date.fromisoformat(str(period["startDate"]))
        end = date.fromisoformat(str(period["endDate"])) if period["endDate"] else None
        if not merged:
            merged.append(dict(period))
            continue
        previous = merged[-1]
        previous_start = date.fromisoformat(str(previous["startDate"]))
        previous_end = date.fromisoformat(str(previous["endDate"])) if previous["endDate"] else None
        if previous_end is None:
            raise SourceError("An open-ended exercise period is followed by another period")
        if start <= previous_end:
            if end is None or end > previous_end:
                previous["endDate"] = end.isoformat() if end else None
            continue
        # Adjacent periods describe uninterrupted exercise and can be combined.
        if start == previous_end + timedelta(days=1):
            previous["endDate"] = end.isoformat() if end else None
            continue
        if start < previous_start:
            raise SourceError("Official exercise periods are out of order")
        merged.append(dict(period))
    return merged


def _cache_path(cache_dir: Path, profile_id: str) -> Path:
    match = _PERSON_ID.fullmatch(profile_id)
    if not match:
        raise ValueError("Invalid Câmara profile ID")
    return cache_dir / f"{match.group(1)}.json"


def _attempt_path(cache_dir: Path, profile_id: str) -> Path:
    match = _PERSON_ID.fullmatch(profile_id)
    if not match:
        raise ValueError("Invalid Câmara profile ID")
    return cache_dir / f"{match.group(1)}.attempt.json"


def _read_attempt(path: Path, profile_id: str) -> dict[str, str] | None:
    value = _read_json(path)
    if not isinstance(value, dict) or set(value) != {
        "profileId", "attemptedAt", "status", "error"
    }:
        return None
    if (
        value.get("profileId") != profile_id
        or not isinstance(value.get("attemptedAt"), str)
        or value.get("status") != "failed"
        or not isinstance(value.get("error"), str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", value["error"])
    ):
        return None
    return value


def _valid_snapshot_profile(value: Any, year: int) -> bool:
    if not isinstance(value, dict) or set(value) != {"name", "months"}:
        return False
    if not isinstance(value.get("name"), str) or not value["name"].strip():
        return False
    months = value.get("months")
    if not isinstance(months, dict):
        return False
    for period, observation in months.items():
        if not re.fullmatch(rf"{year:04d}-(?:0[1-9]|1[0-2])", str(period)):
            return False
        if not isinstance(observation, dict) or observation.get("period") != period:
            return False
        if observation.get("status") not in {"in_office", "outside_mandate", "unknown"}:
            return False
        days = observation.get("daysInOffice")
        if days is not None and (not isinstance(days, int) or isinstance(days, bool) or days < 0):
            return False
    return True


def _read_history_cache(path: Path, profile_id: str) -> dict[str, Any] | None:
    value = _read_json(path)
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "profileId", "fetchedAt", "source", "periods"
    }:
        return None
    source = value.get("source")
    if (
        value.get("schemaVersion") != SCHEMA_VERSION
        or value.get("profileId") != profile_id
        or not isinstance(value.get("fetchedAt"), str)
        or not isinstance(source, dict)
        or set(source) != {"label", "url", "sha256"}
        or source.get("label") != SOURCE_LABEL
        or not _validate_source_url(source.get("url"), profile_id)
        or not re.fullmatch(r"[a-f0-9]{64}", str(source.get("sha256", "")))
        or not isinstance(value.get("periods"), list)
    ):
        return None
    try:
        periods = _validate_periods(value["periods"])
    except (TypeError, ValueError, SourceError):
        return None
    return {**value, "periods": periods}


def _validate_periods(value: Any) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        raise SourceError("Exercise periods are missing")
    output = []
    previous_end: date | None = None
    for row in value:
        if not isinstance(row, dict) or set(row) != {"startDate", "endDate"}:
            raise SourceError("Exercise period has an unexpected shape")
        start = _date_value(row.get("startDate"))
        end = _date_value(row.get("endDate"))
        if start is None or (end is not None and end < start):
            raise SourceError("Exercise period contains invalid dates")
        if previous_end is not None and start <= previous_end:
            raise SourceError("Exercise periods overlap or are out of order")
        if previous_end is None and output:
            raise SourceError("An open-ended exercise period is followed by another period")
        output.append({"startDate": start.isoformat(), "endDate": end.isoformat() if end else None})
        previous_end = end
    return output


def _wait_for_request_slot() -> None:
    global _NEXT_REQUEST_AT
    with _REQUEST_LOCK:
        delay = _NEXT_REQUEST_AT - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _NEXT_REQUEST_AT = time.monotonic() + MIN_REQUEST_INTERVAL


def _fetch_history(profile_id: str) -> dict[str, Any]:
    url = source_url(profile_id)
    request = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/xml,text/xml",
    })
    last_error: Exception | None = None
    for attempt in range(HTTP_RETRIES + 1):
        _wait_for_request_slot()
        try:
            with urlopen(request, timeout=HTTP_TIMEOUT) as response:
                body = response.read()
                final_url = response.geturl()
            return parse_history_xml(body, profile_id, final_url)
        except (HTTPError, URLError, TimeoutError, OSError, SourceError) as exc:
            last_error = exc
            if attempt < HTTP_RETRIES:
                time.sleep(0.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return start, end


def _days_in_month(periods: list[dict[str, str | None]], year: int, month: int) -> int:
    month_start, month_end = _month_bounds(year, month)
    total = 0
    for period in periods:
        start = date.fromisoformat(str(period["startDate"]))
        end = date.fromisoformat(str(period["endDate"])) if period["endDate"] else month_end
        overlap_start = max(month_start, start)
        overlap_end = min(month_end, end)
        if overlap_start <= overlap_end:
            total += (overlap_end - overlap_start).days + 1
    return total


def _source_for_month(history: dict[str, Any]) -> dict[str, str]:
    source = history["source"]
    return {
        "label": source["label"],
        "url": source["url"],
        "sha256": source["sha256"],
        "fetchedAt": history["fetchedAt"],
    }


def _month_observation(
    history: dict[str, Any] | None,
    year: int,
    month: int,
    failure: str | None = None,
    refresh_attempt: dict[str, str] | None = None,
) -> dict[str, Any]:
    period_id = f"{year:04d}-{month:02d}"
    if history is None:
        return {
            "period": period_id,
            "status": "unknown",
            "daysInOffice": None,
            "exercisePeriods": [],
            "source": None,
            "error": failure,
            "stale": False,
            "refreshAttempt": refresh_attempt,
        }
    periods = _validate_periods(history["periods"])
    days = _days_in_month(periods, year, month)
    status = "in_office" if days else ("outside_mandate" if periods else "unknown")
    if not periods:
        days = None
    month_start, month_end = _month_bounds(year, month)
    overlaps = []
    for item in periods:
        start = date.fromisoformat(str(item["startDate"]))
        end = date.fromisoformat(str(item["endDate"])) if item["endDate"] else month_end
        if max(start, month_start) <= min(end, month_end):
            overlaps.append(item)
    return {
        "period": period_id,
        "status": status,
        "daysInOffice": days,
        "exercisePeriods": overlaps,
        "source": _source_for_month(history),
        "error": failure,
        "stale": refresh_attempt is not None,
        "refreshAttempt": refresh_attempt,
    }


def build_snapshot(
    root: Path = ROOT,
    year: int = DEFAULT_YEAR,
    months: tuple[int, ...] = DEFAULT_MONTHS,
    *,
    collect: bool = False,
    refresh: bool = False,
    limit: int | None = None,
    profile_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    if year < 2000 or year > 9998:
        raise ValueError("Year outside valid range")
    if any(not 1 <= month <= 12 for month in months) or not months:
        raise ValueError("Months outside valid range")
    if refresh and not collect:
        raise ValueError("--refresh requires --collect")
    if limit is not None and limit < 1:
        raise ValueError("Limit must be positive")

    configured_paths = paths(root)
    roster = load_roster(configured_paths["roster"])
    if profile_id is not None:
        normalized_id = _person_id(profile_id)
        if not normalized_id:
            raise ValueError("Invalid Câmara profile ID")
        roster = [row for row in roster if row["id"] == normalized_id]
        if not roster:
            roster = [{"id": normalized_id, "name": normalized_id}]
    if limit is not None:
        roster = roster[:limit]

    cache_dir = configured_paths["cache_dir"]
    histories: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    requested = []
    for person in roster:
        identifier = person["id"]
        cached = _read_history_cache(_cache_path(cache_dir, identifier), identifier)
        if cached is not None and not refresh:
            histories[identifier] = cached
        elif collect:
            requested.append(identifier)
        else:
            failures[identifier] = "MissingCache"

    if requested:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_fetch_history, identifier): identifier for identifier in requested}
            for future in as_completed(futures):
                identifier = futures[future]
                try:
                    history = future.result()
                    _atomic_json(_cache_path(cache_dir, identifier), history)
                    histories[identifier] = history
                except Exception as exc:
                    failures[identifier] = type(exc).__name__

    profile_values: dict[str, Any] = {}
    coverage: dict[str, Any] = {
        "rosterCount": len(roster),
        "fullRoster": profile_id is None and limit is None,
        "historiesAvailable": len(histories),
        "historiesMissing": len(roster) - len(histories),
        "months": {},
    }
    for person in roster:
        identifier = person["id"]
        history = histories.get(identifier)
        month_values = {
            f"{year:04d}-{month:02d}": _month_observation(
                history, year, month, failures.get(identifier)
            )
            for month in months
        }
        profile_values[identifier] = {"name": person["name"], "months": month_values}

    for month in months:
        month_key = f"{year:04d}-{month:02d}"
        counts = {"in_office": 0, "outside_mandate": 0, "unknown": 0}
        for person in profile_values.values():
            counts[person["months"][month_key]["status"]] += 1
        coverage["months"][month_key] = {
            "status": "complete" if counts["unknown"] == 0 and roster else "partial",
            "rosterCount": len(roster),
            "statusCounts": counts,
        }

    snapshot = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _utc_now(),
        "year": year,
        "months": [f"{year:04d}-{month:02d}" for month in months],
        "source": {
            "label": SOURCE_LABEL,
            "description": "Official actual exercise intervals (periodosExercicio), inclusive dates.",
            "rosterSourceId": ROSTER_SOURCE_ID,
        },
        "coverage": coverage,
        "profiles": profile_values,
    }
    _atomic_json(configured_paths["output"], snapshot)
    return snapshot, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconstrói períodos mensais de exercício da Câmara")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR, help="ano de referência")
    parser.add_argument("--months", help="meses separados por vírgula e intervalos como 1-9")
    parser.add_argument("--collect", action="store_true", help="consulta históricos oficiais ausentes")
    parser.add_argument("--refresh", action="store_true", help="refaz a coleta; exige --collect")
    parser.add_argument("--limit", type=int, help="limita a reconstrução aos primeiros N deputados")
    parser.add_argument("--profile-id", help="limita a reconstrução a um ID camara:<número>")
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error("--refresh requires --collect")
    try:
        months = parse_months(args.months)
        snapshot, failures = build_snapshot(
            year=args.year,
            months=months,
            collect=args.collect,
            refresh=args.refresh,
            limit=args.limit,
            profile_id=args.profile_id,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(
        f"Snapshot Câmara: {len(snapshot['profiles'])} deputados, "
        f"{snapshot['coverage']['historiesAvailable']} históricos disponíveis, "
        f"{len(failures)} ausências/falhas."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
