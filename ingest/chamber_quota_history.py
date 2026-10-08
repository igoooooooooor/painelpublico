#!/usr/bin/env python3
"""Agrega a cota da Câmara dos anos anteriores do mandato para o SQLite.

Lê ``data/raw/legislative/history/legislative-{ano}.json`` (saída de
``ingest/legislative.py``) e grava ``data/imports-history/camara-ceap-{ano}.json``.
As notas brutas ficam só na base local; o banco recebe agregados por pessoa:
mês e categoria, fornecedor e as maiores notas. Cada ano é uma fonte própria
(``camara_ceap_{ano}``) e não substitui as notas detalhadas de 2026.

Só a Câmara, só notas a partir de fev/2023 (legislatura 57). Importação:
``python3 -m backend.quota_history``.
"""
from __future__ import annotations

import argparse
from decimal import ROUND_HALF_UP, Decimal
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANDATE_START = (2023, 2)
YEARS = (2023, 2024, 2025)
SOURCE_ID = "camara_ceap"
HOUSING_COMPLEMENT_CATEGORY = "COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA"
HOUSING_COMPLEMENT_KIND = "complemento_moradia"
LARGEST_PER_PERSON = 5


def paths(root: Path = ROOT, year: int = YEARS[0]) -> dict[str, Path]:
    return {
        "history": root / "data" / "raw" / "legislative" / "history" / f"legislative-{year}.json",
        "output": root / "data" / "imports-history" / f"camara-ceap-{year}.json",
    }


def history_source_id(year: int) -> str:
    return f"{SOURCE_ID}_{year}"


def cents(value) -> int:
    # Mesma conversão de backend.public_store.money.
    if isinstance(value, bool) or value is None:
        raise ValueError("Valor monetário ausente/inválido")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Valor monetário não finito")
    return int((number * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def supplier_identity(supplier):
    """Mesma chave de backend.public_store: CNPJ de 14 dígitos ou a chave publicada."""
    if not supplier:
        return None, None, None
    cnpj = supplier.get("cnpj")
    if cnpj is not None and not re.fullmatch(r"\d{14}", str(cnpj)):
        raise ValueError("Fornecedor com identificador que não é CNPJ")
    key = "cnpj:" + cnpj if cnpj else supplier.get("key")
    return key, supplier.get("name"), cnpj


def build_year(history: dict, year: int) -> dict:
    source = next((s for s in history.get("sources", []) if s.get("id") == SOURCE_ID), None)
    if not source or source.get("status") != "imported":
        raise ValueError(f"Cota da Câmara de {year} não foi importada por completo; nada a agregar")
    months, suppliers, largest, referenced = {}, {}, {}, set()
    for row in history.get("expenses", []):
        if row.get("sourceId") != SOURCE_ID or int(row.get("year", 0)) != year:
            continue
        month = int(row["month"])
        if (year, month) < MANDATE_START:
            continue
        authority = row["authorityId"]
        referenced.add(authority)
        amount = cents(row["amount"])
        category = row.get("category") or "Não informada"
        # Mesma regra do esquema v3: o complemento de moradia fica fora da cota.
        kind = HOUSING_COMPLEMENT_KIND if category == HOUSING_COMPLEMENT_CATEGORY else "reembolso"
        bucket = months.setdefault((authority, month, category, kind), [0, 0])
        bucket[0] += amount
        bucket[1] += 1
        if kind != "reembolso":
            continue
        key, name, cnpj = supplier_identity(row.get("supplier"))
        if key and name:
            entry = suppliers.setdefault((authority, key), {"name": name, "cnpj": cnpj, "amountCents": 0, "count": 0})
            entry["amountCents"] += amount
            entry["count"] += 1
        notes = largest.setdefault(authority, [])
        notes.append({"date": row.get("date"), "month": month, "category": category, "amountCents": amount,
                      "documentUrl": row.get("documentUrl"), "supplierName": name})
        notes.sort(key=lambda note: -note["amountCents"])
        del notes[LARGEST_PER_PERSON:]
    authorities = [
        {key: a.get(key) for key in ("id", "name", "role", "branch", "sphere", "institution", "uf", "party",
                                     "sourceUrl", "position", "employmentStatus")}
        for a in history.get("authorities", []) if a.get("id") in referenced
    ]
    missing = referenced - {a["id"] for a in authorities}
    if missing:
        raise ValueError(f"Notas sem cadastro em {year}: {sorted(missing)[:5]}")
    return {
        "source": {
            **{key: source.get(key) for key in ("url", "scope", "status", "detail", "fetchedAt")},
            "id": history_source_id(year),
            "label": f"{source.get('label') or 'Câmara dos Deputados: cota parlamentar (CEAP)'} — {year}",
            "period": f"{year}-02 a {year}-12" if year == MANDATE_START[0] else f"{year}-01 a {year}-12",
        },
        "year": year,
        "authorities": authorities,
        "months": [{"authorityId": a, "month": m, "category": c, "kind": k, "amountCents": v[0], "count": v[1]}
                   for (a, m, c, k), v in sorted(months.items())],
        "suppliers": [{"authorityId": a, "supplierKey": key, **value} for (a, key), value in sorted(suppliers.items())],
        "largest": [{"authorityId": a, "rank": index + 1, **note}
                    for a, notes in sorted(largest.items()) for index, note in enumerate(notes)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", default=",".join(map(str, YEARS)), help="anos separados por vírgula")
    args = parser.parse_args(argv)
    years = [int(value) for value in args.years.split(",") if value.strip()]
    if any(year not in YEARS for year in years):
        parser.error("anos aceitos: " + ", ".join(map(str, YEARS)))
    for year in years:
        where = paths(ROOT, year)
        try:
            history = json.loads(where["history"].read_text(encoding="utf-8"))
            result = build_year(history, year)
        except (OSError, ValueError) as error:
            print(f"{year}: {error}", file=sys.stderr)
            return 1
        where["output"].parent.mkdir(parents=True, exist_ok=True)
        temporary = where["output"].with_suffix(".json.tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(where["output"])
        print(f"{where['output']}: {len(result['months'])} linhas mês/categoria, "
              f"{len(result['suppliers'])} pessoa/fornecedor, {len(result['authorities'])} cadastros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
