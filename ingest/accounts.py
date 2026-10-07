"""Offline-first SICONFI DCA snapshots for municipal accounts.

The collector stores only the five selected financial observations per city.
It never persists complete API pages. Use ``--collect`` to fill missing city
caches, ``--collect --refresh`` to refetch them, or run without flags to build
the snapshot from local files only.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Iterable
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

YEAR = 2025
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
DOWNLOAD_TIMEOUT = 90
REQUEST_INTERVAL_SECONDS = 1.05
PAGE_LIMIT = 500

SICONFI_BASE_URL = "https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt"
DCA_URL = SICONFI_BASE_URL + "/dca?an_exercicio={year}&id_ente={municipality_id}"
DELIVERIES_URL = SICONFI_BASE_URL + "/extrato_entregas?an_referencia={year}&id_ente={municipality_id}"
ENTES_URL = SICONFI_BASE_URL + "/entes?limit=5000"
SOURCE_LABEL = "Tesouro Nacional — Siconfi, Declaração de Contas Anuais (DCA)"
SOURCE_DATASET_URL = "https://www.tesourotransparente.gov.br/ckan/dataset/api-dca-entes"
POPULATION_URL = "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/{year}/variaveis/9324?localidades=N6%5Ball%5D"

# Pagination links are untrusted response content. Only follow the official
# API origin or the currently documented Oracle API gateway origin, and only
# the same endpoint path with the requested year and IBGE code.
TRUSTED_HOSTS = {
    "apidatalake.tesouro.gov.br",
    "host-5hrds-scan.prosubnet.vcndados.oraclevcn.com",
}

SPECIAL_MUNICIPALITIES = {
    "5300108": "Brasília não é município e não entrega DCA municipal nesta consulta.",
    "2605459": "Fernando de Noronha é distrito estadual e não entrega DCA municipal nesta consulta.",
}

DCA_ITEM_FIELDS = (
    "exercicio", "cod_ibge", "instituicao", "anexo", "rotulo", "coluna",
    "cod_conta", "conta", "valor",
)
DELIVERY_FIELDS = (
    "exercicio", "cod_ibge", "entregavel", "periodo", "periodicidade",
    "status_relatorio", "data_status",
)
ENTE_FIELDS = ("cod_ibge", "uf", "esfera", "ente")

METRIC_SPECS = (
    {
        "id": "revenue",
        "label": "Receita bruta realizada, inclusive intraorçamentária",
        "classification": "revenue",
        "stage": "realized",
        "selector": {
            "anexo": "DCA-Anexo I-C", "rotulo": "Padrão",
            "coluna": "Receitas Brutas Realizadas", "cod_conta": "TotalReceitas",
        },
    },
    {
        "id": "total-expense",
        "label": "Despesa empenhada total, inclusive intraorçamentária",
        "classification": "total",
        "stage": "committed",
        "selector": {
            "anexo": "DCA-Anexo I-D", "rotulo": "Padrão",
            "coluna": "Despesas Empenhadas", "cod_conta": "TotalDespesas",
        },
    },
    {
        "id": "personnel",
        "label": "Pessoal e encargos (exceto intraorçamentárias)",
        "classification": "nature",
        "stage": "committed",
        "selector": {
            "anexo": "DCA-Anexo I-D", "rotulo": "Padrão",
            "coluna": "Despesas Empenhadas", "cod_conta": "DO3.1.00.00.00.00",
        },
    },
    {
        "id": "health",
        "label": "Despesa empenhada por função em saúde, exceto intraorçamentárias",
        "classification": "function",
        "stage": "committed",
        "selector": {
            "anexo": "DCA-Anexo I-E", "rotulo": "Total Geral da Despesa por Função",
            "coluna": "Despesas Empenhadas", "cod_conta": "TotalDespesas",
            "conta": "10 - Saúde",
        },
    },
    {
        "id": "education",
        "label": "Despesa empenhada por função em educação, exceto intraorçamentárias",
        "classification": "function",
        "stage": "committed",
        "selector": {
            "anexo": "DCA-Anexo I-E", "rotulo": "Total Geral da Despesa por Função",
            "coluna": "Despesas Empenhadas", "cod_conta": "TotalDespesas",
            "conta": "12 - Educação",
        },
    },
)

_last_request_at = 0.0


def paths(root: Path = ROOT, year: int = YEAR) -> dict[str, Path]:
    raw = root / "data" / "raw" / "siconfi"
    cache_dir = raw / f"accounts-{year}"
    return {
        "cache_dir": cache_dir,
        "national_items": cache_dir / "items.jsonl",
        "national_items_meta": cache_dir / "items.meta.json",
        "population": raw / f"population-{year}.json",
        "population_meta": raw / f"population-{year}.meta.json",
        "entities": raw / "entes.json",
        "legacy_population": root / "data" / "raw" / "ibge" / "population.json",
        "legacy_population_meta": root / "data" / "raw" / "ibge" / "population.meta.json",
        "city_catalog": root / "data" / "snapshots" / "cities.json",
        "output": root / "data" / "snapshots" / "accounts.json",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream, parse_float=Decimal)
    except FileNotFoundError:
        return default


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temp_name = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                value = json.loads(line, parse_float=Decimal)
                if isinstance(value, dict):
                    yield value


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    """Copy only the documented, non-identifying DCA fields used here."""
    projected = {}
    for field in DCA_ITEM_FIELDS:
        if field not in item:
            continue
        value = item[field]
        if isinstance(value, Decimal):
            value = str(value)
        projected[field] = value
    return projected


def _public_delivery(item: dict[str, Any]) -> dict[str, Any]:
    """Keep only public registry fields needed to confirm a delivered DCA."""
    return {field: item[field] for field in DELIVERY_FIELDS if field in item}


def _public_ente(item: dict[str, Any]) -> dict[str, Any]:
    """Keep only public identity fields used to match SICONFI to the city catalog."""
    return {field: item[field] for field in ENTE_FIELDS if field in item}


def _response_body(response) -> bytes:
    body = response.read()
    if response.headers.get("Content-Encoding", "").lower() == "gzip" or body[:2] == b"\x1f\x8b":
        return gzip.decompress(body)
    return body


def _amount_cents(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not amount.is_finite():
        return None
    cents = amount * Decimal(100)
    if cents != cents.to_integral_value():
        return None
    return int(cents)


def _is_municipal_institution(value: Any) -> bool:
    return str(value or "").strip().casefold().startswith("prefeitura")


def _row_matches(item: dict[str, Any], selector: dict[str, str]) -> bool:
    return all(str(item.get(field, "")).strip() == expected for field, expected in selector.items())


def _metric_amount(items: list[dict[str, Any]], spec: dict[str, Any], municipality_id: str, year: int) -> int | None:
    selected = []
    for item in items:
        try:
            row_year = int(str(item.get("exercicio", "")).strip())
        except ValueError:
            continue
        if row_year != year or str(item.get("cod_ibge", "")).strip() != municipality_id:
            continue
        if not _is_municipal_institution(item.get("instituicao")):
            continue
        if _row_matches(item, spec["selector"]):
            selected.append(_amount_cents(item.get("valor")))
    if not selected or any(value is None for value in selected):
        return None
    unique = set(selected)
    return next(iter(unique)) if len(unique) == 1 else None


def _source(url: str, year: int, fetched_at: str | None, status: str, note: str | None = None) -> dict[str, Any]:
    value = {
        "label": SOURCE_LABEL,
        "url": url,
        "period": f"exercício de {year}",
        "fetchedAt": fetched_at,
        "status": status,
    }
    if note:
        value["note"] = note
    return value


def _cache_entes_payload(payload: Any, destination: Path, fetched_at: str | None = None) -> dict[str, Any]:
    """Persist a fully paginated official /entes response without CNPJ fields."""
    if not isinstance(payload, dict) or payload.get("hasMore") is not False or not isinstance(payload.get("items"), list):
        raise ValueError("SICONFI /entes cache must contain a complete items list")
    rows = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise ValueError("SICONFI /entes cache contains a malformed row")
        identifier = str(item.get("cod_ibge", "")).strip()
        uf = str(item.get("uf", "")).strip().upper()
        sphere = str(item.get("esfera", "")).strip().upper()
        name = str(item.get("ente", "")).strip()
        if re.fullmatch(r"\d{7}", identifier) and re.fullmatch(r"[A-Z]{2}", uf) and sphere in {"M", "D"}:
            rows.append({"cod_ibge": identifier, "uf": uf, "esfera": sphere, "ente": name})
    if not rows:
        raise ValueError("SICONFI /entes cache contains no valid municipality entries")
    cache = {
        "complete": True,
        "items": rows,
        "source": {
            "label": "Tesouro Nacional — Siconfi, cadastro de entes",
            "url": SICONFI_BASE_URL + "/entes",
            "period": "cadastro vigente na consulta",
            "fetchedAt": fetched_at,
            "status": "cached",
        },
    }
    _atomic_json(destination, cache)
    return cache


def _verified_ente_ids(path: Path, municipalities: list[dict[str, Any]]) -> set[str]:
    """Match complete official registry rows to the IBGE catalog by code, UF and sphere."""
    cache = _read_json(path, None)
    if not isinstance(cache, dict) or cache.get("complete") is not True or not isinstance(cache.get("items"), list):
        return set()
    source = cache.get("source")
    source_url = urlsplit(str(source.get("url") or "")) if isinstance(source, dict) else None
    if (not isinstance(source, dict)
            or source.get("status") not in {"available", "cached", "imported"}
            or source_url.scheme != "https"
            or source_url.hostname not in TRUSTED_HOSTS
            or source_url.path != urlsplit(SICONFI_BASE_URL + "/entes").path):
        return set()
    catalog = {str(row.get("id")): str(row.get("uf") or "").upper() for row in municipalities if isinstance(row, dict)}
    candidates: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in cache["items"]:
        if not isinstance(row, dict):
            continue
        identifier = str(row.get("cod_ibge", "")).strip()
        uf = str(row.get("uf", "")).strip().upper()
        sphere = str(row.get("esfera", "")).strip().upper()
        if identifier in catalog and catalog[identifier] == uf and sphere == "M":
            candidates[identifier].add((uf, sphere))
    return {identifier for identifier, entries in candidates.items() if len(entries) == 1}


def _source_verifies_identity(source: Any, municipality_id: str, year: int) -> bool:
    if not isinstance(source, dict):
        return False
    parts = urlsplit(str(source.get("url") or ""))
    if parts.scheme != "https" or parts.hostname not in TRUSTED_HOSTS:
        return False
    if parts.path not in {
        urlsplit(SICONFI_BASE_URL + "/dca").path,
        urlsplit(SICONFI_BASE_URL + "/extrato_entregas").path,
    }:
        return False
    query = parse_qs(parts.query)
    expected_year_key = "an_exercicio" if parts.path.endswith("/dca") else "an_referencia"
    return query.get("id_ente") == [municipality_id] and query.get(expected_year_key) == [str(year)]


def _identity_evidence(row: dict[str, Any], municipality_id: str, year: int) -> str | None:
    if row.get("identityVerified") is True:
        return str(row.get("identityEvidence") or "cadastro Siconfi verificado")
    declaration = row.get("declaration") if isinstance(row.get("declaration"), dict) else {}
    if declaration.get("status") != "submitted":
        return None
    sources = [row.get("source")]
    metrics = row.get("metrics")
    if isinstance(metrics, list):
        sources.extend(metric.get("source") for metric in metrics if isinstance(metric, dict))
    for source in sources:
        if _source_verifies_identity(source, municipality_id, year):
            return str(source.get("label") or "consulta oficial do Siconfi")
    return None


def _normalize_cache_identity(row: dict[str, Any], municipality_id: str, year: int) -> dict[str, Any] | None:
    status = row.get("status")
    evidence = _identity_evidence(row, municipality_id, year)
    declaration = row.get("declaration") if isinstance(row.get("declaration"), dict) else {}
    if status == "not_filed" and row.get("identityVerified") is not True:
        return None
    if status == "stale" and row.get("identityVerified") is not True and evidence is None:
        return None
    if status in {"available", "partial", "stale"} and declaration.get("status") == "submitted" and evidence:
        row["identityVerified"] = True
        row.setdefault("identityEvidence", evidence)
        row.setdefault("collectionComplete", True)
    return row


def _metric_rows(items: list[dict[str, Any]], municipality_id: str, year: int,
                 source: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for spec in METRIC_SPECS:
        output.append({
            "id": spec["id"],
            "label": spec["label"],
            "amountCents": _metric_amount(items, spec, municipality_id, year),
            "classification": spec["classification"],
            "stage": spec["stage"],
            "source": dict(source),
        })
    return output


def _normalize_metric_labels(row: dict[str, Any]) -> None:
    specs = {spec["id"]: spec for spec in METRIC_SPECS}
    metrics = row.get("metrics")
    if not isinstance(metrics, list):
        return
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        spec = specs.get(str(metric.get("id")))
        if spec:
            metric["label"] = spec["label"]


def _project_dca_payload(payload: Any, municipality_id: str, year: int,
                         source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("SICONFI DCA response is missing an items list")
    if payload.get("hasMore") is not False:
        raise ValueError("SICONFI DCA response is incomplete")
    items = []
    for raw in payload["items"]:
        if not isinstance(raw, dict):
            raise ValueError("SICONFI DCA response contains a malformed item")
        row_code = str(raw.get("cod_ibge", "")).strip()
        if row_code and row_code != municipality_id:
            raise ValueError("SICONFI DCA response contains another municipality code")
        if raw.get("exercicio") is not None and str(raw.get("exercicio")).strip() != str(year):
            raise ValueError("SICONFI DCA response contains another exercise year")
        if row_code == municipality_id and str(raw.get("exercicio", "")).strip() == str(year):
            items.append(_public_item(raw))
    return _project_dca_items(items, municipality_id, year, source)


def _project_dca_items(items: list[dict[str, Any]], municipality_id: str, year: int,
                       source: dict[str, Any], collection_complete: bool = True) -> dict[str, Any]:
    if not items:
        return {
            "year": year,
            "id": municipality_id,
            "status": "needs_registry_check",
            "collectionComplete": collection_complete,
            "declaration": {"status": "unknown"},
            "message": "A consulta da DCA não trouxe valores; o extrato de entregas ainda precisa ser consultado.",
            "metrics": [],
            "source": dict(source),
        }
    metrics = _metric_rows(items, municipality_id, year, source)
    observed = sum(isinstance(metric["amountCents"], int) and not isinstance(metric["amountCents"], bool)
                   for metric in metrics)
    status = "available" if observed == len(METRIC_SPECS) and collection_complete else "partial"
    if status == "available":
        message = ""
    elif not collection_complete:
        message = "Os valores vieram de um arquivo nacional sem confirmação de cobertura completa."
    else:
        message = "A DCA foi encontrada, mas nem todos os indicadores têm um valor válido e único nesta base."
    return {
        "year": year,
        "id": municipality_id,
        "status": status,
        "collectionComplete": collection_complete,
        "identityVerified": True,
        "identityEvidence": source.get("label", SOURCE_LABEL),
        "declaration": {"status": "submitted"},
        "message": message,
        "metrics": metrics,
        "source": dict(source),
    }


def _valid_same_city_extrato_record(item: dict[str, Any], municipality_id: str) -> bool:
    if str(item.get("cod_ibge", "")).strip() != municipality_id:
        return False
    try:
        report_year = int(str(item.get("exercicio", "")).strip())
        period = int(str(item.get("periodo", "")).strip())
    except ValueError:
        return False
    return report_year >= 1900 and period > 0 and bool(str(item.get("entregavel", "")).strip())


def _extract_status(payload: Any, municipality_id: str, year: int,
                    verified_identity: bool = False) -> tuple[str, str | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("SICONFI delivery response is missing an items list")
    if payload.get("hasMore") is not False:
        raise ValueError("SICONFI delivery response is incomplete")
    matching = []
    valid_identity_record = False
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise ValueError("SICONFI delivery response contains a malformed item")
        if _valid_same_city_extrato_record(item, municipality_id):
            valid_identity_record = True
        if (str(item.get("cod_ibge", "")).strip() == municipality_id
                and str(item.get("exercicio", "")).strip() == str(year)
                and item.get("entregavel") == "Balanço Anual (DCA)"
                and str(item.get("periodo", "")).strip() == "1"):
            matching.append(item)
    approved = [item for item in matching if item.get("status_relatorio") in {"HO", "RE"}]
    if approved:
        approved.sort(key=lambda item: str(item.get("data_status") or ""))
        return "submitted", str(approved[-1].get("data_status") or "") or None
    if matching:
        return "unknown", None
    if valid_identity_record or verified_identity:
        return "not_filed", None
    return "unverified", None


def _project_city_payloads(dca_payload: Any, deliveries_payload: Any | None,
                           municipality_id: str, year: int, source: dict[str, Any],
                           verified_identity: bool = False) -> dict[str, Any]:
    row = _project_dca_payload(dca_payload, municipality_id, year, source)
    if row["status"] != "needs_registry_check":
        return row
    if deliveries_payload is None:
        raise ValueError("SICONFI delivery register is required when DCA is empty")
    delivery_status, submitted_at = _extract_status(deliveries_payload, municipality_id, year, verified_identity)
    identity_verified = verified_identity or delivery_status in {"submitted", "not_filed", "unknown"}
    row["collectionComplete"] = delivery_status in {"submitted", "not_filed"}
    row["identityVerified"] = identity_verified
    if identity_verified:
        row["identityEvidence"] = "cadastro oficial de entes" if verified_identity else "registro válido no extrato do Siconfi"
    delivery_source = dict(source)
    if delivery_source.get("deliveryUrl"):
        delivery_source["label"] = "Tesouro Nacional — Siconfi, Extrato de Entregas da DCA"
        delivery_source["url"] = delivery_source["deliveryUrl"]
    if delivery_status == "submitted":
        row.update({
            "status": "partial",
            "declaration": {"status": "submitted", **({"submittedAt": submitted_at} if submitted_at else {})},
            "message": "O extrato do Siconfi registra a entrega da DCA, mas os valores não vieram na consulta detalhada.",
            "source": delivery_source,
        })
    elif delivery_status == "unknown":
        row.update({
            "status": "unavailable",
            "declaration": {"status": "unavailable"},
            "message": "O extrato contém uma linha da DCA, mas o status não confirma homologação ou retificação.",
            "source": delivery_source,
        })
    elif delivery_status == "unverified":
        row.update({
            "status": "unavailable",
            "declaration": {"status": "unavailable"},
            "message": "A consulta não confirma que este código estava cadastrado no Siconfi; ausência de linha não confirma falta de entrega.",
            "source": delivery_source,
        })
    else:
        row.update({
            "status": "not_filed",
            "declaration": {"status": "not_filed"},
            "message": "Não entregou ao Tesouro: não há DCA homologada ou retificada no extrato consultado para este exercício.",
            "source": delivery_source,
        })
    return row


def _validate_next_url(url: str, endpoint: str, municipality_id: str | None = None,
                       year: int | None = None) -> str:
    parts = urlsplit(url)
    expected_path = urlsplit(SICONFI_BASE_URL + endpoint).path
    if parts.scheme != "https" or parts.hostname not in TRUSTED_HOSTS or parts.path != expected_path:
        raise ValueError("SICONFI pagination link uses an untrusted host or path")
    query = parse_qs(parts.query, keep_blank_values=True)
    if endpoint == "/entes":
        if any(key not in {"offset", "limit"} for key in query):
            raise ValueError("SICONFI /entes pagination link has unexpected query parameters")
        for key in ("offset", "limit"):
            if key in query and (len(query[key]) != 1 or not query[key][0].isdigit()):
                raise ValueError("SICONFI /entes pagination link has an invalid page parameter")
        return url
    if endpoint not in {"/dca", "/extrato_entregas"} or municipality_id is None or year is None:
        raise ValueError("SICONFI pagination endpoint is missing its requested identity")
    year_key = "an_exercicio" if endpoint == "/dca" else "an_referencia"
    if query.get(year_key) != [str(year)] or query.get("id_ente") != [municipality_id]:
        raise ValueError("SICONFI pagination link changes the exercise or municipality")
    for key in ("offset", "limit"):
        if key in query and (len(query[key]) != 1 or not query[key][0].isdigit()):
            raise ValueError("SICONFI pagination link has an invalid page parameter")
    return url


def _fetch_pages(url: str, endpoint: str, municipality_id: str | None,
                 year: int | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    global _last_request_at
    current = url
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    last_modified = None
    final_url = None
    for _page_number in range(PAGE_LIMIT):
        _validate_next_url(current, endpoint, municipality_id, year)
        if current in seen:
            raise ValueError("SICONFI pagination repeated a page")
        seen.add(current)
        delay = REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
        if delay > 0:
            time.sleep(delay)
        request = Request(current, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                            "Accept-Encoding": "gzip"})
        _last_request_at = time.monotonic()
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            payload = json.loads(_response_body(response).decode("utf-8"), parse_float=Decimal)
            last_modified = response.headers.get("Last-Modified") or last_modified
            final_url = response.geturl()
        _validate_next_url(final_url, endpoint, municipality_id, year)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ValueError("SICONFI response is missing an items list")
        if not isinstance(payload.get("hasMore"), bool):
            raise ValueError("SICONFI response is missing pagination completion status")
        for row in payload["items"]:
            if not isinstance(row, dict):
                raise ValueError("SICONFI response contains a malformed item")
            if endpoint == "/extrato_entregas":
                output.append(_public_delivery(row))
            elif endpoint == "/entes":
                output.append(_public_ente(row))
            else:
                output.append(_public_item(row))
        if payload["hasMore"] is False:
            break
        links = payload.get("links")
        if not isinstance(links, list):
            raise ValueError("SICONFI response has no valid pagination links")
        next_href = next((link.get("href") for link in links
                          if isinstance(link, dict) and link.get("rel") == "next"), None)
        if not next_href:
            raise ValueError("SICONFI response says more pages exist but has no next link")
        current = urljoin(current, str(next_href))
        _validate_next_url(current, endpoint, municipality_id, year)
    else:
        raise ValueError("SICONFI pagination exceeded the configured page limit")
    return output, {"lastModified": last_modified, "finalUrl": final_url}


def _page_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": items, "hasMore": False}


def _fetch_entes(destination: Path) -> dict[str, Any]:
    """Fetch and immediately project the official registry into its safe cache."""
    items, _meta = _fetch_pages(ENTES_URL, "/entes", None, None)
    return _cache_entes_payload(_page_payload(items), destination, _utc_now())


def _fetch_city(municipality_id: str, year: int, verified_identity: bool = False) -> dict[str, Any]:
    dca_url = DCA_URL.format(year=year, municipality_id=municipality_id)
    dca_items, dca_http = _fetch_pages(dca_url, "/dca", municipality_id, year)
    fetched_at = _utc_now()
    source = _source(dca_url, year, fetched_at, "available")
    dca_payload = _page_payload(dca_items)
    if dca_items:
        return _project_city_payloads(dca_payload, None, municipality_id, year, source, verified_identity)
    delivery_url = DELIVERIES_URL.format(year=year, municipality_id=municipality_id)
    delivery_items, delivery_http = _fetch_pages(delivery_url, "/extrato_entregas", municipality_id, year)
    source["fetchedAt"] = _utc_now()
    source["deliveryUrl"] = delivery_url
    source["lastModified"] = delivery_http.get("lastModified") or dca_http.get("lastModified")
    return _project_city_payloads(dca_payload, _page_payload(delivery_items), municipality_id, year,
                                 source, verified_identity)


def _cache_path(cache_dir: Path, municipality_id: str) -> Path:
    return cache_dir / f"{municipality_id}.json"


def _read_cache(path: Path, municipality_id: str, year: int) -> dict[str, Any] | None:
    value = _read_json(path, None)
    if not isinstance(value, dict) or str(value.get("id")) != municipality_id or value.get("year") != year:
        return None
    if value.get("status") not in {"available", "partial", "not_filed", "unavailable", "stale"}:
        return None
    return _normalize_cache_identity(value, municipality_id, year)


def _source_failure(path: Path, municipality_id: str, year: int, error: Exception) -> dict[str, Any]:
    previous = _read_cache(path, municipality_id, year)
    if previous and previous.get("status") in {"available", "partial", "not_filed", "stale"}:
        previous = dict(previous)
        previous["status"] = "stale"
        previous["message"] = "A atualização do Siconfi falhou; a observação local anterior foi preservada."
        source = previous.get("source") if isinstance(previous.get("source"), dict) else {}
        source = dict(source)
        source.update({
            "status": "stale",
            "attemptedAt": _utc_now(),
            "note": "A atualização falhou; os dados anteriores foram preservados.",
            "error": type(error).__name__,
        })
        previous["source"] = source
        for metric in previous.get("metrics", []):
            if isinstance(metric, dict) and isinstance(metric.get("source"), dict):
                metric["source"] = dict(source)
        _atomic_json(path, previous)
        return previous
    unavailable = {
        "year": year,
        "id": municipality_id,
        "status": "unavailable",
        "collectionComplete": False,
        "declaration": {"status": "unavailable"},
        "message": "A consulta ao Siconfi falhou; esta declaração permanece indisponível nesta base.",
        "metrics": [],
        "source": _source(DCA_URL.format(year=year, municipality_id=municipality_id), year,
                          None, "unavailable", type(error).__name__),
    }
    _atomic_json(path, unavailable)
    return unavailable


def _project_legacy_raw(raw_path: Path, deliveries_path: Path | None, municipality_id: str,
                        year: int, verified_identity: bool = False) -> dict[str, Any] | None:
    if not raw_path.exists():
        return None
    dca_payload = _read_json(raw_path, None)
    if not isinstance(dca_payload, dict):
        raise ValueError(f"Malformed cached SICONFI response for {municipality_id}")
    source = _source(DCA_URL.format(year=year, municipality_id=municipality_id), year,
                     _mtime_iso(raw_path), "cached")
    deliveries_payload = _read_json(deliveries_path, None) if deliveries_path and deliveries_path.exists() else None
    if deliveries_payload is not None:
        source["deliveryUrl"] = DELIVERIES_URL.format(year=year, municipality_id=municipality_id)
        source["fetchedAt"] = _mtime_iso(deliveries_path) or source["fetchedAt"]
    if not dca_payload.get("items") and deliveries_payload is None:
        return None
    return _project_city_payloads(dca_payload, deliveries_payload, municipality_id, year,
                                 source, verified_identity)


def _national_items_manifest(path: Path, year: int) -> dict[str, Any]:
    meta_path = path.with_name("items.meta.json")
    meta = _read_json(meta_path, {})
    if not isinstance(meta, dict):
        meta = {}
    valid = (
        meta.get("year") == year
        and meta.get("complete") is True
        and meta.get("status") in {"available", "cached", "imported"}
    )
    return {**meta, "complete": valid}


def _project_national_items(path: Path, year: int) -> dict[str, list[dict[str, Any]]]:
    """Read an optional safe JSONL cache; groups only selected financial rows."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not path.exists():
        return grouped
    for item in _read_jsonl(path):
        if str(item.get("exercicio", "")).strip() != str(year):
            continue
        municipality_id = str(item.get("cod_ibge", "")).strip()
        if not re.fullmatch(r"\d{7}", municipality_id):
            continue
        grouped[municipality_id].append(_public_item(item))
    return grouped


