#!/usr/bin/env python3
"""Collect explicit Senate presence marks from the Senate Diaries of the current mandate (Feb/2023 on).

The default run is offline. ``--collect`` fetches the monthly Senate Diary
calendar and plenary agenda, then downloads only the table-of-contents and
attendance pages needed from each available diary. This collector records
positive marks in the PDF's ``Presença`` column only; it never turns an absent
row, a missing vote mark, or an uncollected session into an absence.

The optional PDF dependency is pdfplumber. It is needed only for collection
and is listed in ``ingest/senate-requirements.txt``; the app and its tests do
not need it.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unicodedata
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
IMPORT_PATH = ROOT / "data" / "imports" / "legislative.json"
RAW_DIR = ROOT / "data" / "raw" / "senado-presenca"
DEFAULT_OUTPUT = ROOT / "data" / "snapshots" / "senado-presenca.json"
YEAR = 2026
# Mandato atual: a coleta padrão vai de fev/2023 até hoje; --year coleta um ano só.
MANDATE_START = date(2023, 2, 1)
# Nomes como aparecem nas listas do Diário, diferentes do cadastro, conferidos em 9/10/2026.
DIARY_NAME_ALIASES = {
    "Mauro Carvalho Jr.": "senado:6362",  # cadastro: MAURO CARVALHO JUNIOR
    "Veneziano Vital Rêgo": "senado:5748",  # cadastro: Veneziano Vital do Rêgo
}
SOURCE_ID = "senado_senators_current"
SENATOR_ID = re.compile(r"^senado:(\d+)$")
SENATE_DIARIES = "https://legis.senado.leg.br/diarios"
OPEN_DATA = "https://legis.senado.leg.br/dadosabertos"
TUTORIAL_URL = (
    "https://www12.senado.leg.br/assessoria-de-imprensa/guia-para-jornalistas/"
    "tutorial-de-verificacao-da-assiduidade-dos-senadores"
)
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
HTTP_TIMEOUT = 90
HTTP_RETRIES = 1
MAX_PDF_RANGE_PAGES = 20
ATTENDANCE_PAGE_LOOKAHEAD = 5
DIARY_PARSER_VERSION = 2


class SourceError(RuntimeError):
    """Raised when the official source cannot provide a usable observation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: Any, limit: int = 2000) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized[:limit] or None


def _official_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^https://([^/]+)(?:/|$)", value, re.I)
    if not match:
        return None
    host = match.group(1).split(":", 1)[0].lower()
    if host == "senado.leg.br" or host.endswith(".senado.leg.br"):
        return value
    return None


def _period_dates(year: int | None, today: date | None = None) -> tuple[date, date]:
    """Sem ano: o mandato (fev/2023 até hoje). Com ano: esse ano, a partir de fev/2023."""
    today = today or date.today()
    if year is None:
        return MANDATE_START, today
    if year < MANDATE_START.year:
        raise ValueError(f"O mandato atual começa em {MANDATE_START.isoformat()}.")
    if today.year < year:
        raise ValueError("Não é possível confirmar cobertura de um ano futuro.")
    return max(date(year, 1, 1), MANDATE_START), min(today, date(year, 12, 31))


