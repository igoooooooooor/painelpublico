#!/usr/bin/env python3
"""Import a documented DadosJusBr monthly judicial remuneration export.

DadosJusBr gathers and normalizes remuneration rows published by justice
institutions. This importer requests the documented CSV download endpoint,
keeps only its ``base`` remuneration category, and writes normalized records
as JSON Lines inside gzip. It does not claim nationwide court-workforce
coverage: the source is a third-party collection and its per-month coverage
varies by institution.

Usage:
  python3 ingest/judiciary.py
  python3 ingest/judiciary.py --year 2026 --month 8
  python3 ingest/judiciary.py --csv /path/to/month.csv --organizations-json /path/to/orgs.json
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import sqlite3
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "imports" / "judiciary.jsonl.gz"
API_ORGANIZATIONS = "https://api.dadosjusbr.org/v2/orgaos"
API_DOWNLOAD = "https://api.dadosjusbr.org/uiapi/v2/download"
API_SEARCH = "https://api.dadosjusbr.org/uiapi/v2/pesquisar"
JUDICIAL_JURISDICTIONS = {
    "Estadual",
    "Trabalho",
    "Eleitoral",
    "Federal",
    "Superior",
    "Militar",
    "Conselho",
}
ROLE_NAMES = ("magistrado", "servidor")
MISSING_AUTHORITY_NAME = "Nome não informado pela fonte"
NAME_REPAIR_NOTE_PREFIX = "Nomes vazios ou iniciados por `=` normalizados:"

# Explicitly verified STF overlaps with the official roster-only adapter.
# Keep this narrow: other authority names remain source-specific.
STF_AUTHORITY_ID_ALIASES = {
    "dadosjusbr:stf:4dbfcec3db2de1d123ded23223f652556484fa7f7b5f17fb76626aa516265f1d": "stf:alexandre-de-moraes",
    "dadosjusbr:stf:6ec7ce8ee5f1ea62e3e6a3b248fae93a32325c0928791741503ae5276fb2ab5f": "stf:luiz-fux",
}


def normalized(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", (value or "").strip().casefold())
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).split())


def clean_public_text(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or normalized(text) in {"-", "--", "nao informado", "nao informada"}:
        return None
    return text


def normalize_authority_name(value: str | None) -> tuple[str, bool]:
    """Replace blank and spreadsheet-formula values without changing identity input."""
    text = clean_public_text(value)
    if text is None or text.lstrip().startswith("="):
        return MISSING_AUTHORITY_NAME, True
    return text, False


def name_repair_note(count: int) -> str:
    return (
        f"{NAME_REPAIR_NOTE_PREFIX} {count} autoridade(s) para `{MISSING_AUTHORITY_NAME}`; "
        "IDs e remunerações preservados."
    )


def is_invalid_authority_name(value: object) -> bool:
    return not isinstance(value, str) or not value.strip() or value.lstrip().startswith("=")


def parse_money(value: str | None) -> Decimal | None:
    if value is None:
        return None
    raw = value.strip().replace("R$", "").replace("\xa0", "").strip()
    if not raw or raw in {"-", "--", "NA"}:
        return None
    raw = raw.replace(".", "").replace(",", ".")
    try:
        return Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def infer_role(position: str | None) -> str:
    title = normalized(position)
    if re.search(r"\b(juiz|juiza|desembargador|desembargadora|ministro|ministra|magistrado|magistrada)\b", title):
        return "magistrado"
    return "servidor"


def source_professional_id(org_code: str, registration: str | None, name: str, position: str, lotacao: str) -> str:
    """Create a stable, source-prefixed key without exporting raw matrícula."""
    registration = (registration or "").strip()
    if registration:
        identity = "matricula\0" + registration
    else:
        # Most judiciary rows do not publish a matrícula in this export. The
        # public-text fallback is agency-scoped and may change if cargo/lotação
        # changes; the source has no cross-month identifier for those rows.
        identity = "texto\0" + "\0".join(map(normalized, (name, position, lotacao)))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"dadosjusbr:{org_code}:{digest}"


def create_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=FILE")
    conn.execute(
        "CREATE TABLE payroll ("
        "authority_id TEXT PRIMARY KEY, org_code TEXT NOT NULL, name TEXT NOT NULL, position TEXT, "
        "institution TEXT NOT NULL, uf TEXT, sphere TEXT NOT NULL, role TEXT NOT NULL, lotacao TEXT, "
        "amount TEXT, source_rows INTEGER NOT NULL, name_replaced INTEGER NOT NULL)"
    )
    return conn


def write_record(out: TextIO, record_type: str, data: dict) -> None:
    out.write(json.dumps({"type": record_type, "data": data}, ensure_ascii=False, separators=(",", ":")))
    out.write("\n")


def download_url(year: int, month: int) -> str:
    query = urllib.parse.urlencode({"anos": str(year), "meses": str(month), "categorias": "base"})
    return f"{API_DOWNLOAD}?{query}"


def search_url(year: int, month: int) -> str:
    query = urllib.parse.urlencode({"anos": str(year), "meses": str(month), "categorias": "base"})
    return f"{API_SEARCH}?{query}"


def fetch_organizations(path: Path | None) -> dict[str, dict]:
    if path is not None:
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        request = urllib.request.Request(API_ORGANIZATIONS, headers={"User-Agent": "quanto-custa-public-data-importer/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = json.loads(response.read().decode("utf-8"))
    if not isinstance(raw, list):
        raise ValueError("DadosJusBr organization response is not a list")
    organizations = {}
    for record in raw:
        if not isinstance(record, dict) or not record.get("id_orgao"):
            continue
        organizations[str(record["id_orgao"]).casefold()] = record
    if not organizations:
        raise ValueError("DadosJusBr organization response has no usable records")
    return organizations


def fetch_expected_rows(year: int, month: int, path: Path | None) -> int:
    if path is not None:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    else:
        request = urllib.request.Request(search_url(year, month), headers={"User-Agent": "quanto-custa-public-data-importer/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            metadata = json.loads(response.read().decode("utf-8"))
    if not metadata.get("download_available") or metadata.get("num_rows_if_available") is None:
        raise ValueError("DadosJusBr reports that a complete CSV download is unavailable for this period/filter")
    expected_rows = int(metadata["num_rows_if_available"])
    if expected_rows < 0 or expected_rows > int(metadata.get("download_limit") or 0):
        raise ValueError("DadosJusBr search reports a row count above its available download limit")
    return expected_rows


def import_rows(
    reader: csv.DictReader,
    organizations: dict[str, dict],
    year: int,
    month: int,
    conn: sqlite3.Connection,
    expected_rows: int,
) -> dict:
    expected_headers = {
        "orgao", "mes", "ano", "matricula", "nome", "cargo", "lotacao",
        "categoria_contracheque", "detalhamento_contracheque", "valor",
    }
    headers = {str(header or "").strip().lstrip("\ufeff").casefold() for header in (reader.fieldnames or [])}
    if not expected_headers.issubset(headers):
        raise ValueError(f"DadosJusBr CSV is missing expected fields: {sorted(expected_headers - headers)}")

    stats = {
        "downloadRows": 0,
        "judicialBaseRows": 0,
        "pensionistaRows": 0,
        "rowsWithoutAmount": 0,
        "rowsWithoutRegistration": 0,
        "invalidNameRows": 0,
        "matchedComponents": 0,
        "authorities": 0,
        "expenses": 0,
        "zeroExpenses": 0,
        "judicialOrganizations": 0,
        "organizationsWithRows": 0,
        "roleCounts": {},
    }
    observed_organizations: set[str] = set()

    for row in reader:
        stats["downloadRows"] += 1
        org_code = (row.get("orgao") or "").strip().casefold()
        org = organizations.get(org_code)
        if org is None or org.get("jurisdicao") not in JUDICIAL_JURISDICTIONS:
            continue
        if (row.get("categoria_contracheque") or "").strip().casefold() != "base":
            continue
        try:
            row_year = int(row.get("ano") or year)
            row_month = int(row.get("mes") or month)
        except ValueError:
            continue
        if (row_year, row_month) != (year, month):
            raise ValueError(f"CSV includes an unexpected period {row_year:04d}-{row_month:02d}")

        source_name = clean_public_text(row.get("nome"))
        name, name_replaced = normalize_authority_name(row.get("nome"))
        position = clean_public_text(row.get("cargo"))
        lotacao = clean_public_text(row.get("lotacao"))
        if "pensionista" in normalized(position):
            stats["pensionistaRows"] += 1
            continue

        stats["judicialBaseRows"] += 1
        if name_replaced:
            stats["invalidNameRows"] += 1
        observed_organizations.add(org_code)
        registration = row.get("matricula")
        if not (registration or "").strip():
            stats["rowsWithoutRegistration"] += 1
        # Derive IDs from the exact source name (or empty text) before public
        # display normalization so an invalid-name repair never changes IDs.
        authority_id = source_professional_id(org_code, registration, source_name or "", position or "", lotacao or "")
        role = infer_role(position)
        institution = clean_public_text(org.get("nome")) or org_code.upper()
        uf = clean_public_text(org.get("uf"))
        if uf and not re.fullmatch(r"[A-Za-z]{2}", uf):
            uf = None
        sphere = "estadual" if org.get("jurisdicao") == "Estadual" else "federal"
        amount = parse_money(row.get("valor"))
        if amount is None:
            stats["rowsWithoutAmount"] += 1

        found = conn.execute(
            "SELECT amount, source_rows, name, name_replaced FROM payroll WHERE authority_id=?",
            (authority_id,),
        ).fetchone()
        if found is None:
            conn.execute(
                "INSERT INTO payroll VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    authority_id, org_code, name, position, institution, uf.upper() if uf else None,
                    sphere, role, lotacao, str(amount) if amount is not None else None, 1, int(name_replaced),
                ),
            )
        else:
            old_amount, source_rows, old_name, old_name_replaced = found
            if old_name_replaced and not name_replaced:
                stored_name = source_name
                stored_name_replaced = 0
            else:
                stored_name = old_name
                stored_name_replaced = old_name_replaced
            if amount is not None:
                old_total = Decimal(old_amount) if old_amount is not None else Decimal("0.00")
                new_total = old_total + amount
            else:
                new_total = Decimal(old_amount) if old_amount is not None else None
            conn.execute(
                "UPDATE payroll SET name=?, name_replaced=?, amount=?, source_rows=? WHERE authority_id=?",
                (stored_name, stored_name_replaced, str(new_total) if new_total is not None else None, source_rows + 1, authority_id),
            )
        stats["matchedComponents"] += 1

    conn.commit()
    if stats["downloadRows"] != expected_rows:
        raise ValueError(
            f"Downloaded CSV has {stats['downloadRows']} rows but documented search endpoint reports {expected_rows}"
        )
    stats["expectedDownloadRows"] = expected_rows
    stats["organizationsWithRows"] = len(observed_organizations)
    stats["judicialOrganizations"] = sum(
        1 for org in organizations.values() if org.get("jurisdicao") in JUDICIAL_JURISDICTIONS
    )
    stats["authorities"] = conn.execute("SELECT COUNT(*) FROM payroll").fetchone()[0]
    stats["invalidNameAuthorities"] = conn.execute(
        "SELECT COUNT(*) FROM payroll WHERE name_replaced=1"
    ).fetchone()[0]
    stats["expenses"] = conn.execute("SELECT COUNT(*) FROM payroll WHERE amount IS NOT NULL").fetchone()[0]
    stats["zeroExpenses"] = conn.execute("SELECT COUNT(*) FROM payroll WHERE amount='0.00'").fetchone()[0]
    stats["multiComponentAuthorities"] = conn.execute("SELECT COUNT(*) FROM payroll WHERE source_rows>1").fetchone()[0]
    stats["aggregatedComponents"] = stats["matchedComponents"] - stats["authorities"]
    stats["roleCounts"] = {
        role: conn.execute("SELECT COUNT(*) FROM payroll WHERE role=?", (role,)).fetchone()[0]
        for role in ROLE_NAMES
    }
    return stats


def source_record(year: int, month: int, stats: dict, source_url: str, fetched_at: str) -> dict:
    period = f"{year:04d}-{month:02d}"
    return {
        "id": f"dadosjusbr-judiciary-{year:04d}{month:02d}",
        "label": "DadosJusBr — remuneração de órgãos do Judiciário (coleta dos tribunais)",
        "url": source_url,
        "scope": (
            f"Linhas de remuneração da categoria base do mês {period} para órgãos que o catálogo DadosJusBr classifica "
            "nas jurisdições judiciais: estadual, trabalho, eleitoral, federal, superior, militar e conselhos."
        ),
        "period": period,
        "status": "partial",
        "detail": (
            f"DadosJusBr é uma coleta de terceiro que organiza folhas publicadas pelos próprios órgãos, não uma base oficial "
            f"do CNJ. O endpoint documentado de CSV retornou {stats['downloadRows']} linhas no período, igual à contagem "
            f"{stats['expectedDownloadRows']} informada pelo endpoint documentado de pesquisa, com download disponível; "
            f"após filtrar os "
            f"órgãos judiciais, remover cargos explicitamente rotulados como pensionista e agregar linhas da categoria base "
            f"por membro/órgão, foram importadas {stats['expenses']} remunerações de {stats['authorities']} identificadores "
            f"derivados em {stats['organizationsWithRows']} órgãos com dados, de {stats['judicialOrganizations']} órgãos "
            f"judiciais catalogados. Há {stats['roleCounts'].get('magistrado', 0)} magistrados e "
            f"{stats['roleCounts'].get('servidor', 0)} servidores; {stats['zeroExpenses']} valores zero explícitos foram "
            f"mantidos. Foram somadas {stats['aggregatedComponents']} linhas-base adicionais em "
            f"{stats['multiComponentAuthorities']} registros com mais de uma linha-base. A exportação não fornece matrícula para {stats['rowsWithoutRegistration']} das "
            f"{stats['judicialBaseRows']} linhas judiciais elegíveis; nesses casos o ID estável neste registro é um SHA-256 "
            "derivado de órgão, nome, cargo e lotação publicados, então pode mudar se esses campos mudarem e não permite "
            "ligação segura entre órgãos. Se duas pessoas compartilham os mesmos campos publicados dentro de um órgão, o "
            "fallback não consegue distingui-las e pode mesclá-las. Matrículas que existem são usadas apenas como entrada "
            "do hash e não são exportadas. "
            "Quando várias rubricas base têm o mesmo ID derivado de membro/órgão no mês, os valores são somados em um pagamento; "
            "a categoria importada é exatamente `base`. Benefícios/outros pagamentos (`outras`) e descontos não são "
            "somados; este valor não equivale à remuneração bruta total ou ao custo total do vínculo. Linhas sem valor numérico "
            "não geram pagamento, zeros explícitos são mantidos. Órgãos do Ministério Público são excluídos por serem uma "
            "instituição separada, assim como pensionistas; os coletores e dados disponíveis variam por órgão e mês, portanto "
            "este recorte não representa todos os tribunais nem toda a força de trabalho do Judiciário. "
            f"{name_repair_note(stats['invalidNameAuthorities'])}"
        ),
        "fetchedAt": fetched_at,
    }


def write_jsonl_gzip(conn: sqlite3.Connection, output: Path, year: int, month: int, stats: dict, source_url: str) -> None:
    fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    source_id = f"dadosjusbr-judiciary-{year:04d}{month:02d}"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    try:
        with gzip.open(temporary_output, "wt", encoding="utf-8", newline="", compresslevel=6) as out:
            write_record(out, "source", source_record(year, month, stats, source_url, fetched_at))
            for row in conn.execute(
                "SELECT authority_id, name, role, position, institution, uf, sphere, lotacao "
                "FROM payroll ORDER BY org_code, authority_id"
            ):
                authority_id, name, role, position, institution, uf, sphere, lotacao = row
                authority_id = STF_AUTHORITY_ID_ALIASES.get(authority_id, authority_id)
                authority = {
                    "id": authority_id,
                    "name": name,
                    "role": role,
                    "branch": "judiciario",
                    "sphere": sphere,
                    "institution": institution,
                    "uf": uf,
                    "party": None,
                    "sourceId": source_id,
                    "sourceUrl": source_url,
                    "position": position,
                    "employmentStatus": None,
                    "lotacao": lotacao,
                }
                write_record(out, "authority", authority)

            for row in conn.execute(
                "SELECT authority_id, org_code, amount, source_rows FROM payroll "
                "WHERE amount IS NOT NULL ORDER BY org_code, authority_id"
            ):
                authority_id, org_code, amount, source_rows = row
                linked_authority_id = STF_AUTHORITY_ID_ALIASES.get(authority_id, authority_id)
                expense = {
                    "id": f"{source_id}:{org_code}:{authority_id.rsplit(':', 1)[-1]}",
                    "authorityId": linked_authority_id,
                    "sourceId": source_id,
                    "date": None,
                    "year": year,
                    "month": month,
                    "category": "Remuneração-base (DadosJusBr: categoria base)",
                    "amount": float(Decimal(amount).quantize(Decimal("0.01"))),
                    "documentId": f"{year:04d}-{month:02d}:{org_code}:categoria-base:{authority_id.rsplit(':', 1)[-1]}",
                    "documentUrl": source_url,
                    "supplier": None,
                    "kind": "remuneracao",
                }
                write_record(out, "expense", expense)
    except Exception:
        temporary_output.unlink(missing_ok=True)
        raise
    temporary_output.replace(output)


def remap_existing_jsonl(input_path: Path, output_path: Path) -> dict[str, int]:
    """Apply explicit authority aliases and source-quality fixes without downloading."""
    invalid_names = 0
    existing_placeholders = 0
    with gzip.open(input_path, "rt", encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if record.get("type") != "authority" or not isinstance(record.get("data"), dict):
                continue
            name = record["data"].get("name")
            if is_invalid_authority_name(name):
                invalid_names += 1
            elif name == MISSING_AUTHORITY_NAME:
                existing_placeholders += 1

    normalized_name_count = invalid_names + existing_placeholders
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_suffix(output_path.suffix + ".tmp")
    stats = {"authorityAliases": 0, "expenseAliases": 0, "namesNormalized": 0, "datesCleared": 0}
    try:
        with gzip.open(input_path, "rt", encoding="utf-8") as source:
            with gzip.open(temporary_output, "wt", encoding="utf-8", newline="", compresslevel=6) as out:
                for line in source:
                    record = json.loads(line)
                    record_type = record.get("type")
                    data = record.get("data")
                    if not isinstance(data, dict):
                        raise ValueError("Malformed JSONL record: missing data object")
                    if record_type == "source" and data.get("id", "").startswith("dadosjusbr-judiciary-"):
                        detail = data.get("detail") or ""
                        if NAME_REPAIR_NOTE_PREFIX in detail:
                            detail = detail.split(NAME_REPAIR_NOTE_PREFIX, 1)[0].rstrip()
                        data["detail"] = f"{detail} {name_repair_note(normalized_name_count)}".strip()
                    elif record_type == "authority":
                        authority_id = data.get("id")
                        if authority_id in STF_AUTHORITY_ID_ALIASES:
                            data["id"] = STF_AUTHORITY_ID_ALIASES[authority_id]
                            stats["authorityAliases"] += 1
                        if is_invalid_authority_name(data.get("name")):
                            data["name"] = MISSING_AUTHORITY_NAME
                            stats["namesNormalized"] += 1
                    elif record_type == "expense":
                        authority_id = data.get("authorityId")
                        if authority_id in STF_AUTHORITY_ID_ALIASES:
                            data["authorityId"] = STF_AUTHORITY_ID_ALIASES[authority_id]
                            stats["expenseAliases"] += 1
                        if data.get("kind") == "remuneracao" and data.get("date") is not None:
                            data["date"] = None
                            stats["datesCleared"] += 1
                    out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                    out.write("\n")
    except Exception:
        temporary_output.unlink(missing_ok=True)
        raise
    temporary_output.replace(output_path)
    return stats


def read_csv(path: Path | None):
    if path is not None:
        binary = path.open("rb")
        return io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
    return None


def run(
    year: int,
    month: int,
    output: Path,
    csv_path: Path | None,
    organizations_path: Path | None,
    search_path: Path | None,
) -> dict:
    organizations = fetch_organizations(organizations_path)
    expected_rows = fetch_expected_rows(year, month, search_path)
    source_url = download_url(year, month)
    with tempfile.TemporaryDirectory(prefix="quanto-dadosjusbr-") as temporary_directory:
        conn = create_database(Path(temporary_directory) / "judicial-remuneration.sqlite")
        try:
            input_text = read_csv(csv_path)
            if input_text is not None:
                try:
                    stats = import_rows(csv.DictReader(input_text), organizations, year, month, conn, expected_rows)
                finally:
                    input_text.close()
            else:
                request = urllib.request.Request(source_url, headers={"User-Agent": "quanto-custa-public-data-importer/1.0"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    with io.TextIOWrapper(response, encoding="utf-8-sig", newline="") as text:
                        stats = import_rows(csv.DictReader(text), organizations, year, month, conn, expected_rows)
            write_jsonl_gzip(conn, output, year, month, stats, source_url)
            return stats
        finally:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026, help="DadosJusBr reference year (default: 2026)")
    parser.add_argument("--month", type=int, default=8, help="DadosJusBr reference month 1-12 (default: 8)")
    parser.add_argument("--csv", type=Path, help="Use an existing documented DadosJusBr CSV export")
    parser.add_argument("--organizations-json", type=Path, help="Use a saved /v2/orgaos response")
    parser.add_argument("--search-json", type=Path, help="Use a saved /uiapi/v2/pesquisar response for row-count verification")
    parser.add_argument("--remap-existing", type=Path, help="Apply explicit ID aliases and quality fixes to an existing JSONL.GZ")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSONL.GZ path")
    args = parser.parse_args()
    if args.remap_existing is not None:
        try:
            stats = remap_existing_jsonl(args.remap_existing, args.output)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"Could not remap existing DadosJusBr JSONL: {exc}", file=sys.stderr)
            return 2
        print(f"Updated existing JSONL.GZ without downloading: {args.output}")
        print(
            f"Fixed {stats['namesNormalized']} authority names; cleared {stats['datesCleared']} monthly dates; "
            f"updated {stats['authorityAliases']} authority aliases and {stats['expenseAliases']} expense links."
        )
        return 0
    if args.year < 2018 or args.month not in range(1, 13):
        parser.error("--year must be 2018 or later and --month must be between 1 and 12")

    try:
        stats = run(args.year, args.month, args.output, args.csv, args.organizations_json, args.search_json)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, csv.Error, sqlite3.Error, ValueError) as exc:
        print(f"Could not import DadosJusBr judicial remuneration: {exc}", file=sys.stderr)
        print("The documented public API is https://api.dadosjusbr.org/swagger/doc.json", file=sys.stderr)
        return 2

    print(f"Wrote streaming gzip JSONL: {args.output}")
    print(
        f"DadosJusBr {args.year:04d}-{args.month:02d}: {stats['downloadRows']} downloaded rows; "
        f"{stats['judicialBaseRows']} eligible base rows across {stats['organizationsWithRows']} judicial bodies; "
        f"{stats['authorities']} authorities and {stats['expenses']} aggregated salary records "
        f"({stats['zeroExpenses']} explicit zeros)."
    )
    print(f"Roles: {stats['roleCounts']}; excluded explicitly labeled pensionista rows: {stats['pensionistaRows']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
