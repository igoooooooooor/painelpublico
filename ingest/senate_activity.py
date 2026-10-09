#!/usr/bin/env python3
"""Build a local snapshot of Senate nominal votes for a calendar year.

The default run is offline and reads the raw cache. ``--collect`` fetches the
official Senate open-data API when the cache is missing; ``--refresh`` forces
an update. If the separate DSF attendance collector has produced a matching
snapshot, its session counts are reused; otherwise attendance stays explicitly
unavailable instead of treating missing vote rows as absences.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "data" / "snapshots" / "senado-atividade.json"
API_BASE = "https://legis.senado.leg.br/dadosabertos"
VOTES_ENDPOINT = f"{API_BASE}/votacao"
ATTENDANCE_GUIDE_URL = (
    "https://www12.senado.leg.br/assessoria-de-imprensa/guia-para-jornalistas/"
    "tutorial-de-verificacao-da-assiduidade-dos-senadores"
)
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
HTTP_TIMEOUT = 45
HTTP_RETRIES = 1
YEAR = 2026
MANDATE_START = date(2023, 2, 1)


class SourceError(RuntimeError):
    """Raised when the official endpoint cannot provide a valid vote snapshot."""


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
        parts.scheme == "https"
        and not parts.username
        and not parts.password
        and (host == "senado.leg.br" or host.endswith(".senado.leg.br"))
    ):
        return value
    return None


def votes_url(
    year: int = YEAR,
    through: date | None = None,
    start: date | None = None,
) -> str:
    start = start or date(year, 1, 1)
    cutoff = min(through or date.today(), date.today())
    end = min(cutoff, date(year, 12, 31))
    if start.year != year:
        raise ValueError(f"Data inicial fora do ano de consulta {year}.")
    if end < start:
        raise ValueError(f"Data de consulta anterior ao recorte de {year}.")
    params = urlencode({"dataInicio": start.isoformat(), "dataFim": end.isoformat()})
    return f"{VOTES_ENDPOINT}?{params}"


def vote_session_url(session_code: Any) -> str | None:
    code = str(session_code or "")
    if not code.isdigit():
        return None
    return f"{VOTES_ENDPOINT}?{urlencode({'codigoSessao': code})}"


def request_json(url: str) -> tuple[Any, str]:
    """Fetch JSON from a known Senate endpoint and stamp the successful read."""
    last_error: Exception | None = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            request = Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            with urlopen(request, timeout=HTTP_TIMEOUT) as response:
                payload = json.load(response)
            return payload, utc_now()
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < HTTP_RETRIES:
                time.sleep(0.5 * (attempt + 1))
    raise SourceError(f"Falha ao consultar API do Senado ({type(last_error).__name__}).") from last_error


def _normalized_vote_payload(
    payload: Any,
    year: int = YEAR,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return public, non-secret nominal votes and counts for omitted records."""
    if not isinstance(payload, list):
        raise SourceError("A API de votações do Senado não retornou uma lista JSON.")

    items: list[dict[str, Any]] = []
    counts = {"secret": 0, "malformed": 0, "unclassified": 0, "duplicate": 0}
    seen: set[str] = set()
    for source_row in payload:
        if not isinstance(source_row, dict):
            continue
        data = _text(source_row.get("dataSessao"), 10)
        if not data or data[:4] != str(year) or source_row.get("casaSessao") != "SF":
            continue
        try:
            session_date = date.fromisoformat(data)
        except ValueError:
            counts["malformed"] += 1
            continue
        if start_date and session_date < start_date:
            continue
        if end_date and session_date > end_date:
            continue

        secrecy = source_row.get("votacaoSecreta")
        if secrecy == "S":
            counts["secret"] += 1
            continue
        if secrecy != "N":
            counts["malformed"] += 1
            continue

        description = _text(source_row.get("descricaoVotacao"), 1000)
        normalized_description = unicodedata.normalize("NFD", description or "")
        normalized_description = "".join(
            char for char in normalized_description if unicodedata.category(char) != "Mn"
        ).casefold()
        source_votes = source_row.get("votos")
        has_individual_votes = isinstance(source_votes, list) and bool(source_votes)
        if "votacao nominal" not in normalized_description and not has_individual_votes:
            counts["unclassified"] += 1
            continue
        session_code = source_row.get("codigoSessao")
        voting_sequence = source_row.get("sequencialVotacao")
        legacy_voting_code = source_row.get("codigoSessaoVotacao")
        suffix = voting_sequence if voting_sequence is not None else legacy_voting_code
        if (
            session_code is None
            or suffix is None
            or not str(session_code).isdigit()
            or not str(suffix).isdigit()
        ):
            counts["malformed"] += 1
            continue
        identifier = f"senado:{session_code}:{suffix}"

        rows = []
        if not isinstance(source_votes, list) or not source_votes:
            counts["malformed"] += 1
            continue
        has_explicit_choice = False
        invalid_rows = 0
        for vote in source_votes:
            if not isinstance(vote, dict):
                invalid_rows += 1
                continue
            parliamentary_code = vote.get("codigoParlamentar")
            if parliamentary_code is None or not str(parliamentary_code).isdigit():
                invalid_rows += 1
                continue
            name = _text(vote.get("nomeParlamentar"), 200)
            if not name:
                invalid_rows += 1
                continue
            vote_label = _text(vote.get("descricaoVotoParlamentar"), 200)
            vote_label = vote_label or _text(vote.get("siglaVotoParlamentar"), 80)
            for choice in (
                vote.get("descricaoVotoParlamentar"),
                vote.get("siglaVotoParlamentar"),
            ):
                normalized_choice = unicodedata.normalize("NFD", str(choice or ""))
                normalized_choice = "".join(
                    char for char in normalized_choice
                    if unicodedata.category(char) != "Mn"
                ).strip().casefold()
                if normalized_choice in {"sim", "nao", "abstencao", "obstrucao"}:
                    has_explicit_choice = True
            rows.append([
                f"senado:{parliamentary_code}",
                name,
                _text(vote.get("siglaPartidoParlamentar"), 80),
                _text(vote.get("siglaUFParlamentar"), 2),
                vote_label,
            ])

        if invalid_rows:
            counts["malformed"] += invalid_rows
        if not rows:
            counts["malformed"] += 1
            continue
        if not has_explicit_choice:
            counts["unclassified"] += 1
            continue

        if identifier in seen:
            counts["duplicate"] += 1
            continue
        seen.add(identifier)

        proposition = _text(source_row.get("identificacao"), 300)
        title = description or proposition or "Votação nominal"
        if proposition and proposition.casefold() not in title.casefold():
            title = f"{title} ({proposition})"
        items.append({
            "id": identifier,
            "titulo": title[:1200],
            "data": data,
            "proposicao": proposition,
            "sourceUrl": vote_session_url(session_code),
            "secreta": False,
            "rows": rows,
        })

    return sorted(items, key=lambda item: (item["data"], item["id"]), reverse=True), counts


