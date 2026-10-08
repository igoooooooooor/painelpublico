#!/usr/bin/env python3
"""Collect the Câmara's public monthly payroll details for current deputies.

The default run is offline. ``--collect`` fetches one public detail page per
deputy and month, plus the official monthly consolidated CSVs. The CSVs are
parsed in memory and reduced to aggregate sheet counts and component totals
for the exact ``Parlamentar`` group. Individual payroll codes and other groups
are never persisted. A profile-month remains partial whenever supplementary
payroll rows exist but the source does not link them to the public deputy ID.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unicodedata
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
IMPORT_PATH = ROOT / "data" / "imports" / "legislative.json"
RAW_ROOT = ROOT / "data" / "raw" / "mandate-cost" / "payroll" / "camara"
DEFAULT_OUTPUT = ROOT / "data" / "snapshots" / "chamber-payroll.json"
ROSTER_SOURCE_ID = "camara_deputies_current"
CHAMBER_HOST = "www.camara.leg.br"
REPORT_HOST = "www2.camara.leg.br"
REPORT_INDEX_URL = (
    "https://www2.camara.leg.br/transparencia/recursos-humanos/remuneracao/"
    "relatorios-consolidados-por-ano-e-mes/{year}/"
)
SOURCE_NAME = "Câmara dos Deputados — remuneração mensal"
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
HTTP_TIMEOUT = 45
HTTP_RETRIES = 2
MAX_WORKERS = 2
MIN_REQUEST_INTERVAL = 0.25
SCHEMA_VERSION = 1

COMPONENTS: dict[str, tuple[str, ...]] = {
    "fixed_remuneration": ("remuneracao fixa",),
    "personal_advantages": ("vantagens de natureza pessoal",),
    "commission_role": ("funcao ou cargo em comissao",),
    "christmas_bonus": ("gratificacao natalina",),
    "vacation_third": ("ferias (1/3 constitucional)", "ferias 1/3 constitucional"),
    "other_eventual_remuneration": (
        "outras remuneracoes eventuais/provisorias",
        "outras remuneracoes eventuais/provisoria",
    ),
    "permanence_bonus": ("abono de permanencia", "abono permanencia"),
    "constitutional_reduction": ("redutor constitucional",),
    "pension_contribution": (
        "contribuicao previdenciaria",
        "constribuicao previdenciaria",
    ),
    "income_tax": ("imposto de renda",),
    "after_mandatory_deductions": ("remuneracao apos descontos obrigatorios",),
    "daily_allowances": ("diarias",),
    "allowances": ("auxilios",),
    "indemnity_benefits": ("vantagens indenizatorias",),
}
_COMPONENT_LABELS = {
    _normalize: key
    for key, labels in COMPONENTS.items()
    for _normalize in labels
}
_MONTHS_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_MONTHS_BY_NUMBER = {number: name for name, number in _MONTHS_PT.items()}
_PROFILE_ID = re.compile(r"^camara:(\d+)$")
_PERIOD = re.compile(r"(\d{2})/(\d{4})\s*-\s*(.+)$")
_REQUEST_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0


class SourceError(RuntimeError):
    """Raised when an official response cannot support a safe observation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    normalized = "".join(char for char in decomposed if not unicodedata.combining(char))
    normalized = normalized.replace("(*)", "").replace("*", "")
    return " ".join(normalized.casefold().split())


def _official_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    host = (parts.hostname or "").casefold()
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or host not in {CHAMBER_HOST, REPORT_HOST}
    ):
        return None
    return value


def _official_report_month_url(value: Any, year: int, month: int) -> bool:
    if _official_url(value) is None or month not in _MONTHS_BY_NUMBER:
        return False
    path = urlsplit(value).path.rstrip("/")
    month_name = _MONTHS_BY_NUMBER[month]
    return bool(re.search(
        rf"/{month_name}-de-{year}(?:-csv|-\d+)?$",
        path,
        re.IGNORECASE,
    ))


def _official_detail_url(value: Any, profile_id: str, year: int, month: int) -> bool:
    match = _PROFILE_ID.fullmatch(profile_id)
    if not match or not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return (
        parts.scheme == "https"
        and parts.hostname == CHAMBER_HOST
        and parts.path == f"/deputados/{match.group(1)}/remuneracao-deputado-detalhado"
        and parse_qs(parts.query).get("mesAno") == [f"{month:02d}{year}"]
    )


def detail_url(profile_id: str, year: int, month: int) -> str:
    match = _PROFILE_ID.fullmatch(profile_id)
    if not match or not 1 <= month <= 12 or year < 2000:
        raise ValueError("ID de perfil ou período inválido")
    return (
        f"https://{CHAMBER_HOST}/deputados/{match.group(1)}/"
        f"remuneracao-deputado-detalhado?mesAno={month:02d}{year}"
    )


