#!/usr/bin/env python3
"""Passagens aéreas emitidas pela agência da Câmara (SIGEPA) que o arquivo anual da CEAP deixou de trazer.

Até jul/2025 o arquivo aberto (``cotas/Ano-AAAA.csv.zip``) trazia as linhas "PASSAGEM AÉREA - SIGEPA"
(subcota 998); de ago/2025 em diante só aparecem estornos avulsos. A página analítica da cota de cada
deputado(a) continua listando os bilhetes do mês: companhia, CNPJ, data de emissão, número, valor e
estornos, com o mês de competência no link de detalhe. É o mesmo valor que a página do(a) deputado(a)
soma no gráfico de gastos.

Este coletor lê só esses campos, uma página por pessoa e ano, a partir de ago/2025. A página de detalhe
(passageiro e trecho) não é consultada. A soma das linhas precisa fechar com o total publicado na
própria página; senão a pessoa fica sem os bilhetes daquele ano, como dado ausente, nunca como zero.
Uma falha preserva o que a coleta anterior obteve para a pessoa.

``ingest/legislative.py`` coleta e aplica estes bilhetes ao importar o arquivo anual
(``legislative.load_chamber_expenses``). Para reaplicar sem rede sobre um documento já gerado:

    python3 -m ingest.chamber_sigepa --apply data/imports/legislative.json --year 2026
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RAW_DIR = ROOT / "data" / "raw" / "legislative"
# Primeiro mês sem as linhas SIGEPA no arquivo aberto (conferido em 19/10/2026 nos arquivos de 2025 e 2026).
SIGEPA_START = (2025, 8)
ANALYTIC_URL = ("https://www.camara.leg.br/cota-parlamentar/analitico?nuDeputadoId={deputy}"
                "&dataInicio={start_month}/{start_year}&dataFim={end_month}/{end_year}&despesa=998"
                "&nomeHospede=&nomePassageiro=&nomeFornecedor=&cnpjFornecedor=&numDocumento=&sguf=")
# Resumo por tipo de despesa no mesmo período. A página analítica dá erro 500 para alguns IDs, em qualquer tipo
# de despesa (ex.: Eunício Oliveira, 19/10/2026); o resumo sem a linha SIGEPA comprova que não há bilhetes.
SUMMARY_URL = ("https://www.camara.leg.br/cota-parlamentar/sumarizado?nuDeputadoId={deputy}"
               "&dataInicio={start_month}/{start_year}&dataFim={end_month}/{end_year}&despesa="
               "&nomeHospede=&nomePassageiro=&nomeFornecedor=&cnpjFornecedor=&numDocumento=&sguf="
               "&filtroNivel1=1&filtroNivel2=2&filtroNivel3=3")
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
SCHEMA_VERSION = 1


def cache_path(raw_dir: Path, year: int) -> Path:
    return raw_dir / f"camara-sigepa-{year}.json"


def month_range(year: int, today: dt.date) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """(início, fim) do ano coberto pelo coletor, ou None antes de ago/2025 ou no futuro."""
    start = max((year, 1), SIGEPA_START)
    end = (year, 12) if year < today.year else (year, today.month)
    return (start, end) if start <= end else None


def analytic_url(deputy: str, start: tuple[int, int], end: tuple[int, int]) -> str:
    return ANALYTIC_URL.format(deputy=urllib.parse.quote(str(deputy)), start_year=start[0], start_month=start[1],
                               end_year=end[0], end_month=end[1])


def summary_url(deputy: str, start: tuple[int, int], end: tuple[int, int]) -> str:
    return SUMMARY_URL.format(deputy=urllib.parse.quote(str(deputy)), start_year=start[0], start_month=start[1],
                              end_year=end[0], end_month=end[1])


def summary_has_no_tickets(content: str) -> bool:
    """True só quando o resumo do período veio completo (com total) e não tem a linha de passagens SIGEPA."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content))
    return ("Resultado da pesquisa" in text and re.search(r"\bTotal R\$", text) is not None
            and "SIGEPA" not in text.upper())