def normalize_votes(payload: Any, year: int = YEAR) -> list[dict[str, Any]]:
    """Convert public, non-secret nominal votes to the profile snapshot contract."""
    items, _ = _normalized_vote_payload(payload, year)
    return items


def _source_period(source_url: str, year: int, fetched_at: str) -> str:
    params = parse_qs(urlsplit(source_url).query)
    start = (params.get("dataInicio") or [None])[0]
    end = (params.get("dataFim") or [None])[0]
    try:
        if date.fromisoformat(start or "").year != year or date.fromisoformat(end or "").year != year:
            raise ValueError
    except ValueError:
        end = fetched_at[:10] if fetched_at[:4] == str(year) else f"{year}-12-31"
        start = f"{year}-01-01"
    return f"{start} a {end} (data consultada)"


def _cache_path(root: Path, year: int) -> Path:
    return root / "data" / "raw" / "senado-atividade" / f"votacoes-{year}.json"


def _snapshot_path(root: Path) -> Path:
    return root / "data" / "snapshots" / "senado-atividade.json"


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            file_name = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(file_name, path)
    finally:
        if file_name and os.path.exists(file_name):
            os.unlink(file_name)


def _cache_dates(cache: dict[str, Any], year: int) -> tuple[date, date] | None:
    source_url = _official_url(cache.get("sourceUrl"))
    if not source_url:
        return None
    params = parse_qs(urlsplit(source_url).query)
    try:
        start = date.fromisoformat((params.get("dataInicio") or [""])[0])
        end = date.fromisoformat((params.get("dataFim") or [""])[0])
    except ValueError:
        return None
    if start.year != year or end.year != year or end < start:
        return None
    return start, end