def _population_data(where: dict[str, Path], year: int) -> tuple[int | None, dict[str, int], dict[str, Any]]:
    from ingest.cities import _population_series

    path = where["population"]
    meta = _read_json(where["population_meta"], {})
    if not path.exists():
        path = where["legacy_population"]
        meta = _read_json(where["legacy_population_meta"], {})
    if not path.exists():
        return None, {}, {"label": "IBGE — Estimativas de população", "status": "unavailable",
                          "note": f"A população de referência de {year} ainda não foi carregada."}
    actual_year, values = _population_series(_read_json(path, []))
    if actual_year != year or not values:
        return actual_year, {}, {"label": "IBGE — Estimativas de população", "url": meta.get("url"),
                                 "period": actual_year, "fetchedAt": meta.get("fetchedAt") or _mtime_iso(path),
                                 "status": "unavailable", "note": f"A série de população não corresponde ao exercício {year}."}
    return actual_year, values, {
        "label": "IBGE — Estimativas de população residente por município",
        "url": meta.get("url") or POPULATION_URL.format(year=year),
        "period": f"referência de {year}",
        "fetchedAt": meta.get("fetchedAt") or _mtime_iso(path),
        "status": "cached",
    }


def _fetch_population(where: dict[str, Path], year: int) -> dict[str, Any]:
    """Fetch only the account comparison year; never touch cities' newer cache."""
    global _last_request_at
    url = POPULATION_URL.format(year=year)
    delay = REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
    if delay > 0:
        time.sleep(delay)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                    "Accept-Encoding": "gzip"})
    _last_request_at = time.monotonic()
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        payload = json.loads(_response_body(response).decode("utf-8"), parse_float=Decimal)
        last_modified = response.headers.get("Last-Modified")
    from ingest.cities import _population_series
    actual_year, values = _population_series(payload)
    if actual_year != year or not values:
        raise ValueError("IBGE population response has no observations for the requested year")
    _atomic_json(where["population"], payload)
    meta = {
        "url": url,
        "fetchedAt": _utc_now(),
        "status": "available",
        "year": year,
        "count": len(values),
        "lastModified": last_modified,
    }
    _atomic_json(where["population_meta"], meta)
    return meta


