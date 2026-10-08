"""Offline-first monthly snapshots of the Câmara's housing allowance data.

The default run rebuilds ``data/snapshots/chamber-housing.json`` from sanitized
page caches. ``--collect`` fetches only missing monthly result pages and writes
each page atomically so interrupted collections can resume without repeating
successful requests. ``--refresh`` refetches every selected month without
replacing its cache until that month's pagination has been verified end to end.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from typing import Any
import uuid
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_YEAR = 2026
DEFAULT_MONTHS = tuple(range(1, 10))
LEGISLATURE = 57
PAGE_SIZE = 20
PAGE_LIMIT = 100
DOWNLOAD_TIMEOUT = 45
REQUEST_INTERVAL_SECONDS = 0.35
SOURCE_URL = "https://www.camara.leg.br/moradia/detalhamento"
SOURCE_LABEL = "Câmara dos Deputados — imóveis funcionais e auxílio-moradia"
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
TRUSTED_HOSTS = {"camara.leg.br", "www.camara.leg.br"}
_last_request_at = 0.0


def paths(root: Path = ROOT, year: int = DEFAULT_YEAR) -> dict[str, Path]:
    raw = root / "data" / "raw" / "mandate-cost" / "housing" / str(year)
    return {
        "cache_dir": raw,
        "roster": root / "data" / "imports" / "legislative.json",
        "output": root / "data" / "snapshots" / "chamber-housing.json",
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
    match = re.fullmatch(r"camara:(\d+)", str(value or "").strip())
    return f"camara:{match.group(1)}" if match else None


def load_roster(path: Path) -> list[dict[str, str]]:
    """Read only the current official Chamber roster from the local import."""
    payload = _read_json(path)
    authorities = payload.get("authorities") if isinstance(payload, dict) else None
    if not isinstance(authorities, list):
        raise ValueError(f"Current Câmara roster is missing from {path}")
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in authorities:
        if not isinstance(row, dict) or row.get("sourceId") != "camara_deputies_current":
            continue
        identifier = _person_id(row.get("id"))
        name = row.get("name")
        if identifier and isinstance(name, str) and name.strip() and identifier not in seen:
            output.append({"id": identifier, "name": name.strip()})
            seen.add(identifier)
    if not output:
        raise ValueError("The local legislative import contains no current Câmara deputies")
    return output


def _period(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _month_text(year: int, month: int) -> str:
    return f"{month:02d}/{year:04d}"


def query_url(year: int, month: int, page: int) -> str:
    if not 1 <= month <= 12 or page < 1:
        raise ValueError("Month or page is outside its valid range")
    query = urlencode({
        "legislatura": str(LEGISLATURE),
        "deputado": "Todos",
        "situacao": "todos",
        "cargo": "deputado",
        "ordenacao": "nome",
        "dataInicial": _month_text(year, month),
        "dataFinal": _month_text(year, month),
        "pagina": str(page),
    })
    return f"{SOURCE_URL}?{query}"


def _validate_query_url(url: str, year: int, month: int, page: int) -> None:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in TRUSTED_HOSTS
            or parts.path != urlsplit(SOURCE_URL).path):
        raise ValueError("Câmara housing response came from an untrusted URL")
    query = parse_qs(parts.query, keep_blank_values=True)
    expected = {
        "legislatura": str(LEGISLATURE),
        "deputado": "Todos",
        "situacao": "todos",
        "cargo": "deputado",
        "ordenacao": "nome",
        "dataInicial": _month_text(year, month),
        "dataFinal": _month_text(year, month),
        "pagina": str(page),
    }
    if any(query.get(key) != [value] for key, value in expected.items()):
        raise ValueError("Câmara housing response does not match the requested month and page")
    if set(query) != set(expected):
        raise ValueError("Câmara housing response contains unexpected query parameters")


class _ResultTableParser(HTMLParser):
    """Keep just text cells and row links; never retain the source HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self.text_parts: list[str] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {"parts": [], "href": None}
        elif tag == "a" and self._cell is not None:
            self._cell["href"] = attributes.get("href")
        elif tag == "br" and self._cell is not None:
            self._cell["parts"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._cell["text"] = " ".join("".join(self._cell["parts"]).split())
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self.text_parts.append(data)
        if self._cell is not None:
            self._cell["parts"].append(data)


def _as_brl_cents(value: str) -> int | None:
    """Parse one published Brazilian-real amount, preserving a source zero."""
    normalized = " ".join(value.replace("\xa0", " ").split())
    matches = re.findall(r"R\$\s*([+−-]?\s*[\d.]+,\d{2})", normalized, flags=re.IGNORECASE)
    if len(matches) != 1:
        return None
    amount_text = matches[0].replace(" ", "").replace("−", "-").replace(".", "").replace(",", ".")
    try:
        amount = Decimal(amount_text)
    except InvalidOperation:
        return None
    cents = amount * 100
    return int(cents) if cents == cents.to_integral_value() else None


def _functional_days(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s+dias?\s*", value, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _number(value: str) -> int:
    return int(value.replace(".", ""))


def _person_id_from_link(href: Any, year: int, month: int) -> str | None:
    if not isinstance(href, str):
        return None
    parts = urlsplit(urljoin(SOURCE_URL, href))
    if parts.scheme != "https" or parts.hostname not in TRUSTED_HOSTS:
        return None
    match = re.fullmatch(r"/moradia/(\d+)/(\d{4})/(\d{4})/(\d{2})/(\d{2})/(\d+)", parts.path)
    if not match:
        return None
    legislature, start_year, end_year, start_month, end_month, identifier = match.groups()
    if (int(legislature) != LEGISLATURE or int(start_year) != year or int(end_year) != year
            or int(start_month) != month or int(end_month) != month):
        return None
    return f"camara:{identifier}"


def _result_range(text: str, page: int) -> tuple[int, int, int]:
    matches = list(re.finditer(
        r"Exibindo\s+resultados\s+de\s+([\d.]+)\s+a\s+([\d.]+)\s+de\s+([\d.]+)\s+encontrados",
        text, flags=re.IGNORECASE,
    ))
    if matches:
        match = matches[0]
        first, last, total = (_number(item) for item in match.groups())
    else:
        empty = re.search(r"Exibindo\s+0\s+resultados?\s+encontrados", text, flags=re.IGNORECASE)
        if not empty:
            raise ValueError("Câmara housing page has no result count")
        first = last = total = 0
    expected_first = (page - 1) * PAGE_SIZE + 1 if total else 0
    expected_last = min(page * PAGE_SIZE, total) if total else 0
    if (first, last) != (expected_first, expected_last):
        raise ValueError("Câmara housing result range does not match the requested page")
    return first, last, total


def parse_month_page(
    html: str,
    final_url: str,
    year: int,
    month: int,
    page: int,
    response_hash: str,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Project one verified result page into a privacy-minimized cache entry."""
    _validate_query_url(final_url, year, month, page)
    parser = _ResultTableParser()
    parser.feed(html)
    visible_text = " ".join(" ".join(parser.text_parts).split())
    first, last, total = _result_range(visible_text, page)
    records = []
    for row in parser.rows:
        if len(row) < 4:
            continue
        person_id = next(
            (_person_id_from_link(cell.get("href"), year, month) for cell in row if cell.get("href")),
            None,
        )
        if not person_id:
            continue
        record = {
            "id": person_id,
            "functionalPropertyDays": _functional_days(row[1]["text"]),
            "housingAllowanceCents": _as_brl_cents(row[2]["text"]),
            "quotaComplementCents": _as_brl_cents(row[3]["text"]),
        }
        records.append(record)
    expected_count = max(0, last - first + 1)
    if len(records) != expected_count:
        raise ValueError("Câmara housing page contains an incomplete or wrong-period table")
    identifiers = [row["id"] for row in records]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Câmara housing page contains duplicate person rows")
    if not re.fullmatch(r"[a-f0-9]{64}", response_hash):
        raise ValueError("Câmara housing response hash is invalid")
    return {
        "year": year,
        "month": month,
        "period": _period(year, month),
        "page": page,
        "firstRow": first,
        "lastRow": last,
        "totalRows": total,
        "pageCount": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        "fetchedAt": fetched_at or _utc_now(),
        "sha256": response_hash,
        "source": {
            "label": SOURCE_LABEL,
            "url": final_url,
        },
        "records": records,
    }


def _cache_path(cache_dir: Path, year: int, month: int, page: int) -> Path:
    return cache_dir / f"{month:02d}" / f"page-{page}.json"


def _month_dir(cache_dir: Path, year: int, month: int) -> Path:
    return cache_dir / f"{month:02d}"


def _active_page_dir(cache_dir: Path, year: int, month: int) -> Path:
    """Read the atomically published generation, or the legacy month cache."""
    month_dir = _month_dir(cache_dir, year, month)
    pointer = _read_json(month_dir / "current.json")
    generation = pointer.get("generation") if isinstance(pointer, dict) else None
    if (
        isinstance(generation, str)
        and re.fullmatch(r"generations/[a-f0-9]{32}", generation)
        and (month_dir / generation).is_dir()
    ):
        return month_dir / generation
    return month_dir


def _staging_dir(cache_dir: Path, year: int, month: int) -> Path:
    return _month_dir(cache_dir, year, month) / "refresh-staging"


def _page_file(page_dir: Path, page: int) -> Path:
    return page_dir / f"page-{page}.json"


def _clear_staging(stage_dir: Path) -> None:
    if stage_dir.is_symlink():
        stage_dir.unlink()
    elif stage_dir.exists():
        if stage_dir.is_dir():
            shutil.rmtree(stage_dir)
        else:
            stage_dir.unlink()


def _publish_staging(
    cache_dir: Path,
    year: int,
    month: int,
    stage_dir: Path,
    page_count: int,
    total_rows: int,
) -> Path:
    """Publish a complete staged refresh by switching one atomic pointer."""
    month_dir = _month_dir(cache_dir, year, month)
    generations_dir = month_dir / "generations"
    generations_dir.mkdir(parents=True, exist_ok=True)
    generation_id = uuid.uuid4().hex
    generation_path = generations_dir / generation_id
    os.replace(stage_dir, generation_path)
    try:
        _atomic_json(month_dir / "current.json", {
            "generation": f"generations/{generation_id}",
            "pageCount": page_count,
            "totalRows": total_rows,
            "publishedAt": _utc_now(),
        })
    except Exception:
        os.replace(generation_path, stage_dir)
        raise
    return generation_path


def _read_page_cache(path: Path, year: int, month: int, page: int) -> dict[str, Any] | None:
    value = _read_json(path)
    if (not isinstance(value, dict) or value.get("year") != year or value.get("month") != month
            or value.get("period") != _period(year, month) or value.get("page") != page
            or not isinstance(value.get("records"), list)
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("sha256", "")))):
        return None
    allowed_page_fields = {
        "year", "month", "period", "page", "firstRow", "lastRow", "totalRows",
        "pageCount", "fetchedAt", "sha256", "source", "records",
    }
    if set(value) != allowed_page_fields:
        return None
    source = value.get("source")
    if (not isinstance(source, dict) or set(source) != {"label", "url"}
            or not isinstance(value.get("fetchedAt"), str)
            or not isinstance(value.get("totalRows"), int)
            or not isinstance(value.get("pageCount"), int)
            or len(value["records"]) != max(0, value.get("lastRow", 0) - value.get("firstRow", 1) + 1)):
        return None
    for record in value["records"]:
        if not isinstance(record, dict) or set(record) != {
            "id", "functionalPropertyDays", "housingAllowanceCents", "quotaComplementCents"
        } or not _person_id(record.get("id")):
            return None
        for field in ("functionalPropertyDays", "housingAllowanceCents", "quotaComplementCents"):
            field_value = record.get(field)
            if field_value is not None and (not isinstance(field_value, int) or isinstance(field_value, bool)):
                return None
    cache_ids = [record["id"] for record in value["records"]]
    if len(cache_ids) != len(set(cache_ids)):
        return None
    try:
        _validate_query_url(str(source.get("url") or ""), year, month, page)
    except ValueError:
        return None
    return value


def _fetch_page(year: int, month: int, page: int) -> dict[str, Any]:
    global _last_request_at
    url = query_url(year, month, page)
    delay = REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
    if delay > 0:
        time.sleep(delay)
    request = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    _last_request_at = time.monotonic()
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        body = response.read()
        final_url = response.geturl()
        charset = response.headers.get_content_charset() or "utf-8"
    digest = hashlib.sha256(body).hexdigest()
    return parse_month_page(body.decode(charset, errors="replace"), final_url, year, month, page, digest)


def _save_page(cache_dir: Path, page: dict[str, Any], page_dir: Path | None = None) -> None:
    directory = page_dir or _month_dir(cache_dir, page["year"], page["month"])
    _atomic_json(_page_file(directory, page["page"]), page)


def _refresh_month_pages(
    cache_dir: Path,
    year: int,
    month: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any], str | None]:
    """Resume a staged month and atomically publish it only when complete."""
    stage_dir = _staging_dir(cache_dir, year, month)
    stage_dir.mkdir(parents=True, exist_ok=True)
    first_path = _page_file(stage_dir, 1)
    first_page = _read_page_cache(first_path, year, month, 1)
    if first_path.exists() and first_page is None:
        _clear_staging(stage_dir)
        stage_dir.mkdir(parents=True, exist_ok=True)
        first_page = None

    if first_page is None:
        try:
            first_page = _fetch_page(year, month, 1)
        except Exception as exc:
            return {}, {
                "expectedPages": None,
                "totalRows": None,
                "attemptedAt": _utc_now(),
                "failedPage": 1,
            }, type(exc).__name__
        _save_page(cache_dir, first_page, stage_dir)

    total_pages = first_page["pageCount"]
    total_rows = first_page["totalRows"]
    if total_pages > PAGE_LIMIT:
        _clear_staging(stage_dir)
        return {}, {
            "expectedPages": total_pages,
            "totalRows": total_rows,
            "attemptedAt": _utc_now(),
            "failedPage": 1,
        }, "PageLimitExceeded"

    pages = {1: first_page}
    for page_number in range(2, total_pages + 1):
        page_path = _page_file(stage_dir, page_number)
        page = _read_page_cache(page_path, year, month, page_number)
        if page_path.exists() and page is None:
            _clear_staging(stage_dir)
            return {}, {
                "expectedPages": total_pages,
                "totalRows": total_rows,
                "attemptedAt": _utc_now(),
                "failedPage": page_number,
            }, "InvalidStagingPage"
        if page is None:
            try:
                page = _fetch_page(year, month, page_number)
            except Exception as exc:
                return {}, {
                    "expectedPages": total_pages,
                    "totalRows": total_rows,
                    "attemptedAt": _utc_now(),
                    "failedPage": page_number,
                }, type(exc).__name__
            if page["totalRows"] != total_rows or page["pageCount"] != total_pages:
                _clear_staging(stage_dir)
                return {}, {
                    "expectedPages": total_pages,
                    "totalRows": total_rows,
                    "attemptedAt": _utc_now(),
                    "failedPage": page_number,
                }, "InconsistentPageTotal"
            _save_page(cache_dir, page, stage_dir)
        elif page["totalRows"] != total_rows or page["pageCount"] != total_pages:
            _clear_staging(stage_dir)
            return {}, {
                "expectedPages": total_pages,
                "totalRows": total_rows,
                "attemptedAt": _utc_now(),
                "failedPage": page_number,
            }, "InconsistentStagingTotal"
        pages[page_number] = page

    try:
        _publish_staging(cache_dir, year, month, stage_dir, total_pages, total_rows)
    except Exception as exc:
        return {}, {
            "expectedPages": total_pages,
            "totalRows": total_rows,
            "attemptedAt": _utc_now(),
        }, type(exc).__name__
    return pages, {"expectedPages": total_pages, "totalRows": total_rows}, None


def _month_cache(
    cache_dir: Path,
    year: int,
    month: int,
    roster_ids: list[str],
    collect: bool,
    limit: int | None,
    refresh: bool = False,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any], str | None]:
    """Read or fetch pages for a month, keeping prior pages on failed refreshes."""
    if refresh:
        return _refresh_month_pages(cache_dir, year, month)

    requested_ids = set(roster_ids[:limit] if limit is not None else roster_ids)
    pages: dict[int, dict[str, Any]] = {}
    error = None
    attempt: dict[str, Any] = {}
    active_dir = _active_page_dir(cache_dir, year, month)
    first_page = _read_page_cache(_page_file(active_dir, 1), year, month, 1)
    if first_page is None and collect:
        try:
            first_page = _fetch_page(year, month, 1)
        except Exception as exc:  # a failed month must not stop other requested months
            error = type(exc).__name__
            attempt = {"attemptedAt": _utc_now(), "failedPage": 1}
        if first_page is not None:
            _save_page(cache_dir, first_page, active_dir)
    if first_page is not None:
        pages[1] = first_page
        total_pages = first_page["pageCount"]
        if total_pages > PAGE_LIMIT:
            error = "PageLimitExceeded"
            attempt = {"attemptedAt": _utc_now(), "failedPage": 1}
            total_pages = PAGE_LIMIT
    else:
        return pages, {"expectedPages": None, "totalRows": None, **attempt}, error

    seen_ids = {record.get("id") for record in first_page["records"]}
    for page_number in range(2, total_pages + 1):
        if requested_ids.issubset(seen_ids):
            break
        cached = _read_page_cache(_page_file(active_dir, page_number), year, month, page_number)
        if cached is None and collect:
            try:
                cached = _fetch_page(year, month, page_number)
                if cached["totalRows"] != first_page["totalRows"] or cached["pageCount"] != total_pages:
                    raise ValueError("Câmara housing result total changed during pagination")
                _save_page(cache_dir, cached, active_dir)
            except Exception as exc:
                error = type(exc).__name__
                attempt = {"attemptedAt": _utc_now(), "failedPage": page_number}
                break
        if cached is None:
            break
        if cached["totalRows"] != first_page["totalRows"] or cached["pageCount"] != total_pages:
            error = "InconsistentPageTotal"
            attempt = {"attemptedAt": _utc_now(), "failedPage": page_number}
            break
        pages[page_number] = cached
        seen_ids.update(record.get("id") for record in cached["records"])

    coverage = {
        "expectedPages": total_pages,
        "totalRows": first_page["totalRows"],
        **attempt,
    }
    return pages, coverage, error


def _month_observations(
    roster: list[dict[str, str]],
    pages: dict[int, dict[str, Any]],
    coverage: dict[str, Any],
    year: int,
    month: int,
    error: str | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    period = _period(year, month)
    records: dict[str, dict[str, Any]] = {}
    record_sources: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for page in pages.values():
        for row in page["records"]:
            identifier = row.get("id")
            if isinstance(identifier, str) and identifier.startswith("camara:"):
                if identifier in records:
                    duplicate_ids.add(identifier)
                    records.pop(identifier, None)
                    record_sources.pop(identifier, None)
                elif identifier not in duplicate_ids:
                    records[identifier] = row
                    source_page = page.get("source") if isinstance(page.get("source"), dict) else {}
                    record_sources[identifier] = {
                        "label": SOURCE_LABEL,
                        "url": source_page.get("url"),
                        "period": period,
                        "fetchedAt": page.get("fetchedAt"),
                        "status": "available",
                        "sha256": page.get("sha256"),
                    }

    expected_pages = coverage.get("expectedPages")
    source_pages_complete = (
        error is None
        and isinstance(expected_pages, int)
        and len(pages) == expected_pages
        and all(number in pages for number in range(1, expected_pages + 1))
        and len(records) == coverage.get("totalRows")
    )
    roster_ids = {person["id"] for person in roster}
    roster_complete = error is None and not duplicate_ids and roster_ids.issubset(records)
    complete = error is None and not duplicate_ids and (roster_complete or source_pages_complete)
    fetched_values = [page.get("fetchedAt") for page in pages.values() if isinstance(page.get("fetchedAt"), str)]
    page_hashes = [pages[number]["sha256"] for number in sorted(pages)]
    period_hash = hashlib.sha256("\n".join(page_hashes).encode("ascii")).hexdigest() if page_hashes else None
    source_status = "available" if complete else "partial" if pages else "unavailable"
    source = {
        "label": SOURCE_LABEL,
        "url": query_url(year, month, 1),
        "period": period,
        "fetchedAt": max(fetched_values) if fetched_values else None,
        "status": source_status,
        "sha256": period_hash,
    }
    if error:
        source["attemptStatus"] = "failed"
        source["attemptError"] = error
        if coverage.get("attemptedAt"):
            source["attemptedAt"] = coverage["attemptedAt"]
        if coverage.get("failedPage"):
            source["failedPage"] = coverage["failedPage"]
        source["note"] = f"Consulta incompleta ({error}); caches válidos foram preservados."

    observations: dict[str, dict[str, Any]] = {}
    for person in roster:
        identifier = person["id"]
        if identifier in duplicate_ids:
            observations[identifier] = {
                "period": period,
                "status": "partial",
                "housingAllowanceCents": None,
                "quotaComplementCents": None,
                "functionalPropertyDays": None,
                "source": {
                    **source,
                    "status": "partial",
                    "note": "A pessoa apareceu em mais de uma linha; valores conflitantes não foram usados.",
                },
            }
            continue
        record = records.get(identifier)
        if record is None:
            observations[identifier] = {
                "period": period,
                "status": "unavailable",
                "housingAllowanceCents": None,
                "quotaComplementCents": None,
                "functionalPropertyDays": None,
                "source": {
                    **source,
                    "status": "unavailable",
                    "note": (
                        "A pessoa não apareceu nas páginas consultadas; os valores não foram inferidos."
                        if complete else "A consulta parcial não localizou esta pessoa; os valores não foram inferidos."
                    ),
                },
            }
            continue
        allowance = record.get("housingAllowanceCents")
        complement = record.get("quotaComplementCents")
        days = record.get("functionalPropertyDays")
        valid_values = all(isinstance(value, int) and not isinstance(value, bool)
                           for value in (allowance, complement, days))
        observations[identifier] = {
            "period": period,
            "status": "available" if valid_values else "partial",
            "housingAllowanceCents": allowance if isinstance(allowance, int) and not isinstance(allowance, bool) else None,
            "quotaComplementCents": complement if isinstance(complement, int) and not isinstance(complement, bool) else None,
            "functionalPropertyDays": days if isinstance(days, int) and not isinstance(days, bool) else None,
            "source": {
                **record_sources[identifier],
                "status": "available" if valid_values else "partial",
            },
        }
    month_status = "available" if complete else "partial" if pages else "unavailable"
    month_metadata = {
        "status": month_status,
        "complete": complete,
        "rosterComplete": roster_complete,
        "sourcePagesComplete": source_pages_complete,
        "pagesCollected": len(pages),
        "pagesExpected": expected_pages,
        "totalRows": coverage.get("totalRows"),
        "observedRows": sum(len(page["records"]) for page in pages.values()),
        "duplicateRows": len(duplicate_ids),
        "source": source,
    }
    return observations, month_metadata


def _preserve_stale_observation(
    previous: Any,
    current: dict[str, Any],
    complete: bool,
    attempt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep a prior value when this run has no complete evidence to replace it."""
    if not isinstance(previous, dict):
        return current
    if complete:
        if previous.get("status") != "stale":
            return current
        previous_source = previous.get("source")
        current_source = current.get("source")
        if (
            isinstance(previous_source, dict)
            and isinstance(current_source, dict)
            and previous_source.get("fetchedAt") == current_source.get("fetchedAt")
            and previous_source.get("sha256") == current_source.get("sha256")
        ):
            # A complete offline rebuild from the same cache is not a fresh
            # source observation and must not erase stale attempt provenance.
            return previous
        return current
    if current.get("status") not in {"unavailable", "partial"}:
        return current
    previous_status = previous.get("status")
    if previous_status not in {"available", "partial", "stale"}:
        return current
    preserved = json.loads(json.dumps(previous))
    preserved["status"] = "stale"
    source = dict(preserved.get("source") or {})
    source.update({
        "status": "stale",
        "note": "A consulta atual ficou incompleta; a observação anterior foi preservada.",
    })
    if attempt:
        source["attemptedAt"] = attempt.get("attemptedAt") or _utc_now()
        source["attemptStatus"] = "failed"
        if attempt.get("attemptError"):
            source["attemptError"] = attempt["attemptError"]
        if attempt.get("failedPage"):
            source["failedPage"] = attempt["failedPage"]
    preserved["source"] = source
    return preserved


def build_snapshot(
    root: Path = ROOT,
    year: int = DEFAULT_YEAR,
    months: tuple[int, ...] = DEFAULT_MONTHS,
    collect: bool = False,
    limit: int | None = None,
    refresh: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the snapshot offline by default; collection errors stay per month."""
    if refresh and not collect:
        raise ValueError("--refresh requires --collect")
    if limit is not None and limit < 1:
        raise ValueError("--limit must be greater than zero")
    if any(not 1 <= month <= 12 for month in months):
        raise ValueError("Months must be between 1 and 12")
    where = paths(root, year)
    roster = load_roster(where["roster"])
    roster_ids = [person["id"] for person in roster]
    previous_snapshot = _read_json(where["output"])
    if not isinstance(previous_snapshot, dict) or previous_snapshot.get("year") != year:
        previous_snapshot = {}
    previous_profiles = previous_snapshot.get("profiles")
    profiles: dict[str, dict[str, Any]] = {}
    if isinstance(previous_profiles, dict):
        for identifier, previous_profile in previous_profiles.items():
            if not _person_id(identifier) or not isinstance(previous_profile, dict):
                continue
            previous_months = previous_profile.get("months")
            if not isinstance(previous_months, dict):
                continue
            profiles[identifier] = {"months": dict(previous_months)}
    for person in roster:
        profiles.setdefault(person["id"], {"months": {}})
    previous_coverage = previous_snapshot.get("coverage")
    old_months = previous_coverage.get("months") if isinstance(previous_coverage, dict) else None
    coverage_by_month: dict[str, Any] = dict(old_months) if isinstance(old_months, dict) else {}
    failures: dict[str, str] = {}

    for month in months:
        period = _period(year, month)
        pages, coverage, error = _month_cache(
            where["cache_dir"], year, month, roster_ids, collect, limit, refresh
        )
        if error:
            failures[period] = error
        observations, month_metadata = _month_observations(
            roster, pages, coverage, year, month, error
        )
        coverage_by_month[period] = month_metadata
        for identifier, observation in observations.items():
            previous_observation = profiles[identifier]["months"].get(period)
            profiles[identifier]["months"][period] = _preserve_stale_observation(
                previous_observation,
                observation,
                month_metadata["complete"],
                month_metadata["source"] if error else None,
            )

    snapshot = {
        "generatedAt": _utc_now(),
        "year": year,
        "source": SOURCE_LABEL,
        "coverage": {
            "rosterCount": len(roster),
            "months": coverage_by_month,
        },
        "profiles": profiles,
    }
    _atomic_json(where["output"], snapshot)
    return snapshot, failures


def parse_months(value: str) -> tuple[int, ...]:
    try:
        months = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("months must be comma-separated integers") from exc
    if not months or any(month < 1 or month > 12 for month in months):
        raise argparse.ArgumentTypeError("months must contain values from 1 to 12")
    if len(set(months)) != len(months):
        raise argparse.ArgumentTypeError("months must not contain duplicates")
    return months


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monta uma fotografia mensal de auxílio-moradia da Câmara")
    parser.add_argument("--collect", action="store_true", help="consulta as páginas mensais oficiais que faltam")
    parser.add_argument(
        "--refresh", action="store_true",
        help="refaz as páginas dos meses selecionados; requer --collect",
    )
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR, help="ano da consulta (padrão: 2026)")
    parser.add_argument(
        "--months", type=parse_months, default=DEFAULT_MONTHS,
        help="meses separados por vírgula (padrão: 1,2,...,9)",
    )
    parser.add_argument(
        "--limit", type=int,
        help="limita a coleta aos primeiros N deputados do cadastro; páginas já baixadas são preservadas",
    )
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error("--refresh requires --collect")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be greater than zero")
    try:
        snapshot, failures = build_snapshot(
            year=args.year, months=args.months, collect=args.collect, limit=args.limit,
            refresh=args.refresh,
        )
    except (OSError, ValueError) as exc:
        print(f"Câmara housing snapshot was not built: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    output = paths(ROOT, args.year)["output"]
    month_count = sum(len(person["months"]) for person in snapshot["profiles"].values())
    print(f"Wrote {output} ({len(snapshot['profiles'])} deputies, {month_count} person-month observations).")
    if failures:
        for period, error in failures.items():
            print(f"{period}: collection incomplete ({error})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
