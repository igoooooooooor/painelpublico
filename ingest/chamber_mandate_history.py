#!/usr/bin/env python3
"""Gabinete e presença da Câmara nos anos anteriores do mandato atual (desde fev/2023).

Coleta manual e retomável. Lê só os deputados da lista atual em
``data/imports/legislative.json`` e grava ``data/snapshots/chamber-mandate-history.json``
(gabinete 2023–2025 e presença desde fev/2023, inclusive o ano corrente) e
``data/snapshots/presenca.json``, a presença do mandato usada pelas telas.
Mês sem dado fica ausente, nunca zero.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.chamber_housing import load_roster  # noqa: E402
from ingest.profile_office import load_office  # noqa: E402

MANDATE_START = "2023-02"
DEFAULT_YEARS = (2023, 2024, 2025)
CURRENT_YEAR = 2026
PRESENCE_URL = "https://www.camara.leg.br/deputados/{deputy_id}/presenca-plenario/{year}"
USER_AGENT = "Mozilla/5.0 (PainelPublico)"
DAY_PATTERN = re.compile(
    r'info-data__data-formatada">\s*(\d\d)/(\d\d)/(\d{4}).*?</td>\s*<td[^>]*>.*?</td>\s*'
    r'<td class="info-presenca-dia">\s*(.*?)\s*</td>',
    re.S,
)


def paths(root: Path = ROOT) -> dict[str, Path]:
    raw = root / "data" / "raw" / "mandate-history"
    return {
        "office": raw / "office",
        "presence": raw / "presence",
        "roster": root / "data" / "imports" / "legislative.json",
        "output": root / "data" / "snapshots" / "chamber-mandate-history.json",
        "presence_output": root / "data" / "snapshots" / "presenca.json",
    }


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_presence(content: str, year: int) -> list[list[str]]:
    """Return [[YYYY-MM-DD, status], ...] for the requested year only."""
    days = []
    for day, month, found_year, status in DAY_PATTERN.findall(content):
        if int(found_year) != year:
            continue
        label = html.unescape(re.sub(r"<[^>]+>", "", status)).strip()
        if label:
            days.append([f"{found_year}-{month}-{day}", label])
    return days


def load_presence(deputy_id: str, year: int, cache_dir: Path, collect: bool, refresh: bool) -> dict[str, Any] | None:
    """Read the minimized cache (dates and statuses only) or fetch the official page."""
    cache = cache_dir / f"presence-{deputy_id}-{year}.json"
    previous = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None
    if previous and not (collect and refresh):
        return previous
    if not collect:
        return previous
    url = PRESENCE_URL.format(deputy_id=deputy_id, year=year)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        with urllib.request.urlopen(request, timeout=40) as response:
            content = response.read().decode("utf-8", errors="ignore")
    except OSError as error:
        print(f"presença {deputy_id}/{year}: {type(error).__name__}", file=sys.stderr)
        return previous
    # Página lida sem linhas: fica registrada como "sem registros publicados", não como zero.
    result = {"sourceUrl": url, "fetchedAt": _utc_now(), "days": parse_presence(content, year)}
    _atomic_json(cache, result)
    return result


def presence_months(days: list[list[str]]) -> dict[str, dict[str, int]]:
    months: dict[str, dict[str, int]] = {}
    for date, status in days:
        period = date[:7]
        if period < MANDATE_START:
            continue
        bucket = months.setdefault(period, {"days": 0, "present": 0, "absent": 0, "justified": 0})
        bucket["days"] += 1
        if status == "Presença":
            bucket["present"] += 1
        elif status == "Ausência":
            bucket["absent"] += 1
        else:
            bucket["justified"] += 1
    return months


def presence_reasons(days: list[list[str]]) -> dict[str, int]:
    """Contagem dos motivos de dias sem presença nem ausência simples (ex.: justificativas)."""
    reasons: dict[str, int] = {}
    for date, status in days:
        if date[:7] >= MANDATE_START and status not in ("Presença", "Ausência"):
            reasons[status] = reasons.get(status, 0) + 1
    return reasons


def office_months(office: dict[str, Any], year: int) -> dict[str, float]:
    if office.get("status") == "unavailable":
        return {}
    output = {}
    for month, value in (office.get("months") or {}).items():
        period = f"{year}-{int(month):02d}"
        if period >= MANDATE_START and value is not None:
            output[period] = value
    return output


def build_snapshot(root: Path = ROOT, years=DEFAULT_YEARS, collect=False, refresh=False,
                   limit: int | None = None, workers: int = 4) -> dict[str, Any]:
    where = paths(root)
    roster = load_roster(where["roster"])
    selected = roster[:limit] if limit else roster

    def one(person: dict[str, str]) -> tuple[str, dict[str, Any]]:
        deputy_id = person["id"].removeprefix("camara:")
        entry: dict[str, Any] = {"name": person["name"], "office": {}, "presence": {}, "presenceReasons": {},
                                 "sources": {}}
        in_scope = collect and person in selected
        for year in (*years, CURRENT_YEAR):
            # O gabinete de 2026 já vem da ficha; aqui só os anos anteriores.
            office = (load_office(deputy_id, where["office"], collect=in_scope, refresh=refresh, year=year)
                      if year != CURRENT_YEAR else {})
            entry["office"].update(office_months(office, year) if office else {})
            # O ano corrente muda toda semana: com --collect, a presença dele é sempre consultada de novo.
            presence = load_presence(deputy_id, year, where["presence"], in_scope,
                                     refresh or (in_scope and year == CURRENT_YEAR))
            if presence is not None:
                entry["presence"].update(presence_months(presence["days"]))
                for reason, count in presence_reasons(presence["days"]).items():
                    entry["presenceReasons"][reason] = entry["presenceReasons"].get(reason, 0) + count
            entry["sources"][str(year)] = {
                "office": None if not office else {"status": office.get("status"), "url": office.get("sourceUrl"),
                           "fetchedAt": office.get("fetchedAt"), "updatedAt": office.get("sourceUpdatedAt")},
                "presence": None if presence is None else {
                    "url": presence["sourceUrl"], "fetchedAt": presence["fetchedAt"],
                    "status": "available" if presence["days"] else "no_records",
                },
            }
            if in_scope:
                time.sleep(0.25)
        return person["id"], entry

    with ThreadPoolExecutor(max(1, workers)) as executor:
        profiles = dict(executor.map(one, roster))

    periods = sorted({p for e in profiles.values() for p in (*e["office"], *e["presence"])})
    coverage = {
        period: {
            "office": sum(period in e["office"] for e in profiles.values()),
            "presence": sum(period in e["presence"] for e in profiles.values()),
        }
        for period in periods
    }
    return {
        "generatedAt": _utc_now(),
        "scope": "Câmara, deputados da lista atual, meses do mandato desde 2023-02",
        "years": list(years),
        "rosterCount": len(roster),
        "notes": [
            "Valores da época, sem correção pela inflação.",
            "Mês ausente significa dado não publicado ou não coletado, nunca zero.",
            "Gabinete: total mensal publicado no perfil anual; teto não substitui gasto.",
            "Presença: dias de sessão deliberativa no Plenário, como na página oficial.",
        ],
        "coverage": coverage,
        "profiles": profiles,
    }


def load_metadata(path: Path) -> dict[str, dict[str, Any]]:
    """Partido e UF da lista atual, para as linhas de presença."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {row["id"]: row for row in payload.get("authorities", []) if isinstance(row, dict) and row.get("id")}