def money(text: str) -> Decimal | None:
    """'R$1.234,56' → 1234.56; '(R$67,00)' → -67.00; vazio → None."""
    value = re.sub(r"\s+", "", text or "").replace("R$", "")
    if not value:
        return None
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("()").replace(".", "").replace(",", ".")
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"Valor inválido na página analítica: {text!r}") from error
    return -amount if negative else amount


class _AnalyticTable(HTMLParser):
    """Linhas da tabela analítica: texto de cada célula, link de detalhe e o total da página."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.cell_id: str | None = None
        self.link: str | None = None
        self.rows: list[tuple[list[str], str | None]] = []
        self.total: str | None = None
        self.has_total = False
        self.has_result = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "tbody":
            self.in_body = True
        elif self.in_body and tag == "tr":
            self.row, self.link = [], None
        elif self.row is not None and tag == "td":
            self.cell, self.cell_id = [], values.get("id")
        elif self.row is not None and tag == "a" and values.get("href"):
            self.link = values["href"]

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.row is not None and self.cell is not None:
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            if self.cell_id == "totalFinalAnalitico":
                self.has_total, self.total = True, text
            self.row.append(text)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row and self.row[0] != "Total":
                self.rows.append((self.row, self.link))
            self.row = None
        elif tag == "tbody":
            self.in_body = False

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)
        if "Resultado da pesquisa" in data:
            self.has_result = True


def parse_analytic(content: str) -> list[dict[str, Any]]:
    """Bilhetes da página analítica. Página fora do formato esperado ou soma diferente do total → erro."""
    table = _AnalyticTable()
    table.feed(content)
    if not table.has_result or not table.has_total:
        raise ValueError("Página analítica sem o resultado e o total esperados")
    rows: list[dict[str, Any]] = []
    for cells, link in table.rows:
        if len(cells) < 7 or not link:
            raise ValueError("Linha da página analítica fora do formato esperado")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(re.sub(r"\s+", "", link)).query)
        year, month = query.get("numAno", [""])[0], query.get("numMes", [""])[0]
        if not (year.isdigit() and month.isdigit() and 1 <= int(month) <= 12):
            raise ValueError("Linha da página analítica sem mês de competência")
        amount = money(cells[6])
        if amount is None:
            raise ValueError("Linha da página analítica sem valor de reembolso")
        date = None
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", cells[2]):
            date = dt.datetime.strptime(cells[2], "%d/%m/%Y").date().isoformat()
        rows.append({
            "year": int(year), "month": int(month), "date": date,
            "supplier": cells[0] or None, "taxId": cells[1] or None, "document": cells[3] or None,
            "amount": format(amount, "f"),
            "fiscalId": (query.get("idDocumentoFiscal", [""])[0] or None),
        })
    total = money(table.total or "")
    observed = sum((Decimal(row["amount"]) for row in rows), Decimal("0"))
    if (total if total is not None else Decimal("0")) != observed:
        raise ValueError(f"Soma das linhas ({observed}) diferente do total da página ({total})")
    return rows


def deputies_in_archive(archive: Path, year: int) -> dict[str, str]:
    """nuDeputadoId → authorityId de quem tem alguma linha no arquivo anual (mesma regra do importador)."""
    from ingest.legislative import chamber_authority_id

    people: dict[str, str] = {}
    with zipfile.ZipFile(archive) as bundle:
        for member in (name for name in bundle.namelist() if name.lower().endswith(".csv")):
            with bundle.open(member) as binary:
                reader = csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline=""), delimiter=";")
                for row in reader:
                    deputy = str(row.get("nuDeputadoId") or "").strip()
                    if deputy and str(row.get("numAno") or year).strip() == str(year):
                        people.setdefault(deputy, chamber_authority_id(row))
    return people


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schemaVersion") == SCHEMA_VERSION else None


def collect(year: int, archive: Path, raw_dir: Path = RAW_DIR, *, today: dt.date | None = None,
            fetch: Callable[[str], str] = fetch_text, attempts: int = 2, delay: float = 1.0,
            budget_seconds: float | None = None, stop_after_failures: int = 8,
            clock: Callable[[], float] = time.monotonic,
            progress: Callable[[str], None] | None = None) -> dict[str, Any] | None:
    """Atualiza ``camara-sigepa-{ano}.json``; devolve o documento gravado, ou None fora do período.

    Um pedido por vez, com pausa (``delay``), para não sobrecarregar o portal: numa coleta com 4 pedidos
    paralelos, em 19/10/2026, a Câmara deixou de responder a este endereço. Quem está há mais tempo sem
    consulta vai primeiro; com ``budget_seconds``, a coleta para no prazo e o restante fica com a consulta
    anterior (ou sem bilhetes, como dado ausente). Falhas seguidas indicam bloqueio: a coleta para e grava
    o que já obteve.
    """
    today = today or dt.datetime.now(dt.timezone.utc).date()
    span = month_range(year, today)
    if span is None:
        return None
    start, end = span
    people = deputies_in_archive(archive, year)
    previous = load(cache_path(raw_dir, year)) or {}
    previous_people = previous.get("deputies", {}) if previous.get("start") == "%d-%02d" % start else {}
    results: dict[str, dict[str, Any]] = {}
    for deputy, authority in people.items():
        kept = previous_people.get(deputy)
        results[deputy] = dict(kept) if kept and kept.get("status") == "imported" else \
            {"authorityId": authority, "status": "pending", "rows": []}

    def staleness(deputy: str) -> tuple[int, str]:
        item = results[deputy]
        # Nunca consultados primeiro; depois os de consulta mais antiga, e os que cobrem menos meses.
        return (item.get("status") == "imported", f"{item.get('end', '')}|{item.get('fetchedAt', '')}")

    began, failures_in_row, consulted = clock(), 0, 0
    destination = cache_path(raw_dir, year)

    def document() -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "year": year,
            "start": "%d-%02d" % start,
            "end": "%d-%02d" % end,
            "collectedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "url": ANALYTIC_URL,
            "label": "Câmara dos Deputados: passagens aéreas emitidas pela agência (SIGEPA), página analítica da cota",
            "detail": ("Bilhetes de \"PASSAGEM AÉREA - SIGEPA\" listados na página analítica da cota de cada deputado(a), "
                       "que o arquivo anual deixou de trazer a partir de ago/2025. Só companhia, CNPJ, data, número, valor "
                       "e mês de competência; passageiro e trecho não são coletados."),
            "requested": len(people),
            "consultedThisRun": consulted,
            "failed": sorted(deputy for deputy, item in results.items() if item["status"] != "imported"),
            "deputies": results,
        }

    def save() -> dict[str, Any]:
        value = document()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(destination)
        return value

    for deputy in sorted(results, key=staleness):
        if budget_seconds is not None and clock() - began > budget_seconds:
            break
        if failures_in_row >= stop_after_failures:
            break
        url, error = analytic_url(deputy, start, end), None
        for attempt in range(attempts):
            try:
                rows = parse_analytic(fetch(url))
            except Exception as failure:  # noqa: BLE001 - registra e tenta de novo
                error = f"{type(failure).__name__}: {failure}"
                if attempt + 1 < attempts:
                    time.sleep(delay * (attempt + 2))
                continue
            results[deputy] = {"authorityId": people[deputy], "status": "imported",
                               "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                               "end": "%d-%02d" % end, "rows": rows}
            error = None
            break
        if error is not None:
            # Analítica indisponível para esta pessoa: o resumo do período pode comprovar que não há bilhetes.
            try:
                if summary_has_no_tickets(fetch(summary_url(deputy, start, end))):
                    results[deputy] = {"authorityId": people[deputy], "status": "imported",
                                       "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                       "end": "%d-%02d" % end, "rows": [],
                                       "evidence": "resumo por tipo sem passagens SIGEPA; página analítica indisponível"}
                    error = None
            except Exception:  # noqa: BLE001 - mantém o erro da analítica
                pass
        consulted += 1
        if progress:
            progress(f"{consulted} {deputy} {'ok' if error is None else error}")
        if error is None:
            failures_in_row = 0
        else:
            failures_in_row += 1
            results[deputy] = {**results[deputy], "lastError": error}
        if consulted % 50 == 0:
            save()
        time.sleep(delay)
    return save()


def apply_to_document(path: Path, year: int, raw_dir: Path = RAW_DIR) -> dict[str, Any]:
    """Refaz, sem rede, as notas da Câmara de um documento de ``ingest/legislative.py`` com os bilhetes SIGEPA.

    As linhas da Câmara são relidas do arquivo anual já baixado (``camara-{ano}.csv.zip``), como faria a
    importação; Senado, cadastros e as demais fontes do documento ficam como estão.
    """
    from ingest.legislative import load_chamber_expenses, sanitize_expense_suppliers

    document = json.loads(path.read_text(encoding="utf-8"))
    archive = raw_dir / f"camara-{year}.csv.zip"
    authorities = {item["id"]: item for item in document.get("authorities", [])}
    chamber, stats = load_chamber_expenses(archive, year, authorities, "camara_ceap")
    sanitize_expense_suppliers(chamber)
    others = [row for row in document.get("expenses", []) if row.get("sourceId") != "camara_ceap"]
    document["expenses"] = chamber + others
    document["authorities"] = list(authorities.values())
    for source in document.get("sources", []):
        if source.get("id") == "camara_ceap":
            source["detail"] = re.sub(r" Passagens SIGEPA:.*$", "", source.get("detail") or "") + sigepa_detail(stats)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)
    return stats.get("sigepa") or {}


def sigepa_detail(stats: dict[str, Any]) -> str:
    """Frase para o detalhe da fonte CEAP; vazia quando não há coleta SIGEPA para o ano."""
    sigepa = stats.get("sigepa") or {}
    if not sigepa.get("applied"):
        return ""
    text = (f" Passagens SIGEPA: {sigepa['rowsAdded']} bilhetes e estornos de {sigepa['deputies']} deputados(as) "
            f"({sigepa['start']} a {sigepa['end']}) vêm da página analítica da cota, porque o arquivo anual deixou de "
            f"trazê-los; {sigepa['rowsReplaced']} linhas SIGEPA do arquivo nesses meses foram substituídas pela lista da página.")
    if sigepa.get("failed"):
        text += f" {sigepa['failed']} pessoas ficaram sem a consulta e sem esses bilhetes (dado ausente, não zero)."
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--collect", action="store_true", help="consulta a Câmara e atualiza o cache do ano")
    parser.add_argument("--apply", type=Path, help="documento de ingest/legislative.py a refazer sem rede")
    parser.add_argument("--budget-minutes", type=float, help="tempo máximo da coleta; quem fica de fora mantém a consulta anterior")
    args = parser.parse_args(argv)
    if args.collect:
        budget = args.budget_minutes * 60 if args.budget_minutes else None
        result = collect(args.year, RAW_DIR / f"camara-{args.year}.csv.zip", budget_seconds=budget,
                         progress=lambda line: print(line, file=sys.stderr, flush=True))
        if result is None:
            print(f"{args.year}: fora do período coberto (a partir de {SIGEPA_START[1]:02d}/{SIGEPA_START[0]})")
        else:
            rows = sum(len(item["rows"]) for item in result["deputies"].values())
            print(f"{cache_path(RAW_DIR, args.year)}: {rows} linhas de {result['requested']} pessoas; "
                  f"{len(result['failed'])} sem consulta")
    if args.apply:
        path = args.apply if args.apply.is_absolute() else ROOT / args.apply
        print(json.dumps(apply_to_document(path, args.year), ensure_ascii=False))
    if not args.collect and not args.apply:
        parser.error("use --collect e/ou --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