def _catalog(path: Path) -> list[dict[str, Any]]:
    value = _read_json(path, None)
    rows = value.get("municipalities") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("The national city catalog is unavailable; collect cities first.")
    output = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = str(row.get("id", ""))
        if not re.fullmatch(r"\d{7}", identifier) or identifier in seen:
            raise RuntimeError("The national city catalog has an invalid or duplicate IBGE code.")
        seen.add(identifier)
        output.append(row)
    return output


def _merge_previous_row(row: dict[str, Any] | None, source: dict[str, Any],
                        municipality_id: str, year: int) -> dict[str, Any] | None:
    if not isinstance(row, dict) or row.get("status") not in {"available", "partial", "not_filed", "stale"}:
        return None
    preserved = json.loads(json.dumps(row, ensure_ascii=False, default=str))
    preserved["id"] = municipality_id
    preserved["year"] = year
    preserved = _normalize_cache_identity(preserved, municipality_id, year)
    if preserved is None:
        return None
    if preserved.get("status") in {"available", "partial", "not_filed"}:
        preserved["status"] = "stale"
    preserved["message"] = "O cache desta cidade está ausente ou inválido; exibimos a observação anterior preservada."
    prior_source = preserved.get("source") if isinstance(preserved.get("source"), dict) else source
    prior_source = dict(prior_source)
    prior_source.update({"status": "stale", "note": preserved["message"]})
    preserved["source"] = prior_source
    for metric in preserved.get("metrics", []):
        if isinstance(metric, dict) and isinstance(metric.get("source"), dict):
            metric["source"] = dict(prior_source)
    return preserved