def parse_months(value: str | None, year: int, today: date | None = None) -> list[int]:
    """Parse comma-separated months and ranges such as ``1-9`` or ``1..9``."""
    if value is None:
        today = today or date.today()
        last_month = today.month - 1 if year == today.year else 12
        if year > today.year:
            raise ValueError("Não é possível coletar meses futuros")
        return list(range(1, last_month + 1))
    months: set[int] = set()
    for part in re.split(r"[,;]", value):
        token = part.strip()
        match = re.fullmatch(r"(\d{1,2})(?:(?:-|\.\.)(\d{1,2}))?", token)
        if not match:
            raise ValueError(f"Mês inválido: {token}")
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if not 1 <= first <= 12 or not 1 <= last <= 12 or last < first:
            raise ValueError(f"Mês fora do intervalo: {token}")
        months.update(range(first, last + 1))
    if not months:
        raise ValueError("Informe ao menos um mês")
    return sorted(months)


def parse_cents(value: Any) -> int | None:
    """Parse a Brazilian currency value into cents; missing text stays missing."""
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.replace("\xa0", " ").split())
    normalized = re.sub(r"^R\$\s*", "", normalized, flags=re.IGNORECASE)
    if not re.fullmatch(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}", normalized):
        return None
    negative = normalized.startswith("-")
    unsigned = normalized[1:] if negative else normalized
    whole, fraction = unsigned.replace(".", "").split(",", 1)
    cents = int(whole) * 100 + int(fraction)
    return -cents if negative else cents