def presence_rows(snapshot: dict[str, Any], metadata: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Mesmo formato de ``presenca.json``, somando os dias do mandato, com o período ao lado."""
    rows = []
    for identifier, entry in snapshot["profiles"].items():
        months = entry.get("presence") or {}
        days = sum(month["days"] for month in months.values())
        if not days:
            continue
        info = metadata.get(identifier, {})
        reasons = sorted((entry.get("presenceReasons") or {}).items(), key=lambda item: (-item[1], item[0]))
        rows.append({
            "id": int(identifier.removeprefix("camara:")), "nome": entry["name"],
            "partido": info.get("party"), "uf": info.get("uf"), "dias": days,
            "presente": sum(month["present"] for month in months.values()),
            "falta": sum(month["absent"] for month in months.values()),
            "justificadas": sum(month["justified"] for month in months.values()),
            "motivos": [list(item) for item in reasons[:3]],
            "inicio": min(months), "fim": max(months),
        })
    return sorted(rows, key=lambda row: row["nome"])


def parse_years(value: str) -> tuple[int, ...]:
    try:
        years = tuple(int(part) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("years must be comma-separated integers") from exc
    if not years or any(year < 2023 or year > 2025 for year in years):
        raise argparse.ArgumentTypeError("years must be between 2023 and 2025")
    return years


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true", help="consulta as páginas oficiais que faltam")
    parser.add_argument("--refresh", action="store_true", help="refaz páginas já coletadas; requer --collect")
    parser.add_argument("--years", type=parse_years, default=DEFAULT_YEARS, help="anos (padrão: 2023,2024,2025)")
    parser.add_argument("--limit", type=int, help="limita a coleta aos primeiros N deputados da lista")
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error("--refresh requires --collect")
    try:
        snapshot = build_snapshot(years=args.years, collect=args.collect, refresh=args.refresh, limit=args.limit)
    except (OSError, ValueError) as exc:
        print(f"Snapshot não montado: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    output = paths()["output"]
    _atomic_json(output, snapshot)
    rows = presence_rows(snapshot, load_metadata(paths()["roster"]))
    if rows:
        _atomic_json(paths()["presence_output"], rows)
        print(f"Wrote {paths()['presence_output']}: presença do mandato de {len(rows)} deputados.")
    with_office = sum(bool(e["office"]) for e in snapshot["profiles"].values())
    with_presence = sum(bool(e["presence"]) for e in snapshot["profiles"].values())
    print(f"Wrote {output}: {snapshot['rosterCount']} deputados, {with_office} com gabinete, "
          f"{with_presence} com presença.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