def _guard_replacement(previous: Any, replacement: dict[str, Any]) -> None:
    if not isinstance(previous, dict) or not isinstance(previous.get("municipalities"), dict):
        return
    if previous.get("year") != replacement.get("year"):
        return
    old = previous["municipalities"]
    new = replacement["municipalities"]
    observed_statuses = {"available", "partial", "not_filed", "stale"}
    old_observed_ids = {str(identifier) for identifier, row in old.items()
                        if isinstance(row, dict) and row.get("status") in observed_statuses}
    new_observed_ids = {str(identifier) for identifier, row in new.items()
                        if isinstance(row, dict) and row.get("status") in observed_statuses}
    previous_year = previous.get("year")
    unverified_nonfiling = {
        str(identifier)
        for identifier, row in old.items()
        if isinstance(row, dict) and row.get("status") == "not_filed"
        and row.get("identityVerified") is not True
        and _identity_evidence(row, str(identifier), previous_year) is None
    }
    corrected_nonfiling = {
        identifier for identifier in unverified_nonfiling
        if isinstance(new.get(identifier), dict) and new[identifier].get("status") == "unavailable"
    }
    lost_observed_ids = old_observed_ids - new_observed_ids
    correction_only = bool(lost_observed_ids) and lost_observed_ids.issubset(corrected_nonfiling)
    if lost_observed_ids and not correction_only:
        raise RuntimeError(
            f"Refusing to replace accounts snapshot with lower coverage ({len(new_observed_ids)} < {len(old_observed_ids)})."
        )
    previous_coverage = previous.get("coverage") if isinstance(previous.get("coverage"), dict) else {}
    if (previous_coverage.get("nationalCollectionComplete") is True
            and not replacement["coverage"]["nationalCollectionComplete"]
            and not correction_only):
        raise RuntimeError("Refusing to downgrade a complete accounts snapshot to an incomplete one.")