class _PayrollHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self._table: dict[str, Any] | None = None
        self._caption: list[str] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "table":
            self._table = {"caption": "", "rows": []}
        elif self._table is not None and tag == "caption":
            self._caption = []
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._table is not None and self._row is not None and tag in {"td", "th"}:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._caption is not None:
            self._caption.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "caption" and self._table is not None and self._caption is not None:
            self._table["caption"] = " ".join(" ".join(self._caption).split())
            self._caption = None
        elif tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join(" ".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._table is not None and self._row is not None:
            self._table["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table["caption"]:
                self.tables.append(self._table)
            self._table = None


def _sheet_identity(label: str) -> tuple[str, str, int | None]:
    normalized = " ".join(label.strip().split())
    key = _key(normalized)
    if key == "folha normal":
        return normalized.upper(), "normal", None
    if key == "folha complementar":
        return normalized.upper(), "complementary", None
    match = re.fullmatch(r"folha\s+complementar\s*-\s*(\d+)", key)
    if match:
        number = int(match.group(1))
        return normalized.upper(), "complementary", number
    if key in {
        "folha de adiantamento gratificacao natalina",
        "folha de adiantamento de gratificacao natalina",
    }:
        return normalized.upper(), "advance_christmas_bonus", None
    return normalized.upper(), "unknown", None


def parse_payroll_html(
    payload: bytes | str,
    profile_id: str,
    year: int,
    month: int,
    source_url: str | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Extract every payroll table from one profile-month response."""
    if not _PROFILE_ID.fullmatch(profile_id):
        raise SourceError("ID público da Câmara inválido.")
    if not 1 <= month <= 12:
        raise SourceError("Mês solicitado inválido.")
    if isinstance(payload, bytes):
        raw = payload
        html = payload.decode("utf-8", "replace")
    elif isinstance(payload, str):
        html = payload
        raw = payload.encode("utf-8")
    else:
        raise SourceError("Resposta oficial sem HTML.")
    if not html.strip():
        raise SourceError("Resposta oficial vazia.")
    parser = _PayrollHTMLParser()
    parser.feed(html)
    candidates = [
        table for table in parser.tables
        if _key(table.get("caption", "")).startswith(
            _key("Mês/Ano de Referência/Tipo Folha:")
        )
    ]
    if not candidates:
        raise SourceError("Tabela de remuneração não encontrada.")

    sheets: list[dict[str, Any]] = []
    issues: list[str] = []
    target_period = f"{year:04d}-{month:02d}"
    for table_index, table in enumerate(candidates, start=1):
        caption = table["caption"]
        period_match = _PERIOD.search(caption)
        if not period_match:
            raise SourceError("Período da tabela não reconhecido.")
        source_month, source_year, label = period_match.groups()
        if int(source_year) != year or int(source_month) != month:
            raise SourceError("A Câmara retornou período diferente do solicitado.")
        identity, sheet_type, sheet_number = _sheet_identity(label)
        components: dict[str, int] = {}
        duplicate_components: set[str] = set()
        for row in table["rows"]:
            if len(row) < 2:
                continue
            normalized_label = re.sub(r"^[a-z]\s*-\s*", "", _key(row[0]))
            component_key = _COMPONENT_LABELS.get(normalized_label.strip(" :-"))
            if component_key is None:
                continue
            cents = parse_cents(row[-1])
            if cents is None:
                continue
            if component_key in components:
                duplicate_components.add(component_key)
                continue
            components[component_key] = cents
        missing = sorted(set(COMPONENTS) - set(components))
        if missing:
            issues.append(f"sheet-{table_index}-missing-components")
        if duplicate_components:
            issues.append(f"sheet-{table_index}-duplicate-components")
        if sheet_type == "unknown":
            issues.append(f"sheet-{table_index}-unknown-identity")
        sheets.append({
            "sheetIndex": table_index,
            "identity": identity,
            "sheetType": sheet_type,
            "sheetNumber": sheet_number,
            "period": target_period,
            "componentsCents": components,
            "missingComponents": missing,
        })

    status = "complete" if not issues else "partial"
    url = source_url or detail_url(profile_id, year, month)
    if not _official_detail_url(url, profile_id, year, month):
        raise SourceError("A resposta não corresponde ao perfil e período solicitados.")
    return {
        "profileId": profile_id,
        "period": target_period,
        "year": year,
        "month": month,
        "status": status,
        "detailStatus": status,
        "sourceUrl": url,
        "fetchedAt": fetched_at or utc_now(),
        "sourceSha256": sha256(raw).hexdigest(),
        "sheetCoverage": {
            "status": "observed",
            "scope": "all_tables_in_individual_detail_response",
        },
        "sheets": sheets,
        "issues": issues,
    }


class _ReportIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._text).split())))
            self._href = None


def parse_report_index(payload: bytes | str, year: int) -> dict[int, str]:
    """Find official CSV links by month from the Câmara annual index."""
    html = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
    parser = _ReportIndexParser()
    parser.feed(html)
    urls: dict[int, str] = {}
    for href, label in parser.links:
        if _key(label) != "csv":
            continue
        absolute = href if href.startswith("https://") else (
            f"https://{REPORT_HOST}{href}" if href.startswith("/") else ""
        )
        if _official_url(absolute) is None:
            continue
        parts = urlsplit(absolute)
        match = re.search(
            r"/(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)-de-(\d{4})",
            parts.path,
            re.IGNORECASE,
        )
        if not match or int(match.group(2)) != year:
            continue
        month = _MONTHS_PT[match.group(1).casefold()]
        urls[month] = absolute
    return urls


def _csv_component_headers(fieldnames: Iterable[str] | None) -> dict[str, str]:
    normalized = {_key(name): name for name in (fieldnames or []) if isinstance(name, str)}
    aliases = {
        "fixed_remuneration": ("remuneracao fixa",),
        "personal_advantages": ("vantagens de natureza pessoal",),
        "commission_role": ("funcao ou cargo em comissao",),
        "christmas_bonus": ("gratificacao natalina",),
        "vacation_third": ("ferias (1/3 constitucional)", "ferias 1/3 constitucional"),
        "other_eventual_remuneration": (
            "outras remuneracoes eventuais/provisorias",
            "outras remuneracoes eventuais/provisoria(*)",
            "outras remuneracoes eventuais/provisoria",
        ),
        "permanence_bonus": ("abono de permanencia", "abono permanencia"),
        "constitutional_reduction": ("redutor constitucional",),
        "pension_contribution": ("contribuicao previdenciaria", "constribuicao previdenciaria"),
        "income_tax": ("imposto de renda",),
        "after_mandatory_deductions": ("remuneracao apos descontos obrigatorios",),
        "daily_allowances": ("diarias",),
        "allowances": ("auxilios",),
        "indemnity_benefits": ("vantagens indenizatorias",),
    }
    found: dict[str, str] = {}
    for key, candidates in aliases.items():
        for candidate in candidates:
            if candidate in normalized:
                found[key] = normalized[candidate]
                break
    return found


def parse_consolidated_csv(
    payload: bytes,
    year: int,
    month: int,
    source_url: str,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Aggregate only the exact Parliamentary group; retain no row identifiers."""
    if not 1 <= month <= 12 or not _official_report_month_url(source_url, year, month):
        raise SourceError("CSV ou período oficial inválido.")
    text = payload.decode("iso-8859-1", "replace")
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    fieldnames = reader.fieldnames or []
    normalized_headers = {_key(name): name for name in fieldnames if isinstance(name, str)}
    group_column = normalized_headers.get("grupo funcional")
    sheet_column = normalized_headers.get("folha de pagamento")
    component_columns = _csv_component_headers(fieldnames)
    missing_headers = sorted(set(COMPONENTS) - set(component_columns))
    if not group_column or not sheet_column or not fieldnames:
        raise SourceError("Cabeçalho do CSV oficial não reconhecido.")

    aggregates: dict[str, dict[str, Any]] = {}
    unparseable_rows = 0
    for row in reader:
        if (row.get(group_column) or "").strip() != "Parlamentar":
            continue
        sheet_type = " ".join((row.get(sheet_column) or "").split())
        if not sheet_type:
            unparseable_rows += 1
            continue
        aggregate = aggregates.setdefault(sheet_type, {
            "sheetType": sheet_type,
            "rowCount": 0,
            "componentTotalsCents": {key: 0 for key in COMPONENTS},
            "componentsWithMissingValues": set(),
        })
        aggregate["rowCount"] += 1
        for component in COMPONENTS:
            column = component_columns.get(component)
            value = parse_cents(row.get(column)) if column else None
            if value is None:
                aggregate["componentsWithMissingValues"].add(component)
            else:
                aggregate["componentTotalsCents"][component] += value

    if not aggregates:
        raise SourceError("CSV oficial sem linhas do grupo Parlamentar.")
    sheet_rows: list[dict[str, Any]] = []
    for sheet_type, aggregate in sorted(aggregates.items()):
        missing = sorted(aggregate["componentsWithMissingValues"])
        totals = aggregate["componentTotalsCents"]
        for component in missing:
            totals[component] = None
        sheet_rows.append({
            "sheetType": sheet_type,
            "rowCount": aggregate["rowCount"],
            "componentTotalsCents": totals,
            "componentsWithMissingValues": missing,
        })
    has_normal = any(_key(row["sheetType"]) == "normal" for row in sheet_rows)
    has_missing_values = any(row["componentsWithMissingValues"] for row in sheet_rows)
    status = "complete" if (
        has_normal and not missing_headers and not unparseable_rows and not has_missing_values
    ) else "partial"
    return {
        "period": f"{year:04d}-{month:02d}",
        "year": year,
        "month": month,
        "status": status,
        "group": "Parlamentar",
        "sourceUrl": source_url,
        "fetchedAt": fetched_at or utc_now(),
        "sourceSha256": sha256(payload).hexdigest(),
        "rowCount": sum(row["rowCount"] for row in sheet_rows),
        "sheets": sheet_rows,
        "missingHeaders": missing_headers,
        "unparseableRows": unparseable_rows,
        "identityLinkage": "unavailable_from_consolidated_csv",
    }


def _pace_request() -> None:
    global _NEXT_REQUEST_AT
    with _REQUEST_LOCK:
        now = time.monotonic()
        delay = max(0.0, _NEXT_REQUEST_AT - now)
        if delay:
            time.sleep(delay)
        _NEXT_REQUEST_AT = time.monotonic() + MIN_REQUEST_INTERVAL


def _request_bytes(url: str) -> tuple[bytes, str, str]:
    if _official_url(url) is None:
        raise SourceError("URL fora dos domínios oficiais da Câmara.")
    last_error: Exception | None = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            _pace_request()
            request = Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,text/csv,text/plain,*/*",
            })
            with urlopen(request, timeout=HTTP_TIMEOUT) as response:
                payload = response.read()
                final_url = response.geturl()
            if not payload or _official_url(final_url) is None:
                raise SourceError("Resposta vazia ou redirecionada para URL não oficial.")
            return payload, final_url, utc_now()
        except (HTTPError, URLError, TimeoutError, OSError, SourceError) as error:
            last_error = error
            if attempt < HTTP_RETRIES:
                delay = 0.5 * (2 ** attempt)
                if isinstance(error, HTTPError) and error.code == 429:
                    retry_after = error.headers.get("Retry-After") if error.headers else None
                    if retry_after:
                        try:
                            delay = max(0.0, min(60.0, float(retry_after)))
                        except ValueError:
                            try:
                                retry_at = parsedate_to_datetime(retry_after)
                                if retry_at.tzinfo is None:
                                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                                delay = max(0.0, min(60.0, (retry_at - datetime.now(timezone.utc)).total_seconds()))
                            except (TypeError, ValueError, OverflowError):
                                pass
                time.sleep(delay)
    raise SourceError(
        f"Falha ao consultar fonte oficial ({type(last_error).__name__ if last_error else 'erro'})."
    ) from last_error


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(value, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _profile_cache_path(raw_root: Path, year: int, profile_id: str, month: int) -> Path:
    match = _PROFILE_ID.fullmatch(profile_id)
    if not match:
        raise ValueError("ID de perfil inválido")
    return raw_root / str(year) / match.group(1) / f"{month:02d}.json"


def _inventory_cache_path(raw_root: Path, year: int, month: int) -> Path:
    return raw_root / str(year) / "sheets" / f"{month:02d}.json"


def _index_cache_path(raw_root: Path, year: int) -> Path:
    return raw_root / str(year) / "report-index.json"


def _valid_profile_cache(value: Any, profile_id: str, year: int, month: int) -> bool:
    return (
        isinstance(value, dict)
        and value.get("profileId") == profile_id
        and value.get("period") == f"{year:04d}-{month:02d}"
        and value.get("sourceUrl")
        and _official_detail_url(value.get("sourceUrl"), profile_id, year, month)
        and value.get("detailStatus") in {"complete", "partial"}
        and isinstance(value.get("sheets"), list)
    )


def _valid_inventory_cache(value: Any, year: int, month: int) -> bool:
    return (
        isinstance(value, dict)
        and value.get("period") == f"{year:04d}-{month:02d}"
        and value.get("sourceUrl")
        and _official_report_month_url(value.get("sourceUrl"), year, month)
        and value.get("group") == "Parlamentar"
        and value.get("status") in {"complete", "partial"}
        and isinstance(value.get("sheets"), list)
    )


def _current_roster(payload: Any) -> list[str]:
    authorities = payload.get("authorities") if isinstance(payload, dict) else None
    if not isinstance(authorities, list):
        raise SourceError("Lista local de autoridades indisponível.")
    ids = {
        match.group(0)
        for row in authorities
        if isinstance(row, dict)
        and row.get("sourceId") == ROSTER_SOURCE_ID
        and isinstance(row.get("id"), str)
        and (match := _PROFILE_ID.fullmatch(row["id"]))
    }
    if not ids:
        raise SourceError("Lista local sem IDs atuais da Câmara.")
    return sorted(ids, key=lambda value: int(value.split(":", 1)[1]))


def _load_report_links(raw_root: Path, year: int, collect: bool, refresh: bool) -> tuple[dict[int, str], str | None]:
    cache_path = _index_cache_path(raw_root, year)
    cache = _read_json(cache_path)
    valid_cache = (
        isinstance(cache, dict)
        and cache.get("year") == year
        and isinstance(cache.get("urls"), dict)
        and all(
            str(month).isdigit()
            and 1 <= int(month) <= 12
            and _official_url(url) is not None
            for month, url in cache["urls"].items()
        )
    )
    if valid_cache and (not collect or not refresh):
        return {int(month): url for month, url in cache["urls"].items()}, cache.get("sourceUrl")
    if not collect:
        return ({int(month): url for month, url in cache["urls"].items()}, cache.get("sourceUrl")) if valid_cache else ({}, None)
    index_url = REPORT_INDEX_URL.format(year=year)
    try:
        payload, final_url, fetched_at = _request_bytes(index_url)
        urls = parse_report_index(payload, year)
        if not urls:
            raise SourceError("Índice anual sem links CSV reconhecidos.")
        _atomic_json(cache_path, {
            "year": year,
            "sourceUrl": final_url,
            "fetchedAt": fetched_at,
            "urls": {str(month): url for month, url in sorted(urls.items())},
        })
        return urls, final_url
    except Exception:
        if valid_cache:
            return {int(month): url for month, url in cache["urls"].items()}, cache.get("sourceUrl")
        return {}, None


def _load_sheet_inventory(
    raw_root: Path,
    year: int,
    month: int,
    url: str | None,
    collect: bool,
    refresh: bool,
) -> dict[str, Any] | None:
    cache_path = _inventory_cache_path(raw_root, year, month)
    cache = _read_json(cache_path)
    valid_cache = _valid_inventory_cache(cache, year, month)
    if valid_cache and (not collect or (not refresh and cache.get("status") == "complete")):
        return cache
    if not collect or not url:
        return cache if valid_cache else None
    try:
        payload, final_url, fetched_at = _request_bytes(url)
        inventory = parse_consolidated_csv(payload, year, month, final_url, fetched_at)
        if inventory.get("status") == "partial" and valid_cache and cache.get("status") == "complete":
            _atomic_json(cache_path.with_suffix(".attempt.json"), {
                "period": inventory["period"],
                "status": "partial",
                "attemptedAt": inventory["fetchedAt"],
                "sourceUrl": inventory["sourceUrl"],
                "sourceSha256": inventory["sourceSha256"],
                "missingHeaders": inventory.get("missingHeaders", []),
                "unparseableRows": inventory.get("unparseableRows", 0),
            })
            return cache
        _atomic_json(cache_path, inventory)
        return inventory
    except Exception as error:
        failed = {
            "period": f"{year:04d}-{month:02d}",
            "year": year,
            "month": month,
            "status": "unavailable",
            "group": "Parlamentar",
            "sourceUrl": url,
            "fetchedAt": utc_now(),
            "errorType": type(error).__name__,
            "sheets": [],
            "identityLinkage": "unavailable_from_consolidated_csv",
        }
        _atomic_json(cache_path.with_suffix(".attempt.json"), failed)
        return cache if valid_cache else failed


def _apply_inventory(observation: dict[str, Any], inventory: dict[str, Any] | None) -> dict[str, Any]:
    result = json.loads(json.dumps(observation))
    if result.get("detailStatus") == "unavailable":
        result["sheetCoverage"] = {
            "status": "unknown",
            "scope": "individual_detail_response",
            "reason": "individual_detail_response_unavailable",
        }
        return result
    if not isinstance(inventory, dict) or inventory.get("status") not in {"complete", "partial"}:
        result["status"] = "partial"
        result["sheetCoverage"] = {
            "status": "unknown",
            "scope": "individual_detail_response",
            "reason": "monthly_parliamentary_sheet_inventory_unavailable",
        }
        return result
    represented_types = {
        "normal" if sheet.get("sheetType") == "normal" else
        (f"complementar - {sheet.get('sheetNumber')}" if sheet.get("sheetType") == "complementary" else "")
        for sheet in result.get("sheets", []) if isinstance(sheet, dict)
    }
    represented_types.update(
        "adiantamento de gratificacao natalina"
        for sheet in result.get("sheets", [])
        if isinstance(sheet, dict) and sheet.get("sheetType") == "advance_christmas_bonus"
    )
    represented_types = {value for value in represented_types if value}
    expected_types = {
        _key(sheet.get("sheetType"))
        for sheet in inventory.get("sheets", [])
        if isinstance(sheet, dict) and isinstance(sheet.get("sheetType"), str) and sheet.get("rowCount", 0) > 0
    }
    observed_types = {_key(value) for value in represented_types}
    missing_types = sorted(expected_types - observed_types)
    has_unlinked_supplement = any(
        "complement" in _key(sheet.get("sheetType")) and sheet.get("rowCount", 0) > 0
        for sheet in inventory.get("sheets", [])
        if isinstance(sheet, dict)
    )
    parse_complete = result.get("detailStatus") == "complete"
    inventory_complete = inventory.get("status") == "complete"
    coverage_complete = parse_complete and inventory_complete and not missing_types
    reason = None
    if has_unlinked_supplement:
        coverage_complete = False
        reason = "supplementary_rows_are_not_linked_to_public_deputy_ids"
    elif missing_types:
        reason = "sheet_types_in_monthly_inventory_not_present_in_detail_response"
    elif not parse_complete:
        reason = "individual_detail_components_or_sheet_identity_incomplete"
    elif not inventory_complete:
        reason = "monthly_parliamentary_sheet_inventory_partial"
    result["sheetCoverage"] = {
        "status": "complete" if coverage_complete else "partial",
        "scope": "individual_detail_plus_monthly_parliamentary_inventory",
        "inventoryPeriod": inventory.get("period"),
        "missingSheetTypes": missing_types,
        "reason": reason,
    }
    result["sheetInventory"] = {
        "status": inventory.get("status"),
        "sourceUrl": inventory.get("sourceUrl"),
        "sourceSha256": inventory.get("sourceSha256"),
    }
    if not coverage_complete:
        result["status"] = "partial"
    else:
        result["status"] = "complete"
    return result


def _collect_profile_month(
    profile_id: str,
    year: int,
    month: int,
    raw_root: Path,
) -> dict[str, Any]:
    url = detail_url(profile_id, year, month)
    cache_path = _profile_cache_path(raw_root, year, profile_id, month)
    attempt_path = cache_path.with_suffix(".attempt.json")
    try:
        payload, final_url, fetched_at = _request_bytes(url)
        observation = parse_payroll_html(payload, profile_id, year, month, final_url, fetched_at)
    except Exception as error:
        observation = {
            "profileId": profile_id,
            "period": f"{year:04d}-{month:02d}",
            "year": year,
            "month": month,
            "status": "unavailable",
            "detailStatus": "unavailable",
            "sourceUrl": url,
            "fetchedAt": utc_now(),
            "errorType": type(error).__name__,
            "sheetCoverage": {"status": "unknown", "scope": "individual_detail_response"},
            "sheets": [],
            "issues": [],
        }
        _atomic_json(attempt_path, observation)
        return observation
    previous = _read_profile_cache(raw_root, profile_id, year, month)
    if observation.get("detailStatus") == "partial" and previous and previous.get("detailStatus") == "complete":
        _atomic_json(attempt_path, {
            "profileId": profile_id,
            "period": observation["period"],
            "status": "partial",
            "attemptedAt": observation["fetchedAt"],
            "sourceUrl": observation["sourceUrl"],
            "sourceSha256": observation["sourceSha256"],
            "issues": observation.get("issues", []),
        })
        return observation
    _atomic_json(cache_path, observation)
    if attempt_path.exists():
        attempt_path.unlink()
    return observation


def _read_profile_cache(raw_root: Path, profile_id: str, year: int, month: int) -> dict[str, Any] | None:
    value = _read_json(_profile_cache_path(raw_root, year, profile_id, month))
    return value if _valid_profile_cache(value, profile_id, year, month) else None


def _load_previous_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"profiles": {}, "sheetInventory": {"months": {}}}
    value = _read_json(path)
    if not isinstance(value, dict) or not isinstance(value.get("profiles"), dict):
        raise SourceError("Snapshot anterior inválido; ele foi preservado sem alteração.")
    if not isinstance(value.get("sheetInventory"), dict):
        value["sheetInventory"] = {"months": {}}
    if not isinstance(value["sheetInventory"].get("months"), dict):
        value["sheetInventory"]["months"] = {}
    return value


def build_snapshot(
    root: Path = ROOT,
    year: int = 2026,
    months: Iterable[int] | None = None,
    collect: bool = False,
    refresh: bool = False,
    limit: int | None = None,
    profile_ids: Iterable[str] | None = None,
    output: Path | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    if refresh and not collect:
        raise ValueError("--refresh requer --collect")
    if year < 2000:
        raise ValueError("Ano inválido")
    selected_months = sorted(set(months if months is not None else parse_months(None, year)))
    if not selected_months or any(not 1 <= month <= 12 for month in selected_months):
        raise ValueError("Meses inválidos")
    import_path = root / "data" / "imports" / "legislative.json"
    raw_root = root / "data" / "raw" / "mandate-cost" / "payroll" / "camara"
    destination = output or (root / "data" / "snapshots" / "chamber-payroll.json")
    previous = _load_previous_snapshot(destination)
    roster_payload = _read_json(import_path)
    roster = _current_roster(roster_payload)
    if profile_ids is not None:
        wanted = set(profile_ids)
        invalid = wanted - set(roster)
        if invalid:
            raise ValueError("IDs solicitados não pertencem ao roster atual da Câmara")
        roster = [profile_id for profile_id in roster if profile_id in wanted]
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit deve ser positivo")
        roster = roster[:limit]

    links, index_source_url = _load_report_links(raw_root, year, collect, refresh)
    inventory_by_month: dict[int, dict[str, Any] | None] = {}
    for month in selected_months:
        inventory_by_month[month] = _load_sheet_inventory(
            raw_root, year, month, links.get(month), collect, refresh
        )

    result_profiles = previous["profiles"]
    stats = {"complete": 0, "partial": 0, "unavailable": 0, "missing": 0}
    todo: list[tuple[str, int]] = []
    for profile_id in roster:
        profile = result_profiles.setdefault(profile_id, {"months": {}})
        if not isinstance(profile, dict):
            profile = result_profiles[profile_id] = {"months": {}}
        profile.setdefault("months", {})
        if not isinstance(profile["months"], dict):
            profile["months"] = {}
        for month in selected_months:
            cached = _read_profile_cache(raw_root, profile_id, year, month)
            previous_observation = profile["months"].get(f"{year:04d}-{month:02d}")
            if cached and (not collect or (not refresh and cached.get("detailStatus") == "complete")):
                observation = cached
                inventory = inventory_by_month[month]
                profile["months"][observation["period"]] = _apply_inventory(observation, inventory)
            elif collect:
                todo.append((profile_id, month))
            elif cached:
                profile["months"][cached["period"]] = _apply_inventory(cached, inventory_by_month[month])
            elif isinstance(previous_observation, dict):
                # An absent cache never deletes or replaces an older observation.
                pass
            else:
                stats["missing"] += 1

    if collect and todo:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_key = {
                executor.submit(_collect_profile_month, profile_id, year, month, raw_root): (profile_id, month)
                for profile_id, month in todo
            }
            for future in as_completed(future_to_key):
                profile_id, month = future_to_key[future]
                observation = future.result()
                profile = result_profiles.setdefault(profile_id, {"months": {}})
                profile.setdefault("months", {})
                period = f"{year:04d}-{month:02d}"
                updated = _apply_inventory(observation, inventory_by_month[month])
                prior = profile["months"].get(period)
                if observation.get("detailStatus") == "complete":
                    profile["months"][period] = updated
                else:
                    cached = _read_profile_cache(raw_root, profile_id, year, month)
                    if cached:
                        fallback = _apply_inventory(cached, inventory_by_month[month])
                        if (
                            observation.get("detailStatus") == "partial"
                            and cached.get("detailStatus") == "complete"
                        ):
                            preserved = (
                                dict(prior)
                                if isinstance(prior, dict) and prior.get("detailStatus") == "complete"
                                else dict(fallback)
                            )
                            preserved["lastAttempt"] = {
                                "status": "partial",
                                "attemptedAt": observation.get("fetchedAt"),
                                "sourceSha256": observation.get("sourceSha256"),
                                "issues": observation.get("issues", []),
                            }
                            profile["months"][period] = preserved
                        elif not isinstance(prior, dict) or prior.get("detailStatus") not in {"complete", "partial"}:
                            profile["months"][period] = fallback
                        else:
                            prior = dict(prior)
                            prior["lastAttempt"] = {
                                "status": observation.get("detailStatus", "unavailable"),
                                "attemptedAt": observation.get("fetchedAt"),
                                "errorType": observation.get("errorType"),
                                "issues": observation.get("issues", []),
                            }
                            profile["months"][period] = prior
                    elif isinstance(prior, dict):
                        prior = dict(prior)
                        prior["lastAttempt"] = {
                            "status": "unavailable",
                            "attemptedAt": observation.get("fetchedAt"),
                            "errorType": observation.get("errorType"),
                        }
                        profile["months"][period] = prior
                    else:
                        profile["months"][period] = updated

    # Refresh a prior observation's coverage if new aggregate inventory arrived.
    for profile_id in roster:
        profile = result_profiles.get(profile_id, {})
        month_map = profile.get("months", {}) if isinstance(profile, dict) else {}
        for month in selected_months:
            period = f"{year:04d}-{month:02d}"
            observation = month_map.get(period)
            if isinstance(observation, dict) and observation.get("detailStatus") in {"complete", "partial"}:
                # The normalized cache is the stable successful response; use it to recompute coverage.
                cached = _read_profile_cache(raw_root, profile_id, year, month)
                if cached:
                    updated = _apply_inventory(cached, inventory_by_month[month])
                    if observation.get("detailStatus") == "complete":
                        month_map[period] = updated

    sheet_months = previous["sheetInventory"].setdefault("months", {})
    for month, inventory in inventory_by_month.items():
        if isinstance(inventory, dict):
            sheet_months[f"{year:04d}-{month:02d}"] = inventory
    request_counts = {"complete": 0, "partial": 0, "unavailable": 0, "missing": 0}
    for profile_id in roster:
        profile = result_profiles.get(profile_id, {})
        month_map = profile.get("months", {}) if isinstance(profile, dict) else {}
        for month in selected_months:
            observation = month_map.get(f"{year:04d}-{month:02d}")
            if not isinstance(observation, dict):
                request_counts["missing"] += 1
            elif observation.get("status") in request_counts:
                request_counts[observation["status"]] += 1
            else:
                request_counts["partial"] += 1
    snapshot = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "source": {
            "id": "camara_deputy_payroll",
            "name": SOURCE_NAME,
            "rosterSourceId": ROSTER_SOURCE_ID,
            "detailScope": "individual_public_deputy_payroll_pages",
            "sheetInventorySourceUrl": index_source_url,
        },
        "year": year,
        "requestedMonths": selected_months,
        "requestedProfiles": roster,
        "coverage": request_counts,
        "sheetInventory": {
            "sourceUrl": index_source_url,
            "group": "Parlamentar",
            "identityLinkage": "unavailable_from_consolidated_csv",
            "months": sheet_months,
        },
        "profiles": result_profiles,
    }
    _atomic_json(destination, snapshot)
    return snapshot, request_counts


def _parse_profile_ids(value: str | None) -> list[str] | None:
    if value is None:
        return None
    ids: list[str] = []
    for token in re.split(r"[,;]", value):
        normalized = token.strip()
        if normalized.isdigit():
            normalized = f"camara:{normalized}"
        if not _PROFILE_ID.fullmatch(normalized):
            raise ValueError(f"ID de perfil inválido: {token.strip()}")
        ids.append(normalized)
    if not ids:
        raise ValueError("Informe ao menos um ID")
    if len(set(ids)) != len(ids):
        raise ValueError("IDs repetidos")
    return ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true", help="consulta as fontes oficiais; sem isso, usa somente caches locais")
    parser.add_argument("--refresh", action="store_true", help="força nova consulta; exige --collect")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--months", help="meses como 1-9, 1..9 ou 1,2,3; por padrão, meses completos disponíveis")
    parser.add_argument("--limit", type=int, help="limita o número de perfis (amostra)")
    parser.add_argument("--ids", help="IDs públicos da Câmara separados por vírgula; aceita 220661 ou camara:220661")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error("--refresh requer --collect")
    try:
        months = parse_months(args.months, args.year)
        profile_ids = _parse_profile_ids(args.ids)
        snapshot, stats = build_snapshot(
            year=args.year,
            months=months,
            collect=args.collect,
            refresh=args.refresh,
            limit=args.limit,
            profile_ids=profile_ids,
            output=args.output,
        )
    except (ValueError, SourceError) as error:
        parser.error(str(error))
        return 2
    print(json.dumps({"coverage": stats, "requestedMonths": snapshot["requestedMonths"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
