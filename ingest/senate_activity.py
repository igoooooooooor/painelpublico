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


def votes_url(year: int = YEAR, through: date | None = None) -> str:
    start = date(year, 1, 1)
    cutoff = through or date.today()
    end = min(cutoff, date(year, 12, 31))
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
    payload: Any, year: int = YEAR
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

        secrecy = str(source_row.get("votacaoSecreta") or "").upper()
        if secrecy == "S":
            counts["secret"] += 1
            continue

        description = _text(source_row.get("descricaoVotacao"), 1000)
        normalized_description = unicodedata.normalize("NFD", description or "")
        normalized_description = "".join(
            char for char in normalized_description if unicodedata.category(char) != "Mn"
        ).casefold()
        if "votacao nominal" not in normalized_description:
            counts["unclassified"] += 1
            continue
        if secrecy != "N":
            counts["malformed"] += 1

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
        if identifier in seen:
            counts["duplicate"] += 1
            continue
        seen.add(identifier)

        rows = []
        source_votes = source_row.get("votos")
        if not isinstance(source_votes, list) or not source_votes:
            counts["malformed"] += 1
            continue
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


def _read_cache(path: Path, year: int) -> dict[str, Any] | None:
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
    try:
        items = normalize_votes(raw_rows, year)
    except SourceError:
        return None
    if not items:
        return None
    return {"sourceUrl": source_url, "fetchedAt": fetched_at, "data": raw_rows}


def _fetch_cache(
    year: int,
    request: Callable[[str], tuple[Any, str]] = request_json,
) -> dict[str, Any]:
    source_url = votes_url(year)
    payload, fetched_at = request(source_url)
    items, _counts = _normalized_vote_payload(payload, year)
    if not items:
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
    if not isinstance(snapshot, dict) or snapshot.get("year") != year:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera snapshot local de votações nominais do Senado")
    parser.add_argument("--year", type=int, default=YEAR, help="ano do recorte (somente 2026)")
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
        f"presenca={snapshot['presenca']['status']}",
        f"saida={destination or DEFAULT_OUTPUT}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
