#!/usr/bin/env python3
"""Prepara a cota da Câmara e do Senado dos anos anteriores do mandato para o SQLite.

Lê ``data/raw/legislative/history/legislative-{ano}.json`` (saída de
``ingest/legislative.py``) e grava ``data/imports-history/{camara-ceap,senado-ceaps}-{ano}.json``.
O banco recebe as notas em formato enxuto (pessoa, mês, data, categoria, valor,
fornecedor e link da nota), sem as demais colunas do arquivo. Cada Casa e ano é uma fonte própria
(``camara_ceap_{ano}``, ``senado_ceaps_{ano}``) e não substitui as notas detalhadas de 2026.

Só notas a partir de fev/2023 (legislatura 57 da Câmara; mesmo recorte no Senado,
para as duas Casas seguirem a mesma regra). Importação: ``python3 -m backend.quota_history``.
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
# Casa → (fonte no arquivo anual, prefixo do arquivo agregado, nome padrão da fonte).
HOUSES = {
    "camara": ("camara_ceap", "camara-ceap", "Câmara dos Deputados: cota parlamentar (CEAP)"),
    "senado": ("senado_ceaps", "senado-ceaps", "Senado Federal: cota parlamentar (CEAPS)"),
}
HOUSING_COMPLEMENT_CATEGORY = "COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA"
HOUSING_COMPLEMENT_KIND = "complemento_moradia"


def paths(root: Path = ROOT, year: int = YEARS[0], house: str = "camara") -> dict[str, Path]:
    return {
        "history": root / "data" / "raw" / "legislative" / "history" / f"legislative-{year}.json",
        "output": root / "data" / "imports-history" / f"{HOUSES[house][1]}-{year}.json",
    }


def history_source_id(year: int, house: str = "camara") -> str:
    return f"{HOUSES[house][0]}_{year}"


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


def build_year(history: dict, year: int, house: str = "camara") -> dict:
    source_id, _, default_label = HOUSES[house]
    source = next((s for s in history.get("sources", []) if s.get("id") == source_id), None)
    if not source or source.get("status") != "imported":
        raise ValueError(f"Cota de {house} em {year} não foi importada por completo; nada a preparar")
    notes, referenced = [], set()
    for row in history.get("expenses", []):
        if row.get("sourceId") != source_id or int(row.get("year", 0)) != year:
            continue
        month = int(row["month"])
        if (year, month) < MANDATE_START:
            continue
        referenced.add(row["authorityId"])
        category = row.get("category") or "Não informada"
        key, name, cnpj = supplier_identity(row.get("supplier"))
        url = row.get("documentUrl")
        notes.append({
            "recordId": str(row.get("id") or ""), "authorityId": row["authorityId"], "month": month,
            "date": row.get("date") or None, "category": category, "amountCents": cents(row["amount"]),
            # Mesma regra do esquema v3: o complemento de moradia fica fora da cota.
            "kind": HOUSING_COMPLEMENT_KIND if category == HOUSING_COMPLEMENT_CATEGORY else "reembolso",
            "supplier": {"key": key, "name": name, "cnpj": cnpj} if key and name else None,
            "documentUrl": url if isinstance(url, str) and url.startswith("http") else None,
            "airline": row.get("airline"),
        })
    # Ordem estável dentro do mês: a numeração das notas não muda entre coletas.
    notes.sort(key=lambda note: (note["authorityId"], note["month"], note["recordId"]))
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
            "id": history_source_id(year, house),
            "label": f"{source.get('label') or default_label} — {year}",
            "period": f"{year}-02 a {year}-12" if year == MANDATE_START[0] else f"{year}-01 a {year}-12",
        },
        "year": year,
        "house": house,
        "authorities": authorities,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", default=",".join(map(str, YEARS)), help="anos separados por vírgula")
    parser.add_argument("--houses", default="camara,senado", help="casas separadas por vírgula (camara, senado)")
    args = parser.parse_args(argv)
    houses = [value.strip() for value in args.houses.split(",") if value.strip()]
    if not houses or any(house not in HOUSES for house in houses):
        parser.error("casas aceitas: camara, senado")
    years = [int(value) for value in args.years.split(",") if value.strip()]
    if any(year not in YEARS for year in years):
        parser.error("anos aceitos: " + ", ".join(map(str, YEARS)))
    for year in years:
        history = None
        for house in houses:
            where = paths(ROOT, year, house)
            try:
                history = history or json.loads(where["history"].read_text(encoding="utf-8"))
                result = build_year(history, year, house)
            except (OSError, ValueError) as error:
                print(f"{year}/{house}: {error}", file=sys.stderr)
                return 1
            where["output"].parent.mkdir(parents=True, exist_ok=True)
            temporary = where["output"].with_suffix(".json.tmp")
            temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
            temporary.replace(where["output"])
            print(f"{where['output']}: {len(result['notes'])} notas, {len(result['authorities'])} cadastros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
