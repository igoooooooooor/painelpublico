"""Arrecadação dos impostos estaduais (ICMS, IPVA e ITCD) no ano, pelos RREOs dos 27 estados.

Fonte: Tesouro Nacional — Siconfi, Relatório Resumido da Execução Orçamentária (RREO), Anexo 3
(Receita Corrente Líquida), que traz a receita de cada imposto mês a mês nos últimos 12 meses.
Os valores são a arrecadação de cada estado antes das transferências constitucionais aos
municípios e do Fundeb; conferidos contra o Boletim do Confaz (ICMS de 2025 de SP, MG, RS e BA
com diferença de até 2%; IPVA e ITCMD de SP de 2026 iguais). Transferências recebidas (FPE etc.),
taxas e contribuições ficam fora, para não somar duas vezes o que já está no dado federal.

O snapshot usa o último bimestre em que os 27 estados entregaram o relatório. Estado sem relatório
não vira zero: sem os 27, o bimestre não é usado.

Uso: ``python3 -m ingest.state_tax_revenue [--year 2026] [--period 4]``.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import calendar
import json
from pathlib import Path
import sys
import time
from typing import Callable
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "snapshots" / "state-tax-revenue.json"
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
DOWNLOAD_TIMEOUT = 90
REQUEST_INTERVAL_SECONDS = 1.05

RREO_URL = ("https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?an_exercicio={year}&nr_periodo={period}"
            "&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2003&id_ente={state_id}")
SOURCE_LABEL = "Tesouro Nacional — Siconfi, RREO Anexo 3 dos 26 estados e do Distrito Federal"
SOURCE_URL = "https://www.tesourotransparente.gov.br/ckan/dataset/api-rreo-entes"

# Códigos IBGE dos 26 estados e do DF.
STATE_IDS = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO", 21: "MA", 22: "PI",
    23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA", 31: "MG", 32: "ES",
    33: "RJ", 35: "SP", 41: "PR", 42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF",
}
# Linha do Anexo 3 -> chave do snapshot. A conta "ITCD" é o ITCMD.
TAX_ACCOUNTS = {"ICMS": "icms", "IPVA": "ipva", "ITCD": "itcd"}
MONTHS_PT = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def month_columns(period: int) -> dict[str, int]:
    """Colunas mensais do Anexo 3 que caem no ano do relatório: <MR> é o último mês do bimestre."""
    last_month = period * 2
    columns = {"<MR>": last_month}
    for offset in range(1, last_month):
        columns[f"<MR-{offset}>"] = last_month - offset
    return columns


def state_taxes(items: list[dict], period: int) -> dict[str, dict[int, float]] | None:
    """{imposto: {mês: valor}} de um estado; None quando o relatório não traz as três linhas."""
    columns = month_columns(period)
    found: dict[str, dict[int, float]] = {key: {} for key in TAX_ACCOUNTS.values()}
    for item in items:
        key = TAX_ACCOUNTS.get(item.get("conta"))
        month = columns.get(item.get("coluna"))
        value = item.get("valor")
        if key is None or month is None or not isinstance(value, (int, float)):
            continue
        if item.get("anexo") != "RREO-Anexo 03" or item.get("esfera") not in (None, "E"):
            continue
        found[key][month] = found[key].get(month, 0.0) + float(value)
    if any(len(months) != len(columns) for months in found.values()):
        return None
    return found


def summarize(year: int, period: int, by_state: dict[str, dict[str, dict[int, float]] | None], fetched_at: str) -> dict:
    reported = {uf: taxes for uf, taxes in by_state.items() if taxes is not None}
    missing = sorted(set(STATE_IDS.values()) - set(reported))
    last_month = period * 2
    totals = {key: round(sum(sum(taxes[key].values()) for taxes in reported.values()), 2) for key in TAX_ACCOUNTS.values()}
    monthly = [
        {"mes": month, "valor": round(sum(taxes[key][month] for taxes in reported.values() for key in TAX_ACCOUNTS.values()), 2)}
        for month in range(1, last_month + 1)
    ]
    return {
        "inicio": f"{year}-01-01",
        "ate": date(year, last_month, calendar.monthrange(year, last_month)[1]).isoformat(),
        "acumulado": round(sum(totals.values()), 2),
        "impostos": totals,
        "meses": monthly,
        "bimestre": period,
        "estadosComDado": len(reported),
        "estadosEsperados": len(STATE_IDS),
        "estadosSemDado": missing,
        "fonte": f"{SOURCE_LABEL}: ICMS, IPVA e ITCD de jan a {MONTHS_PT[last_month - 1]}/{year}, antes das transferências aos municípios e do Fundeb.",
        "url": SOURCE_URL,
        "coletadoEm": fetched_at,
    }


def fetch_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        return json.load(response)


def collect(year: int, period: int, fetch: Callable[[str], dict] = fetch_json, pause: float = REQUEST_INTERVAL_SECONDS) -> dict[str, dict | None]:
    by_state: dict[str, dict | None] = {}
    for state_id, uf in STATE_IDS.items():
        payload = fetch(RREO_URL.format(year=year, period=period, state_id=state_id))
        items = payload.get("items") if isinstance(payload, dict) else None
        by_state[uf] = state_taxes(items or [], period)
        if pause:
            time.sleep(pause)
    return by_state


def latest_complete(year: int, start_period: int, fetch: Callable[[str], dict] = fetch_json, pause: float = REQUEST_INTERVAL_SECONDS) -> tuple[int, dict]:
    """Último bimestre do ano com os 27 estados; volta um bimestre por vez."""
    for period in range(start_period, 0, -1):
        by_state = collect(year, period, fetch, pause)
        if all(taxes is not None for taxes in by_state.values()):
            return period, by_state
        print(f"Bimestre {period}/{year}: faltam {sorted(uf for uf, taxes in by_state.items() if taxes is None)}", file=sys.stderr)
    raise SystemExit(f"Nenhum bimestre de {year} tem os 27 estados.")


def main(argv: list[str] | None = None) -> int:
    today = date.today()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--year", type=int, default=today.year)
    parser.add_argument("--period", type=int, choices=range(1, 7), help="bimestre inicial da busca (padrão: o anterior ao mês atual)")
    parser.add_argument("--output", type=Path, default=SNAPSHOT_PATH)
    args = parser.parse_args(argv)
    # O RREO de um bimestre sai até 30 dias depois do fim dele; começa pelo último já vencido.
    start = args.period or (max(1, min(6, (today.month - 2) // 2)) if args.year == today.year else 6)
    period, by_state = latest_complete(args.year, start)
    snapshot = summarize(args.year, period, by_state, datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.output}: {snapshot['estadosComDado']} estados, jan–{period * 2:02d}/{args.year}, R$ {snapshot['acumulado'] / 1e9:,.1f} bi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
