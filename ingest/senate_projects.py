"""Collect 2026 Senate-authored PL, PLP, and PEC records.

The default run is offline.  ``--collect`` queries the official Senado Federal
process API once per current senator; ``--refresh`` forces an update of every
cache entry.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
IMPORT_PATH = ROOT / "data" / "imports" / "legislative.json"
RAW_CACHE = ROOT / "data" / "raw" / "senado-projetos"
DEFAULT_OUTPUT = ROOT / "data" / "snapshots" / "senado-projetos.json"
API_BASE = "https://legis.senado.leg.br/dadosabertos"
API_PROCESS_URL = f"{API_BASE}/processo"
SOURCE_ID = "senado_senators_current"
USER_AGENT = "QuantoCusta/1.0 (public-profile collector)"
HTTP_TIMEOUT = 25
HTTP_RETRIES = 1
MAX_WORKERS = 4
REQUEST_INTERVAL = 0.15  # stay below the official 10 requests/second limit
PROJECT_TYPES = ("PL", "PLP", "PEC")
SENATOR_ID = re.compile(r"^senado:(\d+)$")

_request_lock = threading.Lock()
_last_request_at = 0.0


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: Any, limit: int = 12000) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] or None


def _official_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or not host
        or parts.username
        or parts.password
        or not (host == "senado.leg.br" or host.endswith(".senado.leg.br")
                or host == "senado.gov.br" or host.endswith(".senado.gov.br"))
    ):
        return None
    return value


def _senator_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("authorities"), list):
        raise ValueError("Importação legislativa sem lista de autoridades")
    identifiers = set()
    for row in payload["authorities"]:
        if not isinstance(row, dict) or row.get("sourceId") != SOURCE_ID or row.get("role") != "senador":
            continue
        match = SENATOR_ID.fullmatch(str(row.get("id") or ""))
        if match and _text(row.get("name")):
            identifiers.add(f"senado:{match.group(1)}")
    if not identifiers:
        raise ValueError("Importação legislativa sem senadores da lista oficial atual")
    return sorted(identifiers, key=lambda value: int(value.split(":", 1)[1]))


def _period_dates(year: int, today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    if year > today.year:
        raise ValueError("Não é possível confirmar cobertura de um ano futuro")
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), today) if year == today.year else date(year, 12, 31)
    return start.isoformat(), end.isoformat()


def _period_label(year: int, start: str, end: str) -> str:
    return f"PL, PLP e PEC apresentados de {start} a {end}"


def _project_url(authority_id: str, year: int, today: date | None = None) -> str:
    match = SENATOR_ID.fullmatch(authority_id)
    if not match:
        raise ValueError("ID de senador inválido")
    start, end = _period_dates(year, today)
    params: list[tuple[str, str]] = [
        ("codigoParlamentarAutor", match.group(1)),
        *(("sigla", project_type) for project_type in PROJECT_TYPES),
        ("dataInicioApresentacao", start),
        ("dataFimApresentacao", end),
    ]
    return f"{API_PROCESS_URL}?{urlencode(params)}"


def _wait_for_request_slot() -> None:
    global _last_request_at
    with _request_lock:
        now = time.monotonic()
        delay = REQUEST_INTERVAL - (now - _last_request_at)
        if delay > 0:
            time.sleep(delay)
        _last_request_at = time.monotonic()


def _request_json(url: str) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            _wait_for_request_slot()
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=HTTP_TIMEOUT) as response:
                payload = json.load(response)
            if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
                raise ValueError("Resposta do Senado sem lista de processos")
            return payload
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < HTTP_RETRIES:
                time.sleep(0.5)
    raise RuntimeError(f"Falha na consulta ao Senado ({type(last_error).__name__ if last_error else 'erro'})")


def _empty_projects(authority_id: str, year: int, detail: str, today: date | None = None) -> dict[str, Any]:
    start, end = _period_dates(year, today)
    return {
        "status": "unavailable",
        "period": _period_label(year, start, end),
        "sourceUrl": _project_url(authority_id, year, today),
        "fetchedAt": None,
        "total": None,
        "items": [],
        "detail": detail,
    }


def _parse_projects(
    authority_id: str,
    year: int,
    rows: Any,
    fetched_at: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Normalize the unpaginated process list, keeping only originating proposals."""
    result = _empty_projects(authority_id, year, "", today)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        result["detail"] = "Resposta do Senado sem lista válida de processos."
        return result

    start, end = _period_dates(year, today)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    malformed = False
    for row in rows:
        # The API's author filter may also surface a later substitute process
        # whose original initiative was authored by the senator.  Count only
        # proposals first presented as an initiating process in this period.
        objective = _text(row.get("objetivo"), 80)
        if not objective:
            malformed = True
            continue
        if objective.casefold() != "iniciadora":
            continue
        presented = _text(row.get("dataApresentacao"), 20)
        try:
            presented_date = date.fromisoformat(presented[:10]) if presented else None
        except ValueError:
            presented_date = None
        if not presented_date or not (start <= presented_date.isoformat() <= end):
            malformed = True
            continue
        identifier = _text(str(row.get("id") or ""), 80)
        if not identifier or not identifier.isdigit():
            malformed = True
            continue
        if identifier in seen:
            continue
        seen.add(identifier)
        title = _text(row.get("identificacao"), 240)
        source_url = _official_url(row.get("urlDocumento"))
        if not source_url:
            source_url = f"{API_BASE}/processo/{identifier}"
        items.append({
            "id": identifier,
            "titulo": title,
            "ementa": _text(row.get("ementa")),
            "situacao": None,
            "url": source_url,
        })

    result.update({
        "status": "partial" if malformed else "imported",
        "fetchedAt": fetched_at or utc_now(),
        "total": None if malformed else len(items),
        "items": items,
    })
    if malformed:
        result["detail"] = "A resposta foi recebida, mas havia linhas sem dados suficientes para confirmar o total."
    else:
        result.pop("detail", None)
    return result


