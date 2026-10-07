"""Municipal accounting declarations and population-band medians."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import re
from pathlib import Path

from .config import SNAPSHOTS_PATH
from .profiles import _load

SPECIAL_MUNICIPALITIES = {"5300108", "2605459"}
ELIGIBLE_STATUSES = {"available", "partial", "stale"}
EXCLUDED_STATUSES = {"unavailable", "not_filed", "not_applicable"}
MIN_PEER_SAMPLE = 3

POPULATION_BANDS = (
    {"id": "up_to_5000", "label": "Até 5.000 habitantes", "minPopulation": 1, "maxPopulation": 5_000},
    {"id": "5001_to_10000", "label": "De 5.001 a 10.000 habitantes", "minPopulation": 5_001, "maxPopulation": 10_000},
    {"id": "10001_to_20000", "label": "De 10.001 a 20.000 habitantes", "minPopulation": 10_001, "maxPopulation": 20_000},
    {"id": "20001_to_50000", "label": "De 20.001 a 50.000 habitantes", "minPopulation": 20_001, "maxPopulation": 50_000},
    {"id": "50001_to_100000", "label": "De 50.001 a 100.000 habitantes", "minPopulation": 50_001, "maxPopulation": 100_000},
    {"id": "100001_to_500000", "label": "De 100.001 a 500.000 habitantes", "minPopulation": 100_001, "maxPopulation": 500_000},
    {"id": "over_500000", "label": "Mais de 500.000 habitantes", "minPopulation": 500_001, "maxPopulation": None},
)

METRIC_FIELDS = ("id", "label", "amountCents", "classification", "stage", "source")


def _unavailable_comparison(message, population_year=None, population_source=None):
    return {
        "available": False,
        "message": message,
        "band": None,
        "populationYear": population_year,
        "populationSource": deepcopy(population_source),
        "universeCount": 0,
        "reportingCount": 0,
        "metrics": [],
        "method": "Medianas nacionais por faixa populacional; exclui a própria cidade, Brasília e Fernando de Noronha e exige ao menos três pares válidos por indicador.",
    }


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _population_band(value):
    if not _is_int(value) or value <= 0:
        return None
    return next((band for band in POPULATION_BANDS
                 if value >= band["minPopulation"]
                 and (band["maxPopulation"] is None or value <= band["maxPopulation"])), None)


def _source_is_available(source):
    return (isinstance(source, dict) and bool(source.get("url"))
            and source.get("status") in {"available", "cached", "imported", "stale"})


def _metric_source_is_available(metric, source):
    own_source = metric.get("source")
    if own_source is None:
        return _source_is_available(source)
    if isinstance(own_source, dict):
        return own_source.get("status") not in (None, "unavailable") and bool(own_source.get("url") or own_source.get("label"))
    return isinstance(own_source, str) and bool(own_source.strip())


def _public_metrics(row):
    values = row.get("metrics")
    if not isinstance(values, list):
        return []
    output = []
    for metric in values:
        if not isinstance(metric, dict) or not metric.get("id"):
            continue
        item = {field: deepcopy(metric[field]) for field in METRIC_FIELDS if field in metric}
        amount = item.get("amountCents")
        if amount is not None and not _is_int(amount):
            item["amountCents"] = None
        output.append(item)
    return output


def _median_cents(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    midpoint = (Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) / Decimal(2)
    return int(midpoint.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _eligible_account(row, source):
    if not isinstance(row, dict) or row.get("status") not in ELIGIBLE_STATUSES:
        return False
    declaration = row.get("declaration")
    if isinstance(declaration, dict) and declaration.get("status") in EXCLUDED_STATUSES:
        return False
    return _source_is_available(source)


def _has_reported_amount(row, source):
    return any(_is_int(metric.get("amountCents")) and _metric_source_is_available(metric, source)
               for metric in _public_metrics(row))


def _comparison(identifier, row, snapshot, source):
    coverage = snapshot.get("coverage") if isinstance(snapshot.get("coverage"), dict) else {}
    population = snapshot.get("population") if isinstance(snapshot.get("population"), dict) else {}
    population_year = population.get("year") if _is_int(population.get("year")) else None
    population_source = population.get("source")
    population_rows = population.get("municipalities")
    if not isinstance(population_rows, dict):
        population_rows = {}

    if coverage.get("nationalCollectionComplete") is not True:
        return _unavailable_comparison(
            "A comparação fica indisponível enquanto a coleta nacional não estiver completa.",
            population_year, population_source,
        )
    if not _source_is_available(source):
        return _unavailable_comparison(
            "A fonte das declarações não está disponível para formar uma comparação nacional.",
            population_year, population_source,
        )
    if (not isinstance(row, dict) or row.get("status") not in ELIGIBLE_STATUSES
            or (isinstance(row.get("declaration"), dict)
                and row["declaration"].get("status") in EXCLUDED_STATUSES)):
        return _unavailable_comparison(
            "Esta declaração não tem valores disponíveis para comparação.",
            population_year, population_source,
        )
    if (population_year != snapshot.get("year") or not _source_is_available(population_source)):
        return _unavailable_comparison(
            "A população do mesmo exercício não está disponível para comparação.", population_year, population_source,
        )
    if identifier in SPECIAL_MUNICIPALITIES:
        return _unavailable_comparison(
            "Esta localidade não integra a comparação entre municípios.", population_year, population_source,
        )

    selected_population = population_rows.get(identifier)
    band = _population_band(selected_population)
    if band is None:
        return _unavailable_comparison(
            "Não há população válida para definir a faixa de comparação desta cidade.",
            population_year, population_source,
        )

    city_rows = snapshot.get("municipalities")
    if not isinstance(city_rows, dict):
        city_rows = {}
    universe_ids = []
    for city_id, population_value in population_rows.items():
        if not re.fullmatch(r"\d{7}", str(city_id)) or city_id == identifier or city_id in SPECIAL_MUNICIPALITIES:
            continue
        peer_band = _population_band(population_value)
        if peer_band and peer_band["id"] == band["id"]:
            universe_ids.append(str(city_id))

    peers = []
    for city_id in universe_ids:
        peer = city_rows.get(city_id)
        if not _eligible_account(peer, source) or not _has_reported_amount(peer, source):
            continue
        peers.append((city_id, peer))

    comparison_metrics = []
    local_metrics = _public_metrics(row)
    for metric in local_metrics:
        metric_id = str(metric.get("id"))
        if not _is_int(metric.get("amountCents")) or not _metric_source_is_available(metric, source):
            continue
        peer_values = []
        for _peer_id, peer in peers:
            peer_metrics = [candidate for candidate in _public_metrics(peer)
                            if str(candidate.get("id")) == metric_id
                            and candidate.get("stage") == metric.get("stage")
                            and candidate.get("classification") == metric.get("classification")
                            and _is_int(candidate.get("amountCents"))
                            and _metric_source_is_available(candidate, source)]
            # A municipality contributes at most one observation per metric.
            if len(peer_metrics) == 1:
                peer_values.append(peer_metrics[0]["amountCents"])
        sample_size = len(peer_values)
        comparison_metrics.append({
            "id": metric_id,
            "medianCents": _median_cents(peer_values) if sample_size >= MIN_PEER_SAMPLE else None,
            "sampleSize": sample_size,
            **({} if sample_size >= MIN_PEER_SAMPLE else {
                "message": f"A mediana exige ao menos {MIN_PEER_SAMPLE} cidades comparáveis com este indicador."
            }),
        })

    available = any(metric["medianCents"] is not None for metric in comparison_metrics)
    message = (
        "Medianas calculadas com municípios da mesma faixa populacional; são referências descritivas."
        if available else
        "Ainda não há ao menos três cidades comparáveis com valores válidos para os indicadores desta declaração."
    )
    return {
        "available": available,
        "message": message,
        "band": deepcopy(band),
        "populationYear": population_year,
        "populationSource": deepcopy(population_source),
        "universeCount": len(universe_ids),
        "reportingCount": len(peers),
        "metrics": comparison_metrics,
        "method": "Mediana dos valores declarados no mesmo exercício e faixa populacional; a própria cidade, Brasília e Fernando de Noronha são excluídas. Cada indicador exige ao menos três outros municípios com dado válido. A mediana é o valor central do grupo; não é uma meta de gasto nem um ranking.",
    }


def _message_for(status, row, source):
    message = row.get("message") if isinstance(row, dict) else None
    if status == "not_filed":
        return message or "Não entregou ao Tesouro."
    if status == "not_applicable":
        return message or "Esta localidade não se aplica a esta prestação de contas."
    if status == "partial":
        return message or "A declaração está parcialmente disponível; alguns valores não foram informados."
    if status == "stale":
        return message or source.get("note") or "A fonte não foi atualizada; exibimos os dados locais preservados."
    if status == "unavailable":
        return message or "A declaração não está disponível nesta base. Ausência de dados não confirma entrega nem falta de entrega."
    return message or "Declaração municipal disponível nesta base."


def detail(identifier, snapshot_path=None):
    """Return one city's account declaration and a same-year population comparison."""
    if not re.fullmatch(r"\d{7}", str(identifier or "")):
        return None
    path = Path(snapshot_path) if snapshot_path is not None else SNAPSHOTS_PATH / "accounts.json"
    snapshot = _load(path)
    snapshot = snapshot if isinstance(snapshot, dict) else None
    if snapshot is None:
        source = {
            "label": "Declarações municipais ao Tesouro",
            "status": "unavailable",
            "note": "A fotografia local de declarações municipais está indisponível.",
        }
        return {
            "year": None,
            "status": "unavailable",
            "message": source["note"],
            "source": source,
            "declaration": {"status": "unavailable"},
            "metrics": [],
            "comparison": _unavailable_comparison(
                "A declaração não está disponível para comparação.",
            ),
        }

    source = snapshot.get("source")
    if not isinstance(source, dict):
        source = {"label": "Declarações municipais ao Tesouro", "status": "unavailable",
                  "note": "A fonte das declarações não está identificada nesta fotografia."}
    municipalities = snapshot.get("municipalities")
    if not isinstance(municipalities, dict):
        municipalities = {}
    row = municipalities.get(str(identifier))
    if not isinstance(row, dict):
        row = None

    display_source = row.get("source") if isinstance(row, dict) else None
    if not isinstance(display_source, dict):
        display_source = source

    if not _source_is_available(source):
        status = "unavailable"
        declaration = {"status": "unavailable"}
        metrics = []
        message = source.get("note") or "A fonte das declarações não está disponível nesta base."
        comparison = _unavailable_comparison(
            "A fonte das declarações não está disponível para formar uma comparação nacional.",
            snapshot.get("population", {}).get("year") if isinstance(snapshot.get("population"), dict) else None,
            snapshot.get("population", {}).get("source") if isinstance(snapshot.get("population"), dict) else None,
        )
    elif row is None:
        status = "unavailable"
        declaration = {"status": "unavailable"}
        metrics = []
        message = "Não há um registro de declaração para esta cidade nesta fotografia. Ausência de dados não confirma entrega nem falta de entrega."
        comparison = _unavailable_comparison(
            "Não há um registro local para comparar.",
            snapshot.get("population", {}).get("year") if isinstance(snapshot.get("population"), dict) else None,
            snapshot.get("population", {}).get("source") if isinstance(snapshot.get("population"), dict) else None,
        )
    else:
        status = row.get("status") if row.get("status") in {
            "available", "partial", "unavailable", "not_filed", "not_applicable", "stale"
        } else "unavailable"
        declaration_value = row.get("declaration")
        declaration = deepcopy(declaration_value) if isinstance(declaration_value, dict) else {"status": status}
        metrics = _public_metrics(row)
        message = _message_for(status, row, display_source)
        comparison = _comparison(str(identifier), row, snapshot, source)
        if source.get("status") == "stale" and status in {"available", "partial"}:
            status = "stale"
            message = source.get("note") or "A fonte não foi atualizada; exibimos os dados locais preservados."

    return {
        "year": snapshot.get("year") if _is_int(snapshot.get("year")) else None,
        "status": status,
        "message": message,
        "source": deepcopy(display_source),
        "declaration": declaration,
        "metrics": metrics,
        "comparison": comparison,
    }