def _read_cache(
    path: Path,
    year: int,
    start_date: date | None = None,
    end_date: date | None = None,
    allow_empty: bool = False,
) -> dict[str, Any] | None:
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(cache, dict):
        return None
    source_url = _official_url(cache.get("sourceUrl"))
    fetched_at = _text(cache.get("fetchedAt"), 40)
    raw_rows = cache.get("data")
    if not source_url or not fetched_at or not isinstance(raw_rows, list):
        return None
    coverage = _cache_dates(cache, year)
    if coverage is None:
        return None
    if start_date and coverage[0] > start_date:
        return None
    if end_date and coverage[1] < end_date:
        return None
    try:
        items = normalize_votes(raw_rows, year)
    except SourceError:
        return None
    if not items and not allow_empty:
        return None
    return {"sourceUrl": source_url, "fetchedAt": fetched_at, "data": raw_rows}


def _fetch_cache(
    year: int,
    request: Callable[[str], tuple[Any, str]] = request_json,
    start_date: date | None = None,
    end_date: date | None = None,
    allow_empty: bool = False,
) -> dict[str, Any]:
    source_url = votes_url(year, end_date, start_date)
    payload, fetched_at = request(source_url)
    if not isinstance(payload, list):
        raise SourceError("A API de votações do Senado não retornou uma lista JSON.")
    items, _counts = _normalized_vote_payload(payload, year, start_date, end_date)
    if not items and not allow_empty:
        raise SourceError(f"A API não retornou votações do Senado para {year}; snapshot não atualizado.")
    return {"sourceUrl": source_url, "fetchedAt": fetched_at, "data": payload}


def _attendance_section(year: int) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "unit": "sessoes",
        "period": str(year),
        "sourceUrl": ATTENDANCE_GUIDE_URL,
        "fetchedAt": None,
        "detail": (
            "No levantamento feito para este snapshot, não foi encontrada lista individual de presença "
            "na API de Dados Abertos consultada. O Senado orienta consultar a ata no Diário do Senado "
            "Federal, publicada no dia seguinte; justificativas saem nos Diários de sexta-feira. "
            "Esse acervo não está disponível neste snapshot. Itens e contagens ficam indisponíveis; "
            "voto ausente não é classificado como falta."
        ),
        "items": [],
    }


def _attendance_from_snapshot(root: Path, year: int) -> dict[str, Any]:
    """Reuse official DSF attendance when the separate collector supplied it."""
    path = root / "data" / "snapshots" / "senado-presenca.json"
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _attendance_section(year)
    # O coletor do Diário cobre o mandato (year nulo, com o período) ou um ano só.
    if not isinstance(snapshot, dict) or snapshot.get("year") not in (year, None):
        return _attendance_section(year)
    section = snapshot.get("presenca")
    if not isinstance(section, dict) or not isinstance(section.get("items"), list):
        return _attendance_section(year)
    if section.get("unit") != "sessoes":
        return _attendance_section(year)
    return section


