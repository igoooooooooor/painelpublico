#!/usr/bin/env python3
"""Stream official federal executive payroll and STF composition as JSONL.GZ.

The Portal da Transparencia monthly SIAPE ZIP includes CPF and other personal
identifiers. This importer streams the Cadastro and Remuneracao CSVs into a
temporary SQLite database containing only professional fields and the one
chosen gross-pay measure. It emits source, unique-person, and payroll records
as JSON Lines inside gzip; the raw ZIP and temporary database are deleted when
the process exits.

Usage:
  python3 ingest/executive_judicial.py
  python3 ingest/executive_judicial.py --month 202608
  python3 ingest/executive_judicial.py --zip /path/to/202608_Servidores_SIAPE.zip
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import re
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import BinaryIO, TextIO


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "imports" / "executive-judicial.jsonl.gz"
PORTAL_DOWNLOAD = "https://portaldatransparencia.gov.br/download-de-dados/servidores/{month}_Servidores_SIAPE"
PORTAL_DICTIONARY = "https://portaldatransparencia.gov.br/dicionario-de-dados/servidores-remuneracao"
STF_COMPOSITION_URL = "https://portal.stf.jus.br/ostf/"
CNJ_PAY_URL = "https://www.cnj.jus.br/transparencia-cnj/remuneracao-dos-magistrados/"
SIORG_API_URL = "https://api.siorg.economia.gov.br/"
GROSS_PAY_COLUMN = "REMUNERAÇÃO BÁSICA BRUTA (R$)"

# The STF's official composition page listed these ten serving ministers when
# checked on 2026-10-06. The page showed ten occupied places of eleven seats.
# This roster does not imply that STF remuneration was imported.
STF_ROSTER = (
    "Edson Fachin",
    "Gilmar Mendes",
    "Cármen Lúcia",
    "Dias Toffoli",
    "Luiz Fux",
    "Alexandre de Moraes",
    "Nunes Marques",
    "André Mendonça",
    "Cristiano Zanin",
    "Flávio Dino",
)

TITLE_ROLE = {
    "PRESIDENTE DA REPUBLICA": "presidente",
    "VICE-PRESIDENTE DA REPUBLICA": "servidor",
    "MINISTRO DE ESTADO": "ministro",
}
ROLE_PRIORITY = {"servidor": 1, "magistrado": 2, "ministro": 3, "presidente": 4}


def parse_money(value: str | None) -> float | None:
    """Parse a Brazilian currency value without depending on process locale."""
    if value is None:
        return None
    raw = value.strip().replace("R$", "").replace("\xa0", "").strip()
    if not raw or raw in {"-", "--", "Não informado", "NA"}:
        return None
    raw = raw.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    return float(amount.quantize(Decimal("0.01")))


def normalized(value: str | None) -> str:
    return " ".join((value or "").strip().upper().split())


def clean_public_text(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or text.casefold() in {"-1", "sem informação", "não informado", "não informada"}:
        return None
    return text


def text_csv(binary: BinaryIO) -> TextIO:
    # Portal CSVs use semicolons and Windows-1252-compatible encoding.
    return io.TextIOWrapper(binary, encoding="cp1252", newline="")


def source_file(archive: zipfile.ZipFile, month: str, suffix: str) -> zipfile.ZipInfo:
    expected = f"{month}_{suffix}.csv".casefold()
    for info in archive.infolist():
        if Path(info.filename).name.casefold() == expected:
            return info
    raise ValueError(f"ZIP does not contain expected file {expected}")


def infer_role(position: str | None, function: str | None) -> str:
    title = normalized(position)
    fn = normalized(function)
    if title in TITLE_ROLE:
        return TITLE_ROLE[title]
    if fn in TITLE_ROLE:
        return TITLE_ROLE[fn]
    # Ministro de Primeira/Segunda Classe are diplomatic career grades, not
    # holders of ministerial portfolios, and therefore map to servidor.
    if title.startswith("MINISTRO DE PRIMEIRA CLASSE") or title.startswith("MINISTRO DE SEGUNDA CLASSE"):
        return "servidor"
    if any(word in f"{title} {fn}" for word in ("JUIZ", "MAGISTRADO", "DESEMBARGADOR")):
        return "magistrado"
    return "servidor"


def db_text(value: str | None) -> str | None:
    return value if value else None


def assignment(row: dict) -> dict:
    position = clean_public_text(row.get("DESCRICAO_CARGO"))
    function = clean_public_text(row.get("FUNCAO"))
    if position is None:
        position = function
    institution = clean_public_text(row.get("ORG_LOTACAO")) or clean_public_text(row.get("ORG_EXERCICIO"))
    uf = clean_public_text(row.get("UF_EXERCICIO"))
    if uf and not re.fullmatch(r"[A-Z]{2}", uf.upper()):
        uf = None
    return {
        "role": infer_role(position, function),
        "position": position,
        "function": function,
        "institution": institution,
        "lotacao": clean_public_text(row.get("UORG_LOTACAO")),
        "uf": uf.upper() if uf else None,
        "employmentStatus": clean_public_text(row.get("SITUACAO_VINCULO")),
    }


def add_assignment(conn: sqlite3.Connection, person_id: str, name: str | None, current: dict) -> tuple[bool, bool]:
    """Add a Cadastro tie under its unique public ID; select the senior title."""
    existing = conn.execute(
        "SELECT name, role, position, function, institution, lotacao, uf, employment_status, priority, positions_json, position_count "
        "FROM people WHERE id = ?",
        (person_id,),
    ).fetchone()
    role = current["role"]
    priority = ROLE_PRIORITY[role]
    current_position = {
        "role": role,
        "position": current["position"],
        "function": current["function"],
        "institution": current["institution"],
        "lotacao": current["lotacao"],
        "uf": current["uf"],
        "employmentStatus": current["employmentStatus"],
    }
    if existing is None:
        conn.execute(
            "INSERT INTO people VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                person_id, name, role, current["position"], current["function"],
                current["institution"], current["lotacao"], current["uf"],
                current["employmentStatus"], priority, "", 1,
            ),
        )
        return True, False

    (old_name, old_role, old_position, old_function, old_institution, old_lotacao,
     old_uf, old_status, old_priority, positions_json, position_count) = existing
    old_primary = {
        "role": old_role,
        "position": old_position,
        "function": old_function,
        "institution": old_institution,
        "lotacao": old_lotacao,
        "uf": old_uf,
        "employmentStatus": old_status,
    }
    all_positions = json.loads(positions_json) if positions_json else [old_primary]
    is_new_position = current_position not in all_positions
    if is_new_position:
        all_positions.append(current_position)
        position_count += 1
    update_primary = priority > old_priority
    if update_primary:
        old_name, old_role, old_position, old_function = name or old_name, role, current["position"], current["function"]
        old_institution, old_lotacao = current["institution"], current["lotacao"]
        old_uf, old_status, old_priority = current["uf"], current["employmentStatus"], priority
    elif not old_name and name:
        old_name = name
    stored_positions = json.dumps(all_positions, ensure_ascii=False, separators=(",", ":")) if position_count > 1 else ""
    conn.execute(
        "UPDATE people SET name=?, role=?, position=?, function=?, institution=?, lotacao=?, uf=?, "
        "employment_status=?, priority=?, positions_json=?, position_count=? WHERE id=?",
        (old_name, old_role, old_position, old_function, old_institution, old_lotacao, old_uf,
         old_status, old_priority, stored_positions, position_count, person_id),
    )
    return False, is_new_position


def create_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=FILE")
    conn.execute(
        "CREATE TABLE people ("
        "id TEXT PRIMARY KEY, name TEXT, role TEXT, position TEXT, function TEXT, institution TEXT, "
        "lotacao TEXT, uf TEXT, employment_status TEXT, priority INTEGER, positions_json TEXT, position_count INTEGER)"
    )
    conn.execute(
        "CREATE TABLE payroll ("
        "source_row INTEGER PRIMARY KEY, person_id TEXT NOT NULL, year INTEGER NOT NULL, month INTEGER NOT NULL, gross REAL)"
    )
    conn.execute("CREATE INDEX payroll_person_id ON payroll(person_id)")
    return conn


def import_archive(archive: zipfile.ZipFile, month: str, output: Path, database_path: Path) -> dict:
    cadastro_info = source_file(archive, month, "Cadastro")
    remuneration_info = source_file(archive, month, "Remuneracao")
    conn = create_database(database_path)
    stats = {"assignmentRows": 0, "uniquePeople": 0, "distinctPositions": 0, "multiPositionPeople": 0}
    try:
        with archive.open(remuneration_info) as binary:
            reader = csv.DictReader(text_csv(binary), delimiter=";")
            for source_row, row in enumerate(reader, start=1):
                person_id = (row.get("Id_SERVIDOR_PORTAL") or row.get("ID_SERVIDOR_PORTAL") or "").strip()
                if not person_id:
                    continue
                try:
                    year = int(row.get("ANO") or month[:4])
                    month_no = int(row.get("MES") or month[4:6])
                except ValueError:
                    year, month_no = int(month[:4]), int(month[4:6])
                conn.execute(
                    "INSERT INTO payroll VALUES (?, ?, ?, ?, ?)",
                    (source_row, person_id, year, month_no, parse_money(row.get(GROSS_PAY_COLUMN))),
                )
        conn.commit()

        with archive.open(cadastro_info) as binary:
            reader = csv.DictReader(text_csv(binary), delimiter=";")
            for row in reader:
                person_id = (row.get("Id_SERVIDOR_PORTAL") or row.get("ID_SERVIDOR_PORTAL") or "").strip()
                if not person_id:
                    continue
                stats["assignmentRows"] += 1
                _, added_position = add_assignment(
                    conn,
                    person_id,
                    clean_public_text(row.get("NOME")),
                    assignment(row),
                )
                if added_position:
                    stats["distinctPositions"] += 1
        conn.commit()

        stats["uniquePeople"] = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        # position_count starts at one per person; only distinct additional ties
        # are counted while parsing.
        stats["distinctPositions"] += stats["uniquePeople"]
        stats["multiPositionPeople"] = conn.execute("SELECT COUNT(*) FROM people WHERE position_count > 1").fetchone()[0]
        stats["remunerationRows"] = conn.execute("SELECT COUNT(*) FROM payroll").fetchone()[0]
        stats["distinctPayrollIds"] = conn.execute("SELECT COUNT(DISTINCT person_id) FROM payroll").fetchone()[0]
        stats["duplicatePayrollRows"] = stats["remunerationRows"] - stats["distinctPayrollIds"]
        stats["matchedPayrollRows"] = conn.execute(
            "SELECT COUNT(*) FROM payroll p JOIN people a ON a.id = p.person_id"
        ).fetchone()[0]
        stats["unmatchedPayrollIds"] = conn.execute(
            "SELECT COUNT(DISTINCT p.person_id) FROM payroll p LEFT JOIN people a ON a.id=p.person_id WHERE a.id IS NULL"
        ).fetchone()[0]
        stats["peopleWithoutPayroll"] = conn.execute(
            "SELECT COUNT(*) FROM people a LEFT JOIN payroll p ON p.person_id=a.id WHERE p.person_id IS NULL"
        ).fetchone()[0]
        stats["blankGrossRows"] = conn.execute(
            "SELECT COUNT(*) FROM payroll p JOIN people a ON a.id=p.person_id WHERE p.gross IS NULL"
        ).fetchone()[0]
        stats["salaryRows"] = conn.execute(
            "SELECT COUNT(*) FROM payroll p JOIN people a ON a.id=p.person_id WHERE p.gross IS NOT NULL"
        ).fetchone()[0]
        stats["zeroGrossRows"] = conn.execute(
            "SELECT COUNT(*) FROM payroll p JOIN people a ON a.id=p.person_id WHERE p.gross=0"
        ).fetchone()[0]
        stats["roleCounts"] = {
            role: conn.execute("SELECT COUNT(*) FROM people WHERE role=?", (role,)).fetchone()[0]
            for role in ("presidente", "ministro", "magistrado", "servidor")
        }
        write_jsonl_gzip(conn, output, month, stats)
        return stats
    finally:
        conn.close()


def sources_for(month: str, stats: dict, fetched_at: str) -> list[dict]:
    return [
        {
            "id": f"portal-siape-{month}",
            "label": "Portal da Transparência — folha SIAPE do Poder Executivo Federal",
            "url": PORTAL_DOWNLOAD.format(month=month),
            "scope": "Todas as pessoas e posições listadas na Cadastro.csv mensal SIAPE, com remuneração associada pela chave ID_SERVIDOR_PORTAL.",
            "period": f"{month[:4]}-{month[4:6]}",
            "status": "imported",
            "detail": (
                f"A Cadastro.csv tem {stats['assignmentRows']} linhas profissionais, agregadas em "
                f"{stats['uniquePeople']} IDs públicos únicos; {stats['multiPositionPeople']} pessoas têm mais de uma "
                f"posição distinta, guardada em `positions` sem duplicar o pagamento. Foram importadas "
                f"{stats['salaryRows']} registros com valor numérico de remuneração básica bruta, incluindo "
                f"{stats['zeroGrossRows']} zeros explícitos. {stats['peopleWithoutPayroll']} pessoas não têm linha "
                f"associada em Remuneracao.csv; {stats['blankGrossRows']} linhas associadas têm valor bruto ausente; "
                f"{stats['unmatchedPayrollIds']} IDs do arquivo de remuneração não aparecem em Cadastro.csv. "
                f"Há {stats['duplicatePayrollRows']} linhas remuneratórias além do primeiro registro por ID; elas são "
                "preservadas como linhas-fonte independentes. A parcela importada é exatamente "
                f"{GROSS_PAY_COLUMN}; ela não representa custo total do vínculo. Remuneração após deduções, IR, "
                "previdência, verbas eventuais e indenizatórias não são somadas a ela. O ZIP também contém CPF e "
                "matrícula; esses campos são ignorados e não aparecem nos registros exportados. O escopo é o arquivo "
                "mensal SIAPE, não toda a força de trabalho pública estadual/municipal nem os arquivos separados "
                "BACEN/Militar."
            ),
            "fetchedAt": fetched_at,
        },
        {
            "id": "portal-remuneration-dictionary",
            "label": "Portal da Transparência — dicionário de remuneração de servidores",
            "url": PORTAL_DICTIONARY,
            "scope": "Definições das colunas do arquivo mensal de remuneração federal.",
            "period": "2020 em diante",
            "status": "partial",
            "detail": (
                "Define REMUNERAÇÃO BÁSICA BRUTA (R$) e a distingue de remuneração após deduções, "
                "remunerações eventuais e verbas indenizatórias. Usado para importar uma única medida bruta mensal."
            ),
            "fetchedAt": "2026-10-06T00:00:00Z",
        },
        {
            "id": "stf-composition-20261006",
            "label": "Supremo Tribunal Federal — composição atual",
            "url": STF_COMPOSITION_URL,
            "scope": "Composição nominal dos ministros em exercício no STF na consulta de 2026-10-06.",
            "period": "2026-10",
            "status": "partial",
            "detail": (
                f"Registrados {len(STF_ROSTER)} ministros conforme a página oficial, que mostrava 10 titulares em 11 assentos. "
                "Nenhuma remuneração de magistrado foi importada desta página."
            ),
            "fetchedAt": "2026-10-06T00:00:00Z",
        },
        {
            "id": "cnj-magistrates-pay",
            "label": "CNJ — Painel de Remuneração dos Magistrados",
            "url": CNJ_PAY_URL,
            "scope": "Pagamentos apresentados por tribunais ao CNJ; a página declara cobertura de 92 órgãos do Judiciário.",
            "period": None,
            "status": "unavailable",
            "detail": (
                "O CNJ informa que os dados padronizados são apresentados em painel QlikSense e que cada tribunal é "
                "responsável pelos dados; para dados sem padronização orienta consultar as páginas dos tribunais. "
                "Este adaptador não encontrou um arquivo CSV/bulk ou endpoint público integrado. Nenhum valor de "
                "magistrado foi inferido."
            ),
            "fetchedAt": "2026-10-06T00:00:00Z",
        },
        {
            "id": "siorg-structure",
            "label": "SIORG — estrutura organizacional do Executivo Federal",
            "url": SIORG_API_URL,
            "scope": "Estrutura oficial de órgãos, unidades organizacionais e cargos/funções do Executivo Federal.",
            "period": None,
            "status": "unavailable",
            "detail": (
                "O SIORG é fonte oficial de estruturas, mas a API documenta órgãos e cargos/funções, não uma folha "
                "nominal atual de titulares. Não foi usada para atribuir pessoas ou remunerações."
            ),
            "fetchedAt": "2026-10-06T00:00:00Z",
        },
    ]


def stf_authorities() -> list[dict]:
    return [
        {
            "id": "stf:" + re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-"),
            "name": name,
            "role": "magistrado",
            "branch": "judiciario",
            "sphere": "federal",
            "institution": "Supremo Tribunal Federal",
            "uf": "DF",
            "party": None,
            "sourceId": "stf-composition-20261006",
            "sourceUrl": STF_COMPOSITION_URL,
            "position": "Ministro(a) do Supremo Tribunal Federal",
            "employmentStatus": "Em exercício",
        }
        for name in STF_ROSTER
    ]


def write_record(out: TextIO, record_type: str, data: dict) -> None:
    out.write(json.dumps({"type": record_type, "data": data}, ensure_ascii=False, separators=(",", ":")))
    out.write("\n")


def payroll_expense_id(year: int, month: int, person_id: str, ordinal: int) -> str:
    """Identify a payroll row by person and competence, with a per-person ordinal."""
    return f"portal-siape:{year:04d}{month:02d}:{person_id}:{ordinal}"


def write_jsonl_gzip(conn: sqlite3.Connection, output: Path, month: str, stats: dict) -> None:
    fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sources = sources_for(month, stats, fetched_at)
    stf = stf_authorities()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    source_url = PORTAL_DOWNLOAD.format(month=month)

    try:
        with gzip.open(temporary_output, "wt", encoding="utf-8", newline="", compresslevel=6) as out:
            for source in sources:
                write_record(out, "source", source)

            for row in conn.execute(
                "SELECT id, name, role, position, function, institution, lotacao, uf, employment_status, positions_json, position_count "
                "FROM people ORDER BY id"
            ):
                (person_id, name, role, position, function, institution, lotacao, uf,
                 employment_status, positions_json, position_count) = row
                authority = {
                    "id": f"portal-siape:{person_id}",
                    "name": name,
                    "role": role,
                    "branch": "executivo",
                    "sphere": "federal",
                    "institution": institution,
                    "uf": uf,
                    "party": None,
                    "sourceId": f"portal-siape-{month}",
                    "sourceUrl": source_url,
                    "position": position,
                    "function": function,
                    "lotacao": lotacao,
                    "employmentStatus": employment_status,
                }
                if position_count > 1:
                    authority["positions"] = json.loads(positions_json)
                write_record(out, "authority", authority)

            for authority in stf:
                write_record(out, "authority", authority)

            for row in conn.execute(
                "SELECT p.source_row, p.person_id, p.year, p.month, p.gross, "
                "ROW_NUMBER() OVER (PARTITION BY p.person_id, p.year, p.month "
                "ORDER BY p.gross, p.source_row) AS person_ordinal "
                "FROM payroll p JOIN people a ON a.id=p.person_id "
                "WHERE p.gross IS NOT NULL ORDER BY p.source_row"
            ):
                source_row, person_id, year, month_no, amount, person_ordinal = row
                expense = {
                    "id": payroll_expense_id(year, month_no, person_id, person_ordinal),
                    "authorityId": f"portal-siape:{person_id}",
                    "sourceId": f"portal-siape-{month}",
                    "date": None,
                    "year": year,
                    "month": month_no,
                    "category": GROSS_PAY_COLUMN,
                    "amount": amount,
                    "documentId": f"{month}_Servidores_SIAPE.csv:row-{source_row}",
                    "documentUrl": source_url,
                    "supplier": None,
                    "kind": "remuneracao",
                }
                write_record(out, "expense", expense)
    except Exception:
        temporary_output.unlink(missing_ok=True)
        raise
    temporary_output.replace(output)


def run_with_archive(archive: zipfile.ZipFile, month: str, output: Path, database_path: Path) -> dict:
    return import_archive(archive, month, output, database_path)


def import_source(path: Path | None, month: str, output: Path, temp_dir: Path) -> dict:
    database_path = temp_dir / "professional-only.sqlite"
    if path is not None:
        with zipfile.ZipFile(path) as archive:
            return run_with_archive(archive, month, output, database_path)

    request = urllib.request.Request(
        PORTAL_DOWNLOAD.format(month=month),
        headers={
            "User-Agent": "quanto-custa-public-data-importer/1.0",
            "Referer": "https://portaldatransparencia.gov.br/download-de-dados/servidores",
        },
    )
    # TemporaryFile has no persistent path. The CPF-bearing source ZIP is
    # removed automatically when this context closes.
    with tempfile.TemporaryFile() as temporary:
        with urllib.request.urlopen(request, timeout=120) as response:
            while chunk := response.read(1024 * 1024):
                temporary.write(chunk)
        temporary.seek(0)
        with zipfile.ZipFile(temporary) as archive:
            return run_with_archive(archive, month, output, database_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", default="202608", help="Portal YYYYMM period (default: 202608)")
    parser.add_argument("--zip", dest="zip_path", type=Path, help="Use an already downloaded SIAPE ZIP")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSONL.GZ path")
    args = parser.parse_args()
    if not re.fullmatch(r"20\d{4}", args.month):
        parser.error("--month must be YYYYMM")

    try:
        with tempfile.TemporaryDirectory(prefix="quanto-siape-") as temporary_directory:
            stats = import_source(args.zip_path, args.month, args.output, Path(temporary_directory))
    except (OSError, urllib.error.URLError, zipfile.BadZipFile, ValueError, csv.Error, sqlite3.Error) as exc:
        print(f"Could not import Portal SIAPE data: {exc}", file=sys.stderr)
        print("The official monthly ZIP URL is public and does not require an API token.", file=sys.stderr)
        return 2

    print(f"Wrote streaming gzip JSONL: {args.output}")
    print(
        f"Cadastro: {stats['assignmentRows']} assignments / {stats['uniquePeople']} unique people / "
        f"{stats['distinctPositions']} distinct positions ({stats['multiPositionPeople']} multi-position people)."
    )
    print(
        f"Remuneracao: {stats['matchedPayrollRows']} matched rows / {stats['salaryRows']} numeric gross-basic-pay rows "
        f"({stats['zeroGrossRows']} explicit zeros) / {stats['unmatchedPayrollIds']} unmatched payroll IDs."
    )
    print(f"Unique primary roles: {stats['roleCounts']}; added {len(STF_ROSTER)} STF roster entries without pay data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
