#!/usr/bin/env python3
"""Record safe schema evidence for a bounded Senate payroll pilot.

The CSV contains payroll rows for Senate personnel. Collection reads only its
metadata and column-header lines. If those headers do not provide a safe public
senator identifier, the pilot stops before reading any person rows.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Callable
import unicodedata
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ROSTER_PATH = Path("data/imports/legislative.json")
DEFAULT_CACHE = Path("data/raw/mandate-cost/senate-pilot/csv-schema.json")
DEFAULT_OUTPUT = Path("data/snapshots/senate-payroll-pilot.json")
CSV_URL = (
    "https://www.senado.leg.br/transparencia/LAI/secrh/"
    "SF_ConsultaRemuneracaoServidoresParlamentares_202609.csv"
)
CSV_INDEX_URL = "https://www.senado.leg.br/transparencia/rh/servidores/consulta_remuneracao.asp"
SENATE_ROSTER_URL = "https://legis.senado.leg.br/dadosabertos/senador/lista/atual"
INDIVIDUAL_GUIDE_URL = (
    "https://www12.senado.leg.br/perguntas-frequentes/canais-de-atendimento/"
    "senadores/posso-consultar-o-contracheque-de-um-senador"
)
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
COMPETENCE = "2026-09"
MAX_SENATORS = 10
SOURCE_ID = "senado_senators_current"
SENATOR_ID = re.compile(r"^senado:(\d+)$")
MAX_HEADER_BYTES = 65536
SCHEMA_CACHE_KEYS = {
    "schemaVersion", "sourceUrl", "competence", "capturedAt", "sourceUpdatedAt", "fields"
}
EXPECTED_FIELDS = [
    "VÍNCULO", "CATEGORIA", "CARGO", "REFERÊNCIA CARGO", "SÍMBOLO FUNÇÃO",
    "ANO EXERCÍCIO", "LOTAÇÃO EXERCÍCIO", "TIPO FOLHA", "REMUN_BASICA",
    "VANT_PESSOAIS", "FUNC_COMISSIONADA", "GRAT_NATALINA", "HORAS_EXTRAS",
    "OUTRAS_EVENTUAIS", "ABONO_PERMANENCIA", "REVERSAO_TETO_CONST",
    "IMPOSTO_RENDA", "PREVIDÊNCIA", "FALTAS", "REM_LIQUIDA", "DIÁRIAS",
    "AUXÍLIOS", "VANT_INDENIZATORIAS",
]


class PilotError(RuntimeError):
    """Raised when safe, reproducible pilot evidence is unavailable."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFD", value.casefold())
    return " ".join("".join(c for c in value if unicodedata.category(c) != "Mn").split())


def _parse_csv_line(raw: bytes) -> list[str]:
    text = raw.decode("cp1252", errors="strict").lstrip("\ufeff").rstrip("\r\n")
    return next(csv.reader([text], delimiter=";"))


def _source_updated_at(metadata: list[str]) -> str | None:
    if len(metadata) < 2 or "ultima atualizacao" not in _normalized(metadata[0]):
        return None
    try:
        return datetime.strptime(metadata[1].strip(), "%d/%m/%Y %H:%M").isoformat(timespec="minutes")
    except ValueError:
        return None