def build_snapshot(root: Path = ROOT, year: int = YEAR) -> dict[str, Any]:
    where = paths(root, year)
    catalog = _catalog(where["city_catalog"])
    verified_entities = _verified_ente_ids(where["entities"], catalog)
    population_year, population_values, population_source = _population_data(where, year)
    national_items = _project_national_items(where["national_items"], year)
    national_manifest = _national_items_manifest(where["national_items"], year)
    previous = _read_json(where["output"], None)
    previous_rows = (previous.get("municipalities", {})
                     if isinstance(previous, dict) and previous.get("year") == year else {})
    municipalities: dict[str, dict[str, Any]] = {}
    statuses: defaultdict[str, int] = defaultdict(int)
    fetched_times: list[str] = []
    sources_seen: list[dict[str, Any]] = []
    confirmed_ids: set[str] = set()

    for city in catalog:
        municipality_id = str(city["id"])
        if municipality_id in SPECIAL_MUNICIPALITIES:
            cache = {
                "status": "not_applicable",
                "message": SPECIAL_MUNICIPALITIES[municipality_id],
                "declaration": {"status": "not_applicable"},
                "metrics": [],
            }
        else:
            cache = _read_cache(_cache_path(where["cache_dir"], municipality_id), municipality_id, year)
            if cache is None and municipality_id in national_items:
                source = _source(SOURCE_DATASET_URL, year,
                                 national_manifest.get("fetchedAt") or _mtime_iso(where["national_items"]),
                                 "cached")
                if national_manifest.get("url"):
                    source["url"] = national_manifest["url"]
                cache = _project_dca_items(national_items[municipality_id], municipality_id, year, source,
                                           collection_complete=national_manifest["complete"])
            if cache is None:
                raw_path = root / "data" / "raw" / "siconfi" / f"dca_{year}_{municipality_id}.json"
                delivery_path = root / "data" / "raw" / "siconfi" / f"extrato_{year}_{municipality_id}.json"
                try:
                    cache = _project_legacy_raw(raw_path, delivery_path, municipality_id, year,
                                                municipality_id in verified_entities)
                except (OSError, ValueError, json.JSONDecodeError):
                    cache = None
                if cache is not None:
                    _atomic_json(_cache_path(where["cache_dir"], municipality_id), cache)
            if cache is None:
                prior_source = previous.get("source", {}) if isinstance(previous, dict) else {}
                cache = _merge_previous_row(previous_rows.get(municipality_id), prior_source,
                                            municipality_id, year)
            if cache is None:
                cache = {
                    "status": "unavailable",
                    "message": "Esta cidade ainda não tem uma consulta local completa nesta base.",
                    "declaration": {"status": "unavailable"},
                    "metrics": [],
                }
        cache["status"] = cache.get("status", "unavailable")
        _normalize_metric_labels(cache)
        row = {key: value for key, value in cache.items()
               if key in {"status", "message", "declaration", "metrics", "collectionComplete", "source",
                          "identityVerified", "identityEvidence"}}
        municipality_source = cache.get("source")
        if isinstance(municipality_source, dict):
            sources_seen.append(municipality_source)
            if municipality_source.get("fetchedAt"):
                fetched_times.append(str(municipality_source["fetchedAt"]))
        municipalities[municipality_id] = row
        statuses[row["status"]] += 1
        if (cache.get("collectionComplete") is True
                and cache.get("identityVerified") is True
                and row["status"] in {"available", "partial", "not_filed", "stale"}):
            confirmed_ids.add(municipality_id)

    municipal_count = sum(city["id"] not in SPECIAL_MUNICIPALITIES for city in catalog)
    completed_count = statuses["available"] + statuses["partial"] + statuses["not_filed"] + statuses["stale"]
    confirmed_complete = len(confirmed_ids)
    national_complete = confirmed_complete == municipal_count and municipal_count > 0
    usable_sources = [source for source in sources_seen
                      if source.get("status") in {"available", "cached", "imported", "stale"}]
    source_status = "cached" if usable_sources else "unavailable"
    if usable_sources and all(source.get("status") == "stale" for source in usable_sources):
        source_status = "stale"
    source_notes = []
    if not national_complete:
        source_notes.append(f"Coleta parcial: {confirmed_complete} de {municipal_count} municípios têm consulta completa ou extrato confirmado.")
    if statuses["stale"]:
        source_notes.append(f"A atualização falhou para {statuses['stale']} município(s); as observações anteriores foram preservadas.")
    source_note = " ".join(source_notes) or None
    source = _source(SOURCE_DATASET_URL, year, max(fetched_times) if fetched_times else None,
                     source_status, source_note)
    if source_status == "unavailable":
        source["note"] = "Nenhum cache Siconfi local foi encontrado; use --collect para consultar a fonte."

    snapshot = {
        "year": year,
        "generatedAt": _utc_now(),
        "source": source,
        "coverage": {
            "nationalCollectionComplete": national_complete,
            "nationalCollectionCompleteNote": "Indica cobertura confirmada em todo o universo aplicável; não mede atualização, indicada pelo status e pela data da fonte.",
            "municipalityCount": len(catalog),
            "applicableMunicipalityCount": municipal_count,
            "municipalitiesAvailable": statuses["available"],
            "municipalitiesPartial": statuses["partial"],
            "municipalitiesNotFiled": statuses["not_filed"],
            "municipalitiesUnavailable": statuses["unavailable"],
            "municipalitiesStale": statuses["stale"],
            "municipalitiesNotApplicable": statuses["not_applicable"],
            "municipalitiesObserved": completed_count,
            "municipalitiesConfirmedComplete": confirmed_complete,
        },
        "municipalities": municipalities,
        "population": {
            "year": population_year,
            "source": population_source,
            "municipalities": {str(key): value for key, value in population_values.items()},
        },
    }
    _guard_replacement(previous, snapshot)
    _atomic_json(where["output"], snapshot)
    return snapshot