def _months(period_start: date, period_end: date) -> list[tuple[int, int]]:
    months, year, month = [], period_start.year, period_start.month
    while (year, month) <= (period_end.year, period_end.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def agenda_url(year: int, month: int) -> str:
    return f"{OPEN_DATA}/plenario/agenda/mes/{year}{month:02d}01"


def calendar_url(year: int, month: int) -> str:
    query = urlencode({"mes": month, "ano": year, "veiculo": 1, "tipo": 1})
    return f"{SENATE_DIARIES}/resources/calendario-html?{query}"


def diary_url(diary_code: str | int) -> str:
    code = str(diary_code)
    if not code.isdigit():
        raise ValueError("Código de diário inválido")
    return f"{SENATE_DIARIES}/ver/{code}"


def diary_pdf_url(diary_code: str | int, first_page: int, last_page: int) -> str:
    code = str(diary_code)
    if not code.isdigit() or first_page < 1 or last_page < first_page:
        raise ValueError("Intervalo de páginas ou código de diário inválido")
    if last_page - first_page + 1 > MAX_PDF_RANGE_PAGES:
        raise ValueError("A fonte limita downloads a 20 páginas por requisição")
    query = urlencode({
        "codDiario": code,
        "paginaInicial": first_page,
        "paginaFinal": last_page,
    })
    return f"{SENATE_DIARIES}/BuscaPaginasDiario?{query}"


def _request_bytes(url: str) -> tuple[bytes, str]:
    if not _official_url(url):
        raise SourceError("URL fora dos domínios oficiais do Senado.")
    last_error: Exception | None = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/pdf, application/xml, text/html, */*",
                },
            )
            with urlopen(request, timeout=HTTP_TIMEOUT) as response:
                payload = response.read()
                content_type = (response.headers.get("Content-Type") or "").lower()
            if not payload:
                raise SourceError("A resposta oficial veio vazia.")
            if "pdf" in url.lower() and "application/pdf" not in content_type and not payload.startswith(b"%PDF"):
                raise SourceError("A resposta do diário não veio como PDF.")
            return payload, utc_now()
        except (HTTPError, URLError, TimeoutError, OSError, SourceError) as error:
            last_error = error
            if attempt < HTTP_RETRIES:
                time.sleep(0.5 * (attempt + 1))
    raise SourceError(
        f"Falha ao consultar fonte oficial ({type(last_error).__name__ if last_error else 'erro'})."
    ) from last_error


class _CalendarParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._anchor: dict[str, Any] | None = None
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href") or ""
        match = re.fullmatch(r"/diarios/ver/(\d+)", href)
        if match:
            self._anchor = {"code": match.group(1), "text": []}

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._anchor is None:
            return
        label = "".join(self._anchor["text"]).strip()
        if label.isdigit():
            self.links.append((self._anchor["code"], label))
        self._anchor = None


def parse_calendar_html(payload: str, year: int, month: int) -> list[dict[str, str]]:
    """Read date-to-caderno links from the official session-date calendar."""
    if not isinstance(payload, str) or "calendario" not in payload.casefold():
        raise SourceError("Calendário oficial sem marcação esperada.")
    parser = _CalendarParser()
    parser.feed(payload)
    entries = []
    seen: set[tuple[str, str]] = set()
    for code, day_text in parser.links:
        try:
            session_date = date(year, month, int(day_text)).isoformat()
        except ValueError:
            continue
        key = (code, session_date)
        if key in seen:
            continue
        seen.add(key)
        entries.append({"diarioId": code, "date": session_date})
    return sorted(entries, key=lambda row: (row["date"], int(row["diarioId"])))


def _xml_text(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path)
    return (found.text or "").strip() if found is not None else ""


def parse_agenda_xml(
    payload: str,
    year: int,
    month: int,
    period_end: date,
) -> tuple[list[dict[str, str]], int]:
    """Return realized deliberative Senate events and malformed event count."""
    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, TypeError) as error:
        raise SourceError("Agenda do plenário sem XML válido.") from error

    rows: list[dict[str, str]] = []
    malformed = 0
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "Sessao":
            continue
        house = _xml_text(node, "Casa").upper()
        session_type = _xml_text(node, "TipoSessao")
        if house != "SF":
            continue
        normalized_type = " ".join(session_type.split()).upper()
        if not normalized_type:
            malformed += 1
            continue
        if not normalized_type.startswith("SESSÃO DELIBERATIVA"):
            continue
        if "NÃO DELIBERATIVA" in normalized_type:
            continue

        session_date = _xml_text(node, "Data")[:10]
        code = _xml_text(node, "CodigoSessao")
        status = _xml_text(node, "Realizada/Status").casefold()
        try:
            parsed_date = date.fromisoformat(session_date)
        except ValueError:
            malformed += 1
            continue
        if parsed_date.year != year or parsed_date.month != month or parsed_date > period_end:
            continue
        # The agenda includes scheduled and canceled sittings, so only an
        # affirmative Realizada.Status is evidence that the sitting occurred.
        if status != "sim":
            if not status:
                malformed += 1
            continue
        if not code.isdigit():
            malformed += 1
            continue
        rows.append({
            "id": f"senado:{code}",
            "codigoSessao": code,
            "date": session_date,
            "type": normalized_type,
            "status": _xml_text(node, "SituacaoSessao"),
            "sourceUrl": f"{OPEN_DATA}/plenario/encontro/{code}",
        })

    unique: dict[str, dict[str, str]] = {}
    for row in rows:
        unique[row["id"]] = row
    return sorted(unique.values(), key=lambda row: (row["date"], row["id"])), malformed


def parse_diary_metadata(html: str) -> dict[str, Any]:
    if not isinstance(html, str):
        raise SourceError("Página do Diário sem HTML.")
    match = re.search(r"\bvar\s+diario\s*=\s*(\{.*?\});", html, re.S)
    if not match:
        raise SourceError("Metadados do Diário não encontrados na página oficial.")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise SourceError("Metadados do Diário sem JSON válido.") from error
    if not isinstance(value, dict) or not isinstance(value.get("caderno"), dict):
        raise SourceError("Metadados do Diário incompletos.")
    caderno = value["caderno"]
    code = str(caderno.get("codigo") or "")
    session_date = _text(caderno.get("dataSessao"), 30)
    first = caderno.get("paginaSumarioInicio")
    last = caderno.get("paginaSumarioFim")
    final_page = caderno.get("paginaFinal")
    if not code.isdigit() or not session_date:
        raise SourceError("Metadados do Diário sem código ou data de sessão.")
    if not isinstance(first, int) or not isinstance(last, int) or last < first:
        raise SourceError("Metadados do Diário sem intervalo de sumário.")
    if last - first + 1 > MAX_PDF_RANGE_PAGES:
        raise SourceError("Sumário excede o limite de 20 páginas da fonte.")
    if not isinstance(final_page, int) or final_page < 1:
        raise SourceError("Metadados do Diário sem página final.")
    if value.get("veiculoDSF") is not True or value.get("veiculoDCN") is True:
        raise SourceError("O caderno consultado não é do Diário do Senado Federal.")
    return {
        "diarioId": code,
        "date": session_date[:10],
        "sumarioStart": first,
        "sumarioEnd": last,
        "finalPage": final_page,
        "sourceUrl": diary_url(code),
        "extraordinaria": bool(caderno.get("extraordinaria")),
        "title": _text(value.get("tituloLongo"), 500),
    }


def _load_pdf_pages(payload: bytes) -> list[dict[str, Any]]:
    try:
        from io import BytesIO
        import pdfplumber
    except ImportError as error:
        raise SourceError(
            "pdfplumber é necessário somente para --collect; instale ingest/senate-requirements.txt."
        ) from error
    try:
        pages: list[dict[str, Any]] = []
        with pdfplumber.open(BytesIO(payload)) as pdf:
            for page in pdf.pages:
                words = page.extract_words(x_tolerance=2, y_tolerance=3)
                presence_headers = [
                    word for word in words
                    if str(word.get("text", "")).casefold() == "presença"
                ]
                vote_headers = [
                    word for word in words
                    if str(word.get("text", "")).casefold() == "voto"
                ]
                marks = 0
                if presence_headers:
                    presence_center = (
                        float(presence_headers[0]["x0"])
                        + float(presence_headers[0]["x1"])
                    ) / 2
                    if vote_headers:
                        vote_center = (
                            float(vote_headers[0]["x0"])
                            + float(vote_headers[0]["x1"])
                        ) / 2
                        lower = presence_center - 18
                        upper = (presence_center + vote_center) / 2
                    else:
                        # In the comparecimento-only table, Presença is the
                        # last column. Its header center is the anchor; a
                        # fixed page-coordinate band would silently miss a
                        # future layout shift.
                        lower = presence_center - 18
                        upper = float(page.width) - 8
                    marks = sum(
                        word.get("text") == "X"
                        and lower <= float(word.get("x0", -1)) < upper
                        for word in words
                    )
                text = page.extract_text() or ""
                timestamp_marks = sum(
                    TIMESTAMP_ROW_RE.fullmatch(" ".join(line.split())) is not None
                    for line in text.splitlines()
                )
                pages.append({
                    "text": text,
                    "presenceMarks": marks,
                    "timestampMarks": timestamp_marks,
                })
        return pages
    except SourceError:
        raise
    except Exception as error:
        raise SourceError(f"Falha ao ler PDF do Diário ({type(error).__name__}).") from error


def _require_pdf_parser() -> None:
    """Fail before network access when the optional manual collector is not installed."""
    try:
        import pdfplumber  # noqa: F401
    except ImportError as error:
        raise SourceError(
            "pdfplumber é necessário somente para --collect; instale ingest/senate-requirements.txt."
        ) from error


def attendance_page_numbers(summary_pages: list[dict[str, Any]]) -> list[int]:
    section_heading = re.compile(
        r"^\s*\d+\.\d+\s*[–—-]\s*REGISTRO DE COMPARECIMENTO(?:\s+E\s+VOTO)?\b",
        re.I,
    )
    pages: list[int] = []
    for page in summary_pages:
        text = page.get("text") if isinstance(page, dict) else ""
        if not isinstance(text, str):
            continue
        for line in text.splitlines():
            if not section_heading.search(line):
                continue
            numbers = re.findall(r"\d+", line)
            if numbers:
                number = int(numbers[-1])
                if number > 0:
                    pages.append(number)
    return sorted(set(pages))


ROW_RE = re.compile(
    r"^(?P<party>.*?)\s+(?P<uf>[A-Z]{2})\s+(?P<name>.+?)\s+(?P<marks>X(?:\s*X)?)$",
    re.I,
)
BRAZILIAN_UFS = (
    "AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO"
)
TIMESTAMP_ROW_RE = re.compile(
    rf"^(?P<party>.*?)\s+(?P<uf>{BRAZILIAN_UFS})\s+(?P<name>.+?)\s+"
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<time>\d{2}:\d{2}:\d{2})(?:\s+X)?$",
    re.I,
)
FOOTER_RE = re.compile(r"\bCompareceram\s+(\d+)\s+senador(?:es)?\b", re.I)
ATTENDANCE_HEADING_RE = re.compile(r"\bRegistro de Comparecimento(?:\s+e\s+Voto)?\b", re.I)
SESSION_RE = re.compile(
    r"(?P<number>\d+\s*[ªº“”\"'])\s+Sess[aã]o\s+Deliberativa\s+"
    r"(?P<kind>Ordin[aá]ria|Extraordin[aá]ria)",
    re.I,
)
NON_DELIBERATIVE_RE = re.compile(r"\bSess[aã]o\s+N[aã]o\s+Deliberativa\b", re.I)


def _session_kind(text: str) -> str | None:
    match = SESSION_RE.search(text)
    if not match:
        return None
    return f"SESSÃO DELIBERATIVA {match.group('kind').upper()}"


def _session_identity(text: str) -> tuple[str, int] | None:
    match = SESSION_RE.search(text)
    if not match:
        return None
    ordinal = re.search(r"\d+", match.group("number"))
    if ordinal is None:
        return None
    return _session_kind(text) or "", int(ordinal.group())


def parse_attendance_pages(
    pages: list[dict[str, Any]],
    session_date: str,
) -> list[dict[str, Any]]:
    """Parse validated positive Presença marks from one or more table pages.

    Each page is ``{"text": ..., "presenceMarks": N}``, where marks came
    from the PDF text coordinates, not from the row's ``X``/``XX`` string.
    The table is accepted only when its explicit total matches all parsed
    rows and all rows have a separate mark in the Presença column.
    """
    try:
        target_date = date.fromisoformat(session_date)
    except ValueError as error:
        raise SourceError("Data de sessão inválida para validar o diário.") from error
    brazilian_date_text = target_date.strftime("%d/%m/%Y")

    rows: list[dict[str, Any]] = []
    footer_total: int | None = None
    presence_mark_total = 0
    table_seen = False
    table_started = False
    session_kind: str | None = None
    non_deliberative_seen = False
    session_ordinal: int | None = None
    period_date_seen = False
    malformed_lines: list[str] = []
    table_method: str | None = None

    for page in pages:
        text = page.get("text") if isinstance(page, dict) else None
        presence_marks = page.get("presenceMarks") if isinstance(page, dict) else None
        if not isinstance(text, str) or not isinstance(presence_marks, int) or presence_marks < 0:
            raise SourceError("Página de presença sem texto ou marcadores verificáveis.")
        if footer_total is not None:
            break

        has_table_columns = (
            "Partido UF Nome Senador" in text
            and (
                re.search(r"\bPresença\b", text, re.I) is not None
                or (
                    re.search(r"\bHorário\b", text, re.I) is not None
                    and re.search(r"\bVoto\b", text, re.I) is not None
                )
            )
        )
        if ATTENDANCE_HEADING_RE.search(text) or has_table_columns:
            table_seen = True
            detected_method = (
                "attendance_timestamp"
                if re.search(r"Partido UF Nome Senador.*\bHorário\b", text, re.I)
                and re.search(r"Partido UF Nome Senador.*\bPresença\b", text, re.I) is None
                else "presence_column_x"
            )
            if table_method and table_method != detected_method:
                raise SourceError("O intervalo de páginas mistura métodos de registro de presença.")
            table_method = detected_method
            detected_kind = _session_kind(text)
            if detected_kind:
                if session_kind and session_kind != detected_kind:
                    raise SourceError("O intervalo de páginas mistura tipos de sessão.")
                session_kind = detected_kind
                identity = _session_identity(text)
                if identity:
                    if session_ordinal is not None and session_ordinal != identity[1]:
                        raise SourceError("O intervalo de páginas mistura números de sessão.")
                    session_ordinal = identity[1]
            if NON_DELIBERATIVE_RE.search(text):
                non_deliberative_seen = True
            if brazilian_date_text in text:
                period_date_seen = True

        page_rows = 0
        timestamp_row_count = page.get("timestampMarks", 0)
        if not isinstance(timestamp_row_count, int) or timestamp_row_count < 0:
            raise SourceError("Página sem contagem verificável dos horários de comparecimento.")
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            if "Partido UF Nome Senador" in line:
                table_started = True
                continue
            footer = FOOTER_RE.search(line)
            if footer:
                footer_total = int(footer.group(1))
                break
            if not table_started:
                continue
            if (
                not line
                or "registrodecomparecimento" in re.sub(r"\s+", "", line).casefold()
                or "Emissão" in line
                or "DIÁRIO DO SENADO FEDERAL" in line
                or "ARQUIVO ASSINADO DIGITALMENTE" in line
                or "CONSULTE EM http" in line
            ):
                continue
            timestamp_row = TIMESTAMP_ROW_RE.fullmatch(line) if table_method == "attendance_timestamp" else None
            if timestamp_row:
                timestamp_text = f"{timestamp_row.group('date')} {timestamp_row.group('time')}"
                try:
                    recorded_at = datetime.strptime(timestamp_text, "%d/%m/%Y %H:%M:%S")
                except ValueError:
                    malformed_lines.append(line[:120])
                    continue
                if recorded_at.date() != target_date:
                    malformed_lines.append(line[:120])
                    continue
                rows.append({
                    "partido": _text(timestamp_row.group("party"), 100),
                    "uf": timestamp_row.group("uf").upper(),
                    "nome": _text(timestamp_row.group("name"), 200),
                })
                page_rows += 1
                continue

            row = ROW_RE.fullmatch(line) if table_method != "attendance_timestamp" else None
            if row:
                rows.append({
                    "partido": _text(row.group("party"), 100),
                    "uf": row.group("uf").upper(),
                    "nome": _text(row.group("name"), 200),
                })
                page_rows += 1
                continue
            if (
                ATTENDANCE_HEADING_RE.search(line)
                or "Sessão Deliberativa" in line
                or NON_DELIBERATIVE_RE.search(line)
                or "Presenças no período:" in line
                or "Votos no período:" in line
                or line in ("Partido UF Nome Senador", "Voto", "Presença")
                or re.fullmatch(r"\d+[ªº]?", line)
                or "Legislatura" in line
            ):
                continue
            # The table is not silently accepted if an apparent record or
            # extraction artifact appears between its header and explicit end.
            if "senador" in line.casefold() or re.search(r"\b[A-Z]{2}\b", line):
                malformed_lines.append(line[:120])

        if table_started:
            expected_rows = (
                timestamp_row_count
                if table_method == "attendance_timestamp"
                else presence_marks
            )
            if page_rows != expected_rows:
                evidence_label = (
                    "horários registrados"
                    if table_method == "attendance_timestamp"
                    else "X na coluna Presença"
                )
                raise SourceError(
                    f"A quantidade de linhas não coincide com os {evidence_label}."
                )
            presence_mark_total += expected_rows

    if not table_seen or not table_started:
        raise SourceError("O sumário indicou a tabela, mas ela não foi localizada no PDF.")
    if not period_date_seen:
        raise SourceError("A data da sessão não foi confirmada no período da tabela.")
    if footer_total is None:
        raise SourceError("A tabela não chegou ao total explícito de comparecimentos.")
    if malformed_lines:
        detail = "; ".join(malformed_lines[:3])
        raise SourceError(
            "A extração encontrou linhas não reconhecidas dentro da tabela"
            + (f": {detail}" if detail else ".")
        )
    if footer_total != len(rows) or presence_mark_total != len(rows):
        raise SourceError("Total do Diário, linhas e evidências explícitas não coincidem.")
    if non_deliberative_seen and not session_kind:
        return []
    if not session_kind or session_ordinal is None:
        raise SourceError("O tipo e o número da sessão deliberativa não foram confirmados na tabela.")
    for row in rows:
        row["presente"] = True
    return [{
        "type": session_kind,
        "ordinal": session_ordinal,
        "method": table_method or "presence_column_x",
        "total": footer_total,
        "rows": rows,
    }]


def _normalize_name(value: Any) -> str:
    value = _text(value, 240) or ""
    folded = unicodedata.normalize("NFKD", value)
    ascii_name = "".join(char for char in folded if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", ascii_name).strip().casefold()
    normalized = re.sub(r"^(?:astronauta|astr|professora|prof|dra|dr)\s+", "", normalized)
    return " ".join(normalized.split())


def build_roster_index(payload: Any) -> tuple[dict[str, dict[str, Any]], set[str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("authorities"), list):
        raise ValueError("Importação legislativa sem lista de autoridades")
    candidates: dict[str, list[dict[str, Any]]] = {}
    for row in payload["authorities"]:
        if (
            not isinstance(row, dict)
            or row.get("sourceId") != SOURCE_ID
            or row.get("role") != "senador"
        ):
            continue
        identifier = str(row.get("id") or "")
        if not SENATOR_ID.fullmatch(identifier):
            continue
        key = _normalize_name(row.get("name"))
        if not key:
            continue
        candidates.setdefault(key, []).append({
            "id": identifier,
            "nome": _text(row.get("name"), 200),
            "partido": _text(row.get("party"), 100),
            "uf": _text(row.get("uf"), 2),
        })
    unique = {key: rows[0] for key, rows in candidates.items() if len(rows) == 1}
    ambiguous = {key for key, rows in candidates.items() if len(rows) > 1}
    if not candidates:
        raise ValueError("Importação legislativa sem senadores da lista oficial atual")
    # Grafias fixas dos diários, conferidas à mão (sem correspondência aproximada): só valem se o ID existe.
    by_id = {row["id"]: row for row in unique.values()}
    for spelling, identifier in DIARY_NAME_ALIASES.items():
        key = _normalize_name(spelling)
        if identifier in by_id and key not in unique and key not in ambiguous:
            unique[key] = by_id[identifier]
    return unique, ambiguous


def map_presence_rows(
    rows: list[dict[str, Any]],
    roster_index: dict[str, dict[str, Any]],
    ambiguous_names: set[str] | None = None,
) -> tuple[list[str], int, int]:
    """Map positive PDF rows only when normalized roster name is unique."""
    ambiguous_names = ambiguous_names or set()
    identifiers: set[str] = set()
    unmatched = 0
    ambiguous = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("presente") is not True:
            continue
        key = _normalize_name(row.get("nome"))
        if not key or key in ambiguous_names:
            unmatched += 1
            if key in ambiguous_names:
                ambiguous += 1
            continue
        profile = roster_index.get(key)
        if not profile:
            unmatched += 1
            continue
        identifiers.add(profile["id"])
    return sorted(identifiers, key=lambda value: int(value.split(":", 1)[1])), unmatched, ambiguous


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temp_path = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _month_cache_path(cache_root: Path, year: int, month: int) -> Path:
    return cache_root / f"agenda-diarios-{year}-{month:02d}.json"


def _diary_cache_path(cache_root: Path, diary_code: str) -> Path:
    if not diary_code.isdigit():
        raise ValueError("Código de diário inválido")
    return cache_root / f"diario-{diary_code}.json"


def _read_month_cache(path: Path, year: int, month: int) -> dict[str, Any] | None:
    value = _read_json(path)
    if not isinstance(value, dict) or value.get("year") != year or value.get("month") != month:
        return None
    if value.get("agendaUrl") != agenda_url(year, month) or value.get("calendarUrl") != calendar_url(year, month):
        return None
    if (
        not isinstance(value.get("agendaXml"), str)
        or not isinstance(value.get("calendarHtml"), str)
        or not _text(value.get("agendaFetchedAt"), 40)
        or not _text(value.get("calendarFetchedAt"), 40)
    ):
        return None
    try:
        parse_agenda_xml(value["agendaXml"], year, month, date(year, 12, 31))
        parse_calendar_html(value["calendarHtml"], year, month)
    except SourceError:
        return None
    return value


def _read_diary_cache(
    path: Path,
    diary_code: str,
    session_date: str,
    *,
    allow_legacy_undercoverage: bool = False,
) -> dict[str, Any] | None:
    value = _read_json(path)
    if not isinstance(value, dict) or value.get("diarioId") != diary_code:
        return None
    if value.get("calendarDate") != session_date or value.get("scanned") is not True:
        return None
    if not _text(value.get("fetchedAt"), 40) or value.get("sourceUrl") != diary_url(diary_code):
        return None
    tables = value.get("tables")
    if not isinstance(tables, list):
        return None
    for table in tables:
        if not isinstance(table, dict) or not isinstance(table.get("rows"), list):
            return None
        if table.get("method", "presence_column_x") not in {
            "presence_column_x", "attendance_timestamp",
        }:
            return None
        if not isinstance(table.get("total"), int) or table["total"] != len(table["rows"]):
            return None
        for row in table["rows"]:
            if (
                not isinstance(row, dict)
                or row.get("presente") is not True
                or not _text(row.get("nome"), 200)
                or not _text(row.get("uf"), 2)
            ):
                return None
    # Legacy scans looked only for "... e voto" in the contents. Revisit an
    # old cache when its summary lists more attendance sections than the
    # tables it contains; this repairs that known false negative while still
    # allowing already validated positive tables to be used offline.
    summary_text = value.get("sumarioText")
    if (
        not allow_legacy_undercoverage
        and value.get("parserVersion") != DIARY_PARSER_VERSION
        and isinstance(summary_text, str)
    ):
        if len(attendance_page_numbers([{"text": summary_text}])) > len(tables):
            return None
    return value


def _fetch_text(url: str, request: Callable[[str], tuple[bytes, str]]) -> tuple[str, str]:
    payload, fetched_at = request(url)
    if not isinstance(payload, (bytes, bytearray)):
        raise SourceError("Resposta oficial sem bytes.")
    try:
        return bytes(payload).decode("utf-8-sig"), fetched_at
    except UnicodeDecodeError as error:
        raise SourceError("Resposta textual da fonte não está em UTF-8.") from error


def _collect_month(
    year: int,
    month: int,
    cache_root: Path,
    request: Callable[[str], tuple[bytes, str]],
    refresh: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    path = _month_cache_path(cache_root, year, month)
    previous = _read_month_cache(path, year, month)
    if not refresh and previous is not None:
        return previous, None
    try:
        agenda_xml, agenda_fetched = _fetch_text(agenda_url(year, month), request)
        calendar_html, calendar_fetched = _fetch_text(calendar_url(year, month), request)
        parse_agenda_xml(agenda_xml, year, month, date(year, 12, 31))
        parse_calendar_html(calendar_html, year, month)
        value = {
            "year": year,
            "month": month,
            "agendaUrl": agenda_url(year, month),
            "agendaFetchedAt": agenda_fetched,
            "agendaXml": agenda_xml,
            "calendarUrl": calendar_url(year, month),
            "calendarFetchedAt": calendar_fetched,
            "calendarHtml": calendar_html,
        }
        _atomic_json(path, value)
        return value, None
    except Exception as error:
        if previous is not None:
            return previous, f"{year}-{month:02d}: refresh falhou ({type(error).__name__}); cache anterior preservado"
        return None, f"{year}-{month:02d}: não foi possível obter agenda/calendário ({type(error).__name__})"


def _table_from_summary(
    diary_code: str,
    calendar_date: str,
    metadata: dict[str, Any],
    summary_pdf: bytes,
    summary_fetched_at: str,
    request: Callable[[str], tuple[bytes, str]],
) -> tuple[list[dict[str, Any]], list[str], str]:
    summary_pages = _load_pdf_pages(summary_pdf)
    table_starts = attendance_page_numbers(summary_pages)
    if not table_starts:
        return [], [], summary_fetched_at

    tables: list[dict[str, Any]] = []
    errors: list[str] = []
    latest_fetched = summary_fetched_at
    for table_index, start_page in enumerate(table_starts, 1):
        if start_page > metadata["finalPage"]:
            errors.append(f"tabela {table_index}: página do sumário fora do caderno")
            continue
        end_page = min(metadata["finalPage"], start_page + ATTENDANCE_PAGE_LOOKAHEAD - 1)
        url = diary_pdf_url(diary_code, start_page, end_page)
        try:
            pdf_bytes, fetched_at = request(url)
            latest_fetched = max(latest_fetched, fetched_at)
            page_observations = _load_pdf_pages(pdf_bytes)
            parsed = parse_attendance_pages(page_observations, calendar_date)
            for offset, table in enumerate(parsed):
                table["page"] = start_page + offset
                table["sourceUrl"] = diary_url(diary_code)
                table["pdfUrl"] = url
                table["text"] = "\n".join(
                    page.get("text", "") for page in page_observations
                )[:100000]
                tables.append(table)
        except Exception as error:
            reason = str(error).strip() or type(error).__name__
            errors.append(f"tabela {table_index}: {type(error).__name__}: {reason[:180]}")
    return tables, errors, latest_fetched


def _collect_diary(
    entry: dict[str, str],
    cache_root: Path,
    request: Callable[[str], tuple[bytes, str]],
    refresh: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    diary_code = entry["diarioId"]
    calendar_date = entry["date"]
    cache_path = _diary_cache_path(cache_root, diary_code)
    previous = _read_diary_cache(cache_path, diary_code, calendar_date)
    fallback = previous or _read_diary_cache(
        cache_path, diary_code, calendar_date, allow_legacy_undercoverage=True
    )
    if not refresh and previous is not None:
        return previous, None

    try:
        html, page_fetched = _fetch_text(diary_url(diary_code), request)
        metadata = parse_diary_metadata(html)
        if metadata["date"] != calendar_date:
            raise SourceError("Data de sessão do caderno difere da data no calendário.")
        summary_url = diary_pdf_url(
            diary_code, metadata["sumarioStart"], metadata["sumarioEnd"]
        )
        summary_pdf, summary_fetched = request(summary_url)
        if not isinstance(summary_pdf, (bytes, bytearray)) or not bytes(summary_pdf).startswith(b"%PDF"):
            raise SourceError("Sumário do Diário não retornou PDF.")
        tables, errors, table_fetched = _table_from_summary(
            diary_code, calendar_date, metadata, bytes(summary_pdf), summary_fetched, request
        )
        if errors:
            raise SourceError("; ".join(errors))
        if fallback and fallback.get("tables") and not tables:
            raise SourceError("a tabela antes observada não apareceu no sumário atualizado")
        value = {
            "parserVersion": DIARY_PARSER_VERSION,
            "diarioId": diary_code,
            "calendarDate": calendar_date,
            "sourceUrl": diary_url(diary_code),
            "fetchedAt": max(page_fetched, summary_fetched, table_fetched),
            "scanned": True,
            "summaryUrl": summary_url,
            "sumarioText": "\n".join(page.get("text", "") for page in _load_pdf_pages(bytes(summary_pdf)))[:100000],
            "tables": tables,
            "detail": "; ".join(errors) if errors else None,
        }
        _atomic_json(cache_path, value)
        return value, None
    except Exception as error:
        if fallback is not None:
            stale = dict(fallback)
            stale["stale"] = True
            reason = str(error).strip() or type(error).__name__
            return stale, f"Diário {diary_code}: refresh falhou ({type(error).__name__}: {reason[:180]}); observação anterior mantida"
        reason = str(error).strip() or type(error).__name__
        return None, f"Diário {diary_code} ({calendar_date}): falha de leitura ({type(error).__name__}: {reason[:180]})"


def _load_roster(root: Path) -> Any:
    """Todos os senadores do banco (inclui quem saiu e suplentes), para ligar nomes de todo o mandato;
    sem banco, a lista legislativa atual."""
    database = root / "data" / "na-lupa.sqlite3"
    if database.exists():
        import sqlite3
        db = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            rows = db.execute("SELECT id,name,party,uf FROM authorities WHERE id LIKE 'senado:%' AND role='senador'").fetchall()
        finally:
            db.close()
        if rows:
            return {"authorities": [{"id": i, "name": n, "party": p, "uf": u, "role": "senador", "sourceId": SOURCE_ID}
                                    for i, n, p, u in rows]}
    try:
        return json.loads((root / "data" / "imports" / "legislative.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SourceError("Lista legislativa local não está disponível para associar os nomes.") from error


def _add_sessions_in_office(section: dict[str, Any], root: Path) -> None:
    """Por pessoa com presença, quantas sessões com lista validada caíram nos seus períodos de exercício
    (histórico de exercício do Senado em cache, de ``senate_cost.py``). Sem histórico, fica nulo."""
    from ingest import senate_cost
    exercise_dir = root / "data" / "raw" / "senado-exercicios"
    dates = [date.fromisoformat(row["date"]) for row in section.get("sessions", [])]
    for item in section.get("items", []):
        cache = exercise_dir / f"{item['id'].split(':', 1)[1]}.json"
        intervals = None
        if cache.exists():
            try:
                intervals = senate_cost.exercise_intervals(json.loads(cache.read_text(encoding="utf-8"))["payload"])
            except (ValueError, KeyError, TypeError):
                intervals = None
        item["sessoesEmExercicio"] = (sum(1 for day in dates if any(start <= day and (end is None or end >= day) for start, end in intervals))
                                      if intervals is not None else None)


def _build_attendance_section(
    year: int,
    period_start: date,
    period_end: date,
    months: list[dict[str, Any]],
    diaries: list[tuple[dict[str, str], dict[str, Any]]],
    roster_payload: Any,
    errors: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    roster_index, ambiguous_names = build_roster_index(roster_payload)
    agenda_events: list[dict[str, str]] = []
    expected_malformed = 0
    calendar_entries: list[dict[str, str]] = []
    latest_times: list[str] = []
    for month_cache in months:
        month = month_cache["month"]
        # Cada cache mensal traz o próprio ano: o mandato atravessa vários anos.
        cache_year = month_cache.get("year", year)
        events, malformed = parse_agenda_xml(
            month_cache["agendaXml"], cache_year, month, period_end
        )
        agenda_events.extend(events)
        expected_malformed += malformed
        calendar_entries.extend(
            entry for entry in parse_calendar_html(month_cache["calendarHtml"], cache_year, month)
            if entry["date"] <= period_end.isoformat()
        )
        latest_times.extend([
            month_cache["agendaFetchedAt"], month_cache["calendarFetchedAt"],
        ])

    agenda_by_date_type: dict[tuple[str, str], list[dict[str, str]]] = {}
    for event in agenda_events:
        agenda_by_date_type.setdefault((event["date"], event["type"]), []).append(event)
    calendar_by_diary = {entry["diarioId"]: entry for entry in calendar_entries}

    session_rows: list[dict[str, Any]] = []
    presence_counts: Counter[str] = Counter()
    unmatched_rows = 0
    ambiguous_rows = 0
    assigned_agenda: set[str] = set()
    seen_session_identities: set[tuple[str, str, int]] = set()
    diary_table_count = 0
    method_counts: Counter[str] = Counter()
    # If the same session is reprinted or retified in another caderno, use
    # the highest caderno id once and never add its presence marks twice.
    ordered_diaries = sorted(
        diaries,
        key=lambda item: (item[0]["date"], -int(item[0]["diarioId"])),
    )
    for entry, cached_diary in ordered_diaries:
        if not isinstance(cached_diary, dict) or cached_diary.get("scanned") is not True:
            continue
        fetched = _text(cached_diary.get("fetchedAt"), 40)
        if fetched:
            latest_times.append(fetched)
        diary_id = entry["diarioId"]
        for table_index, table in enumerate(cached_diary.get("tables", []), 1):
            if not isinstance(table, dict) or not isinstance(table.get("rows"), list):
                errors.append(f"Diário {diary_id}: cache de tabela inválido")
                continue
            table_date = entry["date"]
            kind = table.get("type")
            if not isinstance(kind, str) or table_date > period_end.isoformat():
                errors.append(f"Diário {diary_id}: data/tipo da tabela não confirmado")
                continue
            ordinal = table.get("ordinal")
            if not isinstance(ordinal, int):
                identity = _session_identity(table.get("text", ""))
                ordinal = identity[1] if identity and identity[0] == kind else None
            if not isinstance(ordinal, int):
                errors.append(f"Diário {diary_id}/{table_index}: número ordinal da sessão não confirmado")
                continue
            identity_key = (table_date, kind, ordinal)
            if identity_key in seen_session_identities:
                errors.append(
                    f"Diário {diary_id}/{table_index}: cópia repetida da sessão "
                    f"{table_date}/{kind}/{ordinal}; presenças duplicadas ignoradas"
                )
                continue
            seen_session_identities.add(identity_key)
            key = (table_date, kind)
            matching_events = [
                event for event in agenda_by_date_type.get(key, [])
                if event["id"] not in assigned_agenda
            ]
            if len(matching_events) == 1:
                session_id = matching_events[0]["id"]
                assigned_agenda.add(session_id)
            else:
                session_id = f"senado-diario:{diary_id}:{table_index}"
                if not matching_events:
                    errors.append(
                        f"Tabela {diary_id}/{table_index} ({table_date}) sem sessão realizada correspondente na agenda"
                    )
                else:
                    errors.append(
                        f"Tabela {diary_id}/{table_index} ({table_date}) tem mais de uma sessão correspondente na agenda"
                    )

            present_ids, unmatched, ambiguous = map_presence_rows(
                table["rows"], roster_index, ambiguous_names
            )
            evidence_method = table.get("method", "presence_column_x")
            if evidence_method not in {"presence_column_x", "attendance_timestamp"}:
                errors.append(f"Diário {diary_id}/{table_index}: método de presença inválido")
                continue
            method_counts[evidence_method] += 1
            unmatched_rows += unmatched
            ambiguous_rows += ambiguous
            presence_counts.update(present_ids)
            session_rows.append({
                "id": session_id,
                "date": table_date,
                "sourceUrl": cached_diary["sourceUrl"],
                "presentIds": present_ids,
                "method": evidence_method,
            })
            diary_table_count += 1

    missing_agenda = [event for event in agenda_events if event["id"] not in assigned_agenda]
    if missing_agenda:
        errors.append(f"{len(missing_agenda)} sessão(ões) realizadas na agenda sem tabela DSF validada")
    if expected_malformed:
        errors.append(f"{expected_malformed} item(ns) da agenda deliberativa sem campos suficientes")

    session_rows.sort(key=lambda row: (row["date"], row["id"]))
    roster_by_id = {
        value["id"]: value for value in roster_index.values()
    }
    items = []
    for identifier, count in sorted(presence_counts.items(), key=lambda pair: int(pair[0].split(":", 1)[1])):
        profile = roster_by_id[identifier]
        items.append({
            "id": identifier,
            "nome": profile["nome"],
            "partido": profile["partido"],
            "uf": profile["uf"],
            "presente": count,
            "dias": None,
            "falta": None,
            "justificadas": None,
        })

    unique_unmatched = len({
        _normalize_name(row.get("nome"))
        for _entry, cached_diary in diaries
        if isinstance(cached_diary, dict)
        for table in cached_diary.get("tables", [])
        if isinstance(table, dict)
        for row in table.get("rows", [])
        if _normalize_name(row.get("nome")) not in roster_index
    })
    detail_parts = [
        f"Presenças positivas registradas em {diary_table_count} tabelas de sessões deliberativas do DSF, "
        f"com sessão realizada até {period_end.isoformat()}.",
        f"Evidência: {method_counts['presence_column_x']} tabela(s) com X na coluna Presença e "
        f"{method_counts['attendance_timestamp']} com horário nominal explícito na coluna Horário.",
        "Linha ausente e voto sem X não viram falta; X na coluna Voto não é usado como presença.",
        "Faltas, justificativas e dias não foram coletados e permanecem nulos.",
        f"Agenda oficial: {len(agenda_events)} sessões deliberativas realizadas enumeradas; "
        f"{len(missing_agenda)} sem tabela validada.",
        f"{unmatched_rows} registro(s) de comparecimento ({unique_unmatched} nomes ou grafias) "
        f"sem associação segura ao cadastro atual; {ambiguous_rows} registro(s) ambíguos.",
        "As contagens individuais podem estar incompletas; são apenas os comparecimentos associados com segurança.",
    ]
    if errors:
        detail_parts.append(f"Coleta parcial: {len(errors)} divergência(s)/falha(s) registrada(s).")
    fetched_at = max(latest_times) if latest_times else None
    section = {
        "status": "partial",
        "unit": "sessoes",
        "period": f"{period_start.isoformat()} a {period_end.isoformat()}",
        "sourceUrl": TUTORIAL_URL,
        "fetchedAt": fetched_at,
        "detail": " ".join(detail_parts),
        "sessionCount": len(session_rows),
        "items": items,
        "sessions": session_rows,
    }
    stats = {
        "diaries": len(calendar_entries),
        "scannedDiaries": len(diaries),
        "agendaSessions": len(agenda_events),
        "sessions": len(session_rows),
        "profiles": len(items),
        "unmatchedRows": unmatched_rows,
        "ambiguousRows": ambiguous_rows,
        "methods": dict(method_counts),
        "uniqueUnmatchedNames": unique_unmatched,
        "errors": errors,
    }
    return section, stats


def build_snapshot(
    year: int | None = None,
    *,
    root: Path = ROOT,
    output: Path | None = None,
    collect: bool = False,
    refresh: bool = False,
    request: Callable[[str], tuple[bytes, str]] = _request_bytes,
    today: date | None = None,
    roster: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    period_start, period_end = _period_dates(year, today)
    if refresh and not collect:
        raise ValueError("--refresh exige --collect.")
    if collect:
        _require_pdf_parser()
    cache_root = root / "data" / "raw" / "senado-presenca"
    month_caches: list[dict[str, Any]] = []
    errors: list[str] = []
    for cache_year, month in _months(period_start, period_end):
        path = _month_cache_path(cache_root, cache_year, month)
        if collect:
            cache, error = _collect_month(cache_year, month, cache_root, request, refresh)
            if error:
                errors.append(error)
        else:
            cache = _read_month_cache(path, cache_year, month)
            if cache is None:
                errors.append(f"{cache_year}-{month:02d}: cache de agenda/calendário ausente ou inválido")
        if cache is not None:
            month_caches.append(cache)

    if not month_caches:
        raise SourceError("Não há cache validado de agenda/calendário; snapshot preservado.")

    calendar_entries: list[dict[str, str]] = []
    for month_cache in month_caches:
        calendar_entries.extend(
            entry for entry in parse_calendar_html(
                month_cache["calendarHtml"], month_cache.get("year", year), month_cache["month"]
            )
            if period_start.isoformat() <= entry["date"] <= period_end.isoformat()
        )
    # A calendar can repeat a caderno link; keep one date/code pair.
    unique_entries = {
        (entry["diarioId"], entry["date"]): entry for entry in calendar_entries
    }
    calendar_entries = sorted(
        unique_entries.values(), key=lambda row: (row["date"], int(row["diarioId"]))
    )

    diaries: list[tuple[dict[str, str], dict[str, Any]]] = []
    for entry in calendar_entries:
        path = _diary_cache_path(cache_root, entry["diarioId"])
        if collect:
            diary, error = _collect_diary(entry, cache_root, request, refresh)
            if error:
                errors.append(error)
        else:
            diary = _read_diary_cache(path, entry["diarioId"], entry["date"])
            if diary is None:
                errors.append(f"Diário {entry['diarioId']} ({entry['date']}): cache de leitura ausente ou inválido")
        if diary is not None:
            diaries.append((entry, diary))

    roster_payload = roster if roster is not None else _load_roster(root)
    section, stats = _build_attendance_section(
        year or period_end.year, period_start, period_end, month_caches, diaries, roster_payload, errors
    )
    _add_sessions_in_office(section, root)
    if section["sessionCount"] == 0:
        raise SourceError("Nenhuma tabela de presença foi validada; snapshot anterior preservado.")
    snapshot = {"generatedAt": utc_now(), "year": year, "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
                "presenca": section}
    stats["errors"] = errors
    stats["monthCaches"] = len(month_caches)
    if output is not None:
        _atomic_json(output, snapshot)
    else:
        _atomic_json(root / "data" / "snapshots" / "senado-presenca.json", snapshot)
    return snapshot, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=None, help="um ano só (padrão: o mandato, de fev/2023 até hoje)")
    parser.add_argument("--collect", action="store_true", help="consultar fontes oficiais; padrão é offline")
    parser.add_argument("--refresh", action="store_true", help="forçar atualização dos caches PDF e de agenda")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        snapshot, stats = build_snapshot(
            year=args.year, collect=args.collect, refresh=args.refresh, output=args.output,
        )
    except (SourceError, ValueError) as error:
        parser.error(str(error))
    print(
        f"Senado {args.year or 'mandato'}: {stats['sessions']} tabelas/sessões validadas; "
        f"{stats['profiles']} IDs com presença positiva; "
        f"{stats['unmatchedRows']} linhas sem ID único; snapshot {args.output}"
    )
    for error in stats["errors"]:
        print(f"AVISO: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