def fetch_senate_projects(
    authority_id: str,
    year: int = 2026,
    request_json: Callable[[str], Any] = _request_json,
    today: date | None = None,
) -> dict[str, Any]:
    """Fetch all matching rows; this API response is an unpaginated JSON array."""
    url = _project_url(authority_id, year, today)
    try:
        rows = request_json(url)
    except Exception as error:
        result = _empty_projects(authority_id, year, "", today)
        result["detail"] = f"Falha na consulta ao Senado ({type(error).__name__}); total não confirmado."
        return result
    result = _parse_projects(authority_id, year, rows, today=today)
    result["sourceUrl"] = url
    return result


def _cache_path(authority_id: str, year: int, cache_root: Path) -> Path:
    match = SENATOR_ID.fullmatch(authority_id)
    if not match:
        raise ValueError("ID de senador inválido")
    return cache_root / f"senado-{match.group(1)}-{year}.json"


def _read_cache(authority_id: str, year: int, cache_root: Path) -> dict[str, Any] | None:
    path = _cache_path(authority_id, year, cache_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("id") != authority_id or payload.get("year") != year:
        return None
    projects = payload.get("projetos")
    if not isinstance(projects, dict) or projects.get("status") not in ("imported", "partial", "unavailable"):
        return None
    rows = projects.get("items")
    if not isinstance(rows, list):
        return None
    total = projects.get("total")
    if isinstance(total, bool) or (total is not None and (not isinstance(total, int) or total < 0)):
        total = None
    cleaned = {
        "status": projects.get("status"),
        "period": _text(projects.get("period"), 200),
        "sourceUrl": _official_url(projects.get("sourceUrl")),
        "fetchedAt": _text(projects.get("fetchedAt"), 40),
        "total": total,
        "items": [],
    }
    for item in rows:
        if not isinstance(item, dict):
            continue
        identifier = _text(str(item.get("id") or ""), 80)
        if not identifier or not identifier.isdigit():
            continue
        cleaned["items"].append({
            "id": identifier,
            "titulo": _text(item.get("titulo"), 240),
            "ementa": _text(item.get("ementa")),
            "situacao": None,
            "url": _official_url(item.get("url")),
        })
    detail = _text(projects.get("detail"), 300)
    if detail:
        cleaned["detail"] = detail
    if projects.get("stale") is True:
        cleaned["stale"] = True
    return cleaned


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _write_cache(authority_id: str, year: int, projects: dict[str, Any], cache_root: Path) -> None:
    _atomic_json(_cache_path(authority_id, year, cache_root), {
        "id": authority_id,
        "year": year,
        "projetos": projects,
    })


def _preserve_on_failure(previous: dict[str, Any] | None, failed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(previous, dict) or not previous.get("fetchedAt"):
        return failed
    preserved = deepcopy(previous)
    preserved["status"] = "partial"
    preserved["stale"] = True
    reason = _text(failed.get("detail"), 300) or "A consulta não foi concluída."
    old_detail = _text(preserved.get("detail"), 300)
    preserved["detail"] = f"Falha ao atualizar; última observação preservada. {reason}"
    if old_detail and old_detail not in preserved["detail"]:
        preserved["detail"] += f" Observação anterior: {old_detail}"
    return preserved


def _collect_one(
    authority_id: str,
    year: int,
    cache_root: Path,
    refresh: bool,
    request_json: Callable[[str], Any],
    today: date | None = None,
) -> dict[str, Any]:
    previous = _read_cache(authority_id, year, cache_root)
    start, end = _period_dates(year, today)
    requested_period = _period_label(year, start, end)
    if (
        previous
        and previous.get("status") == "imported"
        and previous.get("period") == requested_period
        and not refresh
    ):
        return previous
    try:
        refreshed = fetch_senate_projects(authority_id, year, request_json, today)
    except Exception as error:
        refreshed = _empty_projects(authority_id, year, "", today)
        refreshed["detail"] = f"Falha ao processar a consulta ({type(error).__name__}); total não confirmado."
    if refreshed.get("status") != "imported":
        refreshed = _preserve_on_failure(previous, refreshed)
    _write_cache(authority_id, year, refreshed, cache_root)
    return refreshed


def build_snapshot(
    root: Path = ROOT,
    output: Path | None = None,
    collect: bool = False,
    refresh: bool = False,
    year: int = 2026,
    limit: int | None = None,
    request_json: Callable[[str], Any] = _request_json,
    today: date | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    import_path = root / "data" / "imports" / "legislative.json"
    try:
        roster_payload = json.loads(import_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Importação legislativa ausente ou inválida") from error
    senator_ids = _senator_ids(roster_payload)
    cache_root = root / "data" / "raw" / "senado-projetos"
    targets = senator_ids[:limit] if collect and limit is not None else senator_ids
    projects_by_id: dict[str, dict[str, Any]] = {}
    if collect:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(_collect_one, authority_id, year, cache_root, refresh, request_json, today): authority_id
                for authority_id in targets
            }
            done = 0
            for future in as_completed(futures):
                authority_id = futures[future]
                try:
                    projects_by_id[authority_id] = future.result()
                except Exception as error:
                    previous = _read_cache(authority_id, year, cache_root)
                    failed = _empty_projects(authority_id, year, "", today)
                    failed["detail"] = f"Falha na coleta ({type(error).__name__}); total não confirmado."
                    projects_by_id[authority_id] = _preserve_on_failure(previous, failed)
                done += 1
                print(f"projetos do Senado consultados: {done}/{len(targets)}")
    for authority_id in senator_ids:
        if authority_id not in projects_by_id:
            projects_by_id[authority_id] = _read_cache(authority_id, year, cache_root) or _empty_projects(
                authority_id, year, "Projetos do Senado ainda não coletados.", today
            )

    snapshot = {
        "generatedAt": utc_now(),
        "year": year,
        "profiles": {
            authority_id: {"projetos": projects_by_id[authority_id]}
            for authority_id in senator_ids
        },
    }
    destination = output or (root / "data" / "snapshots" / "senado-projetos.json")
    _atomic_json(destination, snapshot)
    stats = {
        "senadores": len(senator_ids),
        "consultados": len(targets) if collect else 0,
        "imported": sum(value.get("status") == "imported" for value in projects_by_id.values()),
        "partial": sum(value.get("status") == "partial" for value in projects_by_id.values()),
        "unavailable": sum(value.get("status") == "unavailable" for value in projects_by_id.values()),
        "projects": sum(len(value.get("items", [])) for value in projects_by_id.values()),
    }
    return snapshot, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true", help="consulta a API oficial do Senado")
    parser.add_argument("--refresh", action="store_true", help="atualiza também caches completos")
    parser.add_argument("--year", type=int, default=2026, help="ano de apresentação (padrão: 2026)")
    parser.add_argument("--limit", type=int, help="limita o diagnóstico aos primeiros N senadores")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit deve ser maior que zero")
    if args.refresh and not args.collect:
        parser.error("--refresh requer --collect")
    try:
        _, stats = build_snapshot(
            collect=args.collect,
            refresh=args.refresh,
            year=args.year,
            limit=args.limit,
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(
        f"senadores={stats['senadores']} consultados={stats['consultados']} "
        f"importados={stats['imported']} parciais={stats['partial']} "
        f"indisponíveis={stats['unavailable']} projetos={stats['projects']}"
    )
    return 0 if stats["unavailable"] == 0 and stats["partial"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