def collect(root: Path = ROOT, year: int = YEAR, refresh: bool = False) -> dict[str, Any]:
    where = paths(root, year)
    catalog = _catalog(where["city_catalog"])
    verified_entities = _verified_ente_ids(where["entities"], catalog)
    if refresh or not verified_entities:
        try:
            _fetch_entes(where["entities"])
        except Exception:
            # An unavailable registry must not block other data collection or
            # replace a previously cached registry with an incomplete response.
            pass
        verified_entities = _verified_ente_ids(where["entities"], catalog)
    national_items = _project_national_items(where["national_items"], year)
    national_manifest = _national_items_manifest(where["national_items"], year)
    where["cache_dir"].mkdir(parents=True, exist_ok=True)
    cached_population_year, cached_population, _population_source = _population_data(where, year)
    if refresh or cached_population_year != year or not cached_population:
        try:
            _fetch_population(where, year)
        except Exception:
            # Missing population only disables peer comparisons; it does not
            # invalidate otherwise confirmed municipal declaration data.
            pass
    eligible = [city for city in catalog if str(city["id"]) not in SPECIAL_MUNICIPALITIES]
    total = len(eligible)
    for index, city in enumerate(eligible, 1):
        municipality_id = str(city["id"])
        cache_path = _cache_path(where["cache_dir"], municipality_id)
        prior = None if refresh else _read_cache(cache_path, municipality_id, year)
        if (prior is not None
                and prior.get("status") in {"available", "partial", "not_filed"}
                and prior.get("collectionComplete") is True
                and prior.get("identityVerified") is True):
            if index % 25 == 0 or index == total:
                print(f"siconfi: {index}/{total} municípios", flush=True)
            continue
        if municipality_id in national_items and national_manifest["complete"]:
            source = _source(SOURCE_DATASET_URL, year,
                             national_manifest.get("fetchedAt") or _mtime_iso(where["national_items"]),
                             "cached")
            if national_manifest.get("url"):
                source["url"] = national_manifest["url"]
            row = _project_dca_items(national_items[municipality_id], municipality_id, year, source,
                                     collection_complete=national_manifest["complete"])
            _atomic_json(cache_path, row)
            if index % 25 == 0 or index == total:
                print(f"siconfi: {index}/{total} municípios", flush=True)
            continue
        try:
            # Existing raw files are preserved. They were created by earlier
            # explicit collection and contain only public financial records.
            raw_path = root / "data" / "raw" / "siconfi" / f"dca_{year}_{municipality_id}.json"
            deliveries_path = root / "data" / "raw" / "siconfi" / f"extrato_{year}_{municipality_id}.json"
            row = None if refresh else _project_legacy_raw(raw_path, deliveries_path, municipality_id, year,
                                                           municipality_id in verified_entities)
            if row is None:
                row = _fetch_city(municipality_id, year, municipality_id in verified_entities)
            _atomic_json(cache_path, row)
        except Exception as error:
            _source_failure(cache_path, municipality_id, year, error)
        if index % 25 == 0 or index == total:
            print(f"siconfi: {index}/{total} municípios", flush=True)
    return build_snapshot(root, year)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monta uma fotografia offline das contas municipais no Siconfi")
    parser.add_argument("--collect", action="store_true", help="consulta caches locais e completa ausências na API oficial")
    parser.add_argument("--refresh", action="store_true", help="refaz as consultas já armazenadas; exige --collect")
    parser.add_argument("--year", type=int, default=YEAR, help="exercício DCA (padrão: 2025)")
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error("--refresh exige --collect")
    if args.year < 2014 or args.year > datetime.now(timezone.utc).year:
        parser.error("--year precisa ser um exercício disponível do Siconfi")
    snapshot = collect(year=args.year, refresh=args.refresh) if args.collect else build_snapshot(year=args.year)
    print("contas", json.dumps(snapshot["coverage"], ensure_ascii=False, sort_keys=True))
    print("fonte", json.dumps(snapshot["source"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