def build_snapshot(
    root: Path = ROOT,
    output: Path | None = None,
    year: int = YEAR,
    collect: bool = False,
    refresh: bool = False,
    request: Callable[[str], tuple[Any, str]] = request_json,
) -> tuple[dict[str, Any], dict[str, int]]:
    if year != YEAR:
        raise ValueError(f"Este coletor está limitado ao recorte autorizado de {YEAR}.")
    if refresh and not collect:
        raise ValueError("--refresh exige --collect.")

    cache_path = _cache_path(root, year)
    previous = _read_cache(cache_path, year)
    stale_error = None
    cache = previous
    if collect and (refresh or cache is None):
        try:
            cache = _fetch_cache(year, request)
            _atomic_json(cache_path, cache)
        except Exception as error:
            if previous is None:
                raise SourceError(
                    f"Falha na coleta sem cache válido; nenhum snapshot de votação foi gravado: "
                    f"{type(error).__name__}."
                ) from error
            cache = previous
            stale_error = f"Falha ao atualizar ({type(error).__name__}); mantida a coleta anterior."

    if cache is None:
        raise SourceError("Cache de votações ausente ou inválido; use --collect para consultar o Senado.")

    items, counts = _normalized_vote_payload(cache["data"], year)
    if not items:
        raise SourceError("Cache sem votações válidas do Senado; snapshot não gravado.")
    period = _source_period(cache["sourceUrl"], year, cache["fetchedAt"])
    partial_reasons = []
    if stale_error:
        partial_reasons.append(stale_error)
    if counts["malformed"]:
        partial_reasons.append(
            f"{counts['malformed']} linha(s) nominal(is) malformada(s) foram excluídas."
        )
    if counts["unclassified"]:
        partial_reasons.append(
            f"{counts['unclassified']} registro(s) sem identificação de votação nominal foram excluídos."
        )
    if counts["duplicate"]:
        partial_reasons.append(f"{counts['duplicate']} registro(s) duplicado(s) foram excluídos.")
    details = [
        "A lista contém votações nominais públicas; votações secretas não entram nos itens.",
        f"{counts['secret']} votação(ões) secreta(s) foram excluídas da lista de votos individuais.",
        "Rótulos do Senado são preservados literalmente. Atividade parlamentar, presença sem voto, "
        "licenças, não comparecimento e presidência não são convertidos em Sim, Não, Abstenção ou falta.",
    ]
    details.extend(partial_reasons)
    vote_section: dict[str, Any] = {
        "status": "partial" if partial_reasons else "imported",
        "period": period,
        "sourceUrl": cache["sourceUrl"],
        "fetchedAt": cache["fetchedAt"],
        "detail": " ".join(details),
        "secretCount": counts["secret"],
        "items": items,
    }
    snapshot = {
        "generatedAt": utc_now(),
        "year": year,
        "presenca": _attendance_from_snapshot(root, year),
        "votacoes": vote_section,
    }
    destination = output or _snapshot_path(root)
    _atomic_json(destination, snapshot)
    stats = {
        "votes": len(items),
        "voteRows": sum(len(item["rows"]) for item in items),
        "secretVotes": counts["secret"],
        "malformedRows": counts["malformed"],
        "snapshotBytes": destination.stat().st_size,
    }
    return snapshot, stats


def _load_existing_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _mandate_cutoff(through: date | None) -> date:
    cutoff = min(through or date.today(), date.today())
    if cutoff < MANDATE_START:
        raise ValueError(f"Data final anterior ao início do mandato ({MANDATE_START.isoformat()}).")
    return cutoff


def _mandate_cached_items(
    cache: dict[str, Any], year: int, start_date: date, end_date: date,
) -> tuple[list[dict[str, Any]], dict[str, int], tuple[date, date] | None]:
    coverage = _cache_dates(cache, year)
    if coverage is None:
        return [], {"secret": 0, "malformed": 0, "unclassified": 0, "duplicate": 0}, None
    actual_start = max(start_date, coverage[0])
    actual_end = min(end_date, coverage[1])
    if actual_end < actual_start:
        return [], {"secret": 0, "malformed": 0, "unclassified": 0, "duplicate": 0}, None
    items, counts = _normalized_vote_payload(
        cache["data"], year, actual_start, actual_end,
    )
    return items, counts, (actual_start, actual_end)