def fetch_schema(
    opener: Callable[..., Any] = urlopen,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Read the two schema lines only; never parse or retain a payroll row."""
    request = Request(
        CSV_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "text/csv", "Range": "bytes=0-8191"},
    )
    with opener(request, timeout=30) as response:
        metadata_line = response.readline(MAX_HEADER_BYTES)
        header_line = response.readline(MAX_HEADER_BYTES)
    if not metadata_line or not header_line or len(header_line) >= MAX_HEADER_BYTES:
        raise PilotError("Não foi possível ler com segurança as linhas de metadados e cabeçalho do CSV.")
    try:
        metadata = _parse_csv_line(metadata_line)
        fields = _parse_csv_line(header_line)
    except (UnicodeDecodeError, csv.Error, StopIteration) as error:
        raise PilotError("O cabeçalho do CSV não pôde ser interpretado com segurança.") from error
    if len(metadata) < 2 or _normalized(metadata[0]) != "ultima atualizacao":
        raise PilotError("A primeira linha não corresponde aos metadados esperados do CSV.")
    if fields != EXPECTED_FIELDS:
        raise PilotError("O cabeçalho do CSV mudou; coleta interrompida sem salvar conteúdo.")
    return {
        "schemaVersion": 1,
        "sourceUrl": CSV_URL,
        "competence": COMPETENCE,
        "capturedAt": fetched_at or utc_now(),
        "sourceUpdatedAt": _source_updated_at(metadata),
        "fields": fields,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary_path = stream.name
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _write_schema_cache(path: Path, schema: dict[str, Any]) -> None:
    if set(schema) != SCHEMA_CACHE_KEYS or schema.get("sourceUrl") != CSV_URL:
        raise PilotError("A projeção de cabeçalho contém campos inesperados.")
    fields = schema.get("fields")
    if fields != EXPECTED_FIELDS:
        raise PilotError("A projeção de cabeçalho está inválida.")
    _atomic_json(path, schema)


def _read_schema_cache(path: Path) -> dict[str, Any] | None:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(schema, dict) or set(schema) != SCHEMA_CACHE_KEYS:
        return None
    fields = schema.get("fields")
    if (
        schema.get("schemaVersion") != 1
        or schema.get("sourceUrl") != CSV_URL
        or schema.get("competence") != COMPETENCE
        or fields != EXPECTED_FIELDS
    ):
        return None
    return schema


def _selected_senator_ids(roster_payload: Any) -> list[str]:
    if not isinstance(roster_payload, dict) or not isinstance(roster_payload.get("authorities"), list):
        raise PilotError("A lista local não contém as autoridades parlamentares esperadas.")
    senator_ids: set[str] = set()
    for row in roster_payload["authorities"]:
        if (
            not isinstance(row, dict)
            or row.get("sourceId") != SOURCE_ID
            or row.get("role") != "senador"
            or not isinstance(row.get("name"), str)
            or not row["name"].strip()
        ):
            continue
        match = SENATOR_ID.fullmatch(str(row.get("id") or ""))
        if match:
            senator_ids.add(f"senado:{match.group(1)}")
    return sorted(senator_ids, key=lambda identifier: int(identifier.split(":", 1)[1]))[:MAX_SENATORS]


def _load_roster(root: Path) -> dict[str, Any]:
    path = root / ROSTER_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PilotError("A importação local da lista atual do Senado está ausente ou inválida.") from error
    return payload


def build_snapshot(
    root: Path = ROOT,
    output: Path | None = None,
    cache_path: Path | None = None,
    roster_payload: Any | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    cache = _read_schema_cache(cache_path or (root / DEFAULT_CACHE))
    if cache is None:
        raise PilotError("Cache seguro do cabeçalho ausente ou inválido; use --collect para ler apenas o cabeçalho.")
    roster = roster_payload if roster_payload is not None else _load_roster(root)
    selected_ids = _selected_senator_ids(roster)
    fields = cache["fields"]
    linkage_reason = (
        "O CSV não contém coluna pública de nome ou identificador individual de senador. "
        "A leitura foi interrompida após o cabeçalho; cargo ou lotação não comprovam a identidade da linha."
    )
    linkage_status = "unavailable"
    snapshot = {
        "generatedAt": utc_now(),
        "competence": COMPETENCE,
        "status": linkage_status,
        "source": {
            "sourceUrl": CSV_URL,
            "indexUrl": CSV_INDEX_URL,
            "rosterUrl": SENATE_ROSTER_URL,
            "competence": COMPETENCE,
            "capturedAt": cache["capturedAt"],
            "sourceUpdatedAt": cache.get("sourceUpdatedAt"),
            "schemaOnly": True,
            "fields": fields,
        },
        "pilot": {
            "selectionRule": "Até 10 IDs da lista local atual, ordenados numericamente; amostra não representativa.",
            "selectedSenatorCount": len(selected_ids),
            "selectedSenatorIds": selected_ids,
            "linkedSenatorCount": 0,
            "verifiedPersonMonthCount": 0,
            "individualConsultationCount": 0,
            "individualConsultationStatus": "not_attempted",
            "individualConsultationGuideUrl": INDIVIDUAL_GUIDE_URL,
            "linkageStatus": linkage_status,
            "detail": linkage_reason,
        },
    }
    destination = output or (root / DEFAULT_OUTPUT)
    _atomic_json(destination, snapshot)
    return snapshot, {
        "selected": len(selected_ids),
        "linked": 0,
        "verified": 0,
    }


def run(
    root: Path = ROOT,
    collect: bool = False,
    refresh: bool = False,
    output: Path | None = None,
    opener: Callable[..., Any] = urlopen,
) -> tuple[dict[str, Any], dict[str, int]]:
    if refresh and not collect:
        raise PilotError("--refresh exige --collect.")
    cache_path = root / DEFAULT_CACHE
    cache = _read_schema_cache(cache_path)
    if collect and (refresh or cache is None):
        schema = fetch_schema(opener=opener)
        _write_schema_cache(cache_path, schema)
    return build_snapshot(root=root, output=output, cache_path=cache_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Registra evidência segura do piloto de folha do Senado")
    parser.add_argument("--collect", action="store_true", help="consulta somente metadados e cabeçalho do CSV oficial")
    parser.add_argument("--refresh", action="store_true", help="atualiza o cabeçalho mesmo com cache válido")
    parser.add_argument("--output", type=Path, help="caminho alternativo para o snapshot JSON")
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error("--refresh exige --collect")
    output = args.output
    if output is not None and not output.is_absolute():
        output = ROOT / output
    try:
        snapshot, stats = run(collect=args.collect, refresh=args.refresh, output=output)
    except PilotError as error:
        parser.error(str(error))
    print(
        "snapshot",
        f"status={snapshot['status']}",
        f"selecionados={stats['selected']}",
        f"ligados={stats['linked']}",
        f"verificados={stats['verified']}",
        f"saida={output or ROOT / DEFAULT_OUTPUT}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