def _previous_year_data(
    snapshot: dict[str, Any] | None,
    year: int,
    start_date: date,
    end_date: date,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not snapshot or not isinstance(snapshot.get("votacoes"), dict):
        return [], None
    section = snapshot["votacoes"]
    sources = section.get("sources")
    source = None
    if isinstance(sources, list):
        source = next((row for row in sources if isinstance(row, dict) and row.get("year") == year), None)
    items = section.get("items")
    if not isinstance(items, list):
        items = []
    year_items = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("data"), str):
            continue
        try:
            item_date = date.fromisoformat(item["data"])
        except ValueError:
            continue
        if item_date.year == year and start_date <= item_date <= end_date:
            year_items.append(item)

    # Compatibilidade com o snapshot anual anterior à expansão desde 2023.
    if source is None and snapshot.get("year") == year:
        source = {
            "year": year,
            "sourceUrl": section.get("sourceUrl"),
            "fetchedAt": section.get("fetchedAt"),
        }
    return year_items, source


def _snapshot_source_range(source: dict[str, Any] | None, year: int) -> tuple[date, date] | None:
    if not isinstance(source, dict):
        return None
    coverage = _cache_dates({"sourceUrl": source.get("sourceUrl")}, year)
    if coverage is None:
        return None
    start, end = coverage
    try:
        if source.get("startDate"):
            start = max(start, date.fromisoformat(str(source["startDate"])))
        if source.get("endDate"):
            end = min(end, date.fromisoformat(str(source["endDate"])))
    except ValueError:
        return None
    return (start, end) if start <= end else None


def build_mandate_snapshot(
    root: Path = ROOT,
    output: Path | None = None,
    collect: bool = False,
    refresh: bool = False,
    through: date | None = None,
    request: Callable[[str], tuple[Any, str]] = request_json,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Build the 2023–current Senate vote snapshot from bounded annual caches."""
    if refresh and not collect:
        raise ValueError("--refresh exige --collect.")
    cutoff = _mandate_cutoff(through)
    destination = output or _snapshot_path(root)
    previous_snapshot = _load_existing_snapshot(destination)

    all_items: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    partial_reasons: list[str] = []
    aggregate = {"secret": 0, "malformed": 0, "unclassified": 0, "duplicate": 0}
    seen_ids: set[str] = set()
    complete_sources = 0

    for year in range(MANDATE_START.year, cutoff.year + 1):
        requested_start = max(MANDATE_START, date(year, 1, 1))
        requested_end = min(cutoff, date(year, 12, 31))
        cache_path = _cache_path(root, year)
        previous_cache = _read_cache(cache_path, year, allow_empty=True)
        previous_coverage = _cache_dates(previous_cache, year) if previous_cache else None
        cache_covers = bool(
            previous_coverage
            and previous_coverage[0] <= requested_start
            and previous_coverage[1] >= requested_end
        )
        needs_fetch = collect and (
            refresh or previous_cache is None or not cache_covers
        )
        cache = previous_cache
        refresh_error: str | None = None
        if needs_fetch:
            try:
                cache = _fetch_cache(
                    year,
                    request,
                    requested_start,
                    requested_end,
                    allow_empty=True,
                )
                _atomic_json(cache_path, cache)
            except Exception as error:
                refresh_error = (
                    f"Falha ao consultar {year} ({type(error).__name__}); "
                    "a coleta anterior foi preservada."
                )
                cache = previous_cache

        items: list[dict[str, Any]] = []
        counts = {"secret": 0, "malformed": 0, "unclassified": 0, "duplicate": 0}
        actual_range: tuple[date, date] | None = None
        if cache:
            items, counts, actual_range = _mandate_cached_items(
                cache, year, requested_start, requested_end,
            )

        fallback_used = False
        fallback_source = None
        fallback_items: list[dict[str, Any]] = []
        requested_covered = bool(
            actual_range
            and actual_range[0] <= requested_start
            and actual_range[1] >= requested_end
        )
        if cache is None or not requested_covered:
            fallback_items, fallback_source = _previous_year_data(
                previous_snapshot, year, requested_start, requested_end,
            )
            fallback_source_range = _snapshot_source_range(fallback_source, year)
            cache_range = actual_range
            previous_covers_cache = bool(
                fallback_source_range
                and cache_range
                and fallback_source_range[0] <= cache_range[0]
                and fallback_source_range[1] >= cache_range[1]
            )
            if cache is None and (fallback_items or fallback_source):
                fallback_source = fallback_source or {}
                items = fallback_items
                fallback_used = True
                if fallback_source_range:
                    bounded_start = max(requested_start, fallback_source_range[0])
                    bounded_end = min(requested_end, fallback_source_range[1])
                    actual_range = (bounded_start, bounded_end) if bounded_start <= bounded_end else None
            elif previous_covers_cache:
                fallback_source = fallback_source or {}
                items = fallback_items
                bounded_start = max(requested_start, fallback_source_range[0])
                bounded_end = min(requested_end, fallback_source_range[1])
                actual_range = (bounded_start, bounded_end) if bounded_start <= bounded_end else None
                fallback_used = True

        has_coverage = bool(
            actual_range
            and actual_range[0] <= requested_start
            and actual_range[1] >= requested_end
        )
        source_url = cache.get("sourceUrl") if cache else None
        fetched_at = cache.get("fetchedAt") if cache else None
        if fallback_used:
            source_url = fallback_source.get("sourceUrl")
            fetched_at = fallback_source.get("fetchedAt")
            status = "partial" if actual_range else "missing"
        elif (
            has_coverage
            and not refresh_error
            and not counts["malformed"]
            and not counts["unclassified"]
            and not counts["duplicate"]
        ):
            status = "imported"
        elif actual_range:
            status = "partial"
        else:
            status = "missing"

        if status == "imported":
            complete_sources += 1
        if refresh_error:
            partial_reasons.append(refresh_error)
        if status == "missing":
            partial_reasons.append(f"Cache de votações sem cobertura válida para {year}.")
        elif status == "partial" and actual_range:
            if fallback_used:
                partial_reasons.append(
                    f"Dados e cobertura de {year} preservados do snapshot anterior."
                )
            elif not has_coverage:
                partial_reasons.append(f"Cobertura incompleta de votações para {year}.")
        if counts["malformed"]:
            partial_reasons.append(f"{counts['malformed']} linha(s) malformada(s) em {year} foram excluídas.")
        if counts["unclassified"]:
            partial_reasons.append(
                f"{counts['unclassified']} registro(s) sem identificação nominal em {year} foram excluídos."
            )
        if counts["duplicate"]:
            partial_reasons.append(f"{counts['duplicate']} registro(s) duplicado(s) em {year} foram excluídos.")

        for key in aggregate:
            aggregate[key] += counts[key]
        for item in items:
            identifier = item.get("id")
            if isinstance(identifier, str) and identifier in seen_ids:
                aggregate["duplicate"] += 1
                continue
            if isinstance(identifier, str):
                seen_ids.add(identifier)
            all_items.append(item)

        source_rows.append({
            "year": year,
            "sourceUrl": source_url if isinstance(source_url, str) else None,
            "status": status,
            "fetchedAt": fetched_at if isinstance(fetched_at, str) else None,
            "startDate": actual_range[0].isoformat() if actual_range else None,
            "endDate": actual_range[1].isoformat() if actual_range else None,
            **(
                {"detail": refresh_error}
                if refresh_error
                else (
                    {"detail": "Dados e cobertura preservados do snapshot anterior."}
                    if fallback_used
                    else {}
                )
            ),
        })

    if not all_items:
        raise SourceError("Nenhuma votação disponível; snapshot de mandato não gravado.")

    all_items.sort(key=lambda item: (item.get("data", ""), item.get("id", "")), reverse=True)
    if complete_sources != len(source_rows):
        overall_status = "partial"
    elif partial_reasons:
        overall_status = "partial"
    else:
        overall_status = "imported"
    source_urls = [row["sourceUrl"] for row in source_rows if row.get("sourceUrl")]
    fetched_values = [row["fetchedAt"] for row in source_rows if row.get("fetchedAt")]
    section_details = [
        "Lista de votações nominais públicas do Senado desde 1º de fevereiro de 2023.",
        "Votações secretas e registros sem confirmação explícita de votação pública foram excluídos.",
        "Rótulos do Senado são preservados; ausência de voto não é classificada como falta.",
    ]
    if partial_reasons:
        section_details.append("Cobertura parcial: " + " ".join(dict.fromkeys(partial_reasons)))
    vote_section = {
        "status": overall_status,
        "period": f"{MANDATE_START.isoformat()} a {cutoff.isoformat()} (data consultada)",
        "startDate": MANDATE_START.isoformat(),
        "endDate": cutoff.isoformat(),
        "sourceUrl": source_urls[-1] if source_urls else None,
        "sources": source_rows,
        "fetchedAt": max(fetched_values) if fetched_values else None,
        "detail": " ".join(section_details),
        "secretCount": aggregate["secret"],
        "items": all_items,
    }
    snapshot = {
        "generatedAt": utc_now(),
        "year": YEAR,
        "presenca": _attendance_from_snapshot(root, YEAR),
        "votacoes": vote_section,
    }
    _atomic_json(destination, snapshot)
    stats = {
        "votes": len(all_items),
        "voteRows": sum(len(item["rows"]) for item in all_items),
        "secretVotes": aggregate["secret"],
        "malformedRows": aggregate["malformed"],
        "missingYears": sum(row["status"] == "missing" for row in source_rows),
        "partialYears": sum(row["status"] == "partial" for row in source_rows),
        "snapshotBytes": destination.stat().st_size,
    }
    return snapshot, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera snapshot local de votações nominais do Senado")
    parser.add_argument("--year", type=int, default=YEAR, help="ano do recorte (somente 2026)")
    parser.add_argument("--mandate", action="store_true", help="inclui votações desde 1º de fevereiro de 2023")
    parser.add_argument("--through", type=date.fromisoformat, help="limita o recorte a YYYY-MM-DD")
    parser.add_argument("--collect", action="store_true", help="consulta a API oficial se o cache estiver ausente")
    parser.add_argument("--refresh", action="store_true", help="atualiza o cache mesmo que exista")
    parser.add_argument("--output", type=Path, help="caminho do snapshot JSON de saída")
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error("--refresh exige --collect")
    destination = args.output
    if destination is not None and not destination.is_absolute():
        destination = ROOT / destination
    try:
        if args.mandate:
            snapshot, stats = build_mandate_snapshot(
                output=destination,
                collect=args.collect,
                refresh=args.refresh,
                through=args.through,
            )
        else:
            if args.through is not None:
                parser.error("--through exige --mandate.")
            snapshot, stats = build_snapshot(
                output=destination,
                year=args.year,
                collect=args.collect,
                refresh=args.refresh,
            )
    except (SourceError, ValueError) as error:
        parser.error(str(error))
    print(
        "snapshot",
        f"votacoes={stats['votes']}",
        f"linhas={stats['voteRows']}",
        f"secretas={stats['secretVotes']}",
        f"bytes={stats['snapshotBytes']}",
        *([f"anosParciais={stats['partialYears']}", f"anosAusentes={stats['missingYears']}"] if args.mandate else []),
        f"presenca={snapshot['presenca']['status']}",
        f"saida={destination or DEFAULT_OUTPUT}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
