import json
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingest import accounts


def metric_item(municipality_id, selector, value, *, year=2025, institution="Prefeitura Municipal de Teste - SP", **extra):
    row = {
        "exercicio": year,
        "cod_ibge": municipality_id,
        "instituicao": institution,
        **selector,
        "valor": value,
    }
    row.update(extra)
    return row


def full_dca(municipality_id="3550308"):
    specs = {spec["id"]: spec["selector"] for spec in accounts.METRIC_SPECS}
    return [
        metric_item(municipality_id, specs["revenue"], Decimal("100.25")),
        metric_item(municipality_id, specs["total-expense"], Decimal("90.01")),
        metric_item(municipality_id, specs["personnel"], Decimal("30.50")),
        metric_item(municipality_id, specs["health"], Decimal("15.25")),
        metric_item(municipality_id, specs["education"], Decimal("10.00")),
    ]


def paginated_payload(items):
    return {"items": items, "hasMore": False}


class JsonResponse:
    def __init__(self, payload, url):
        self.body = json.dumps(payload, default=str).encode("utf-8")
        self.url = url
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self):
        return self.body

    def geturl(self):
        return self.url


class AccountsCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.where = accounts.paths(self.root, 2025)

    def tearDown(self):
        self.temp.cleanup()

    def write_catalog(self, ids=("3550308", "3166600", "1111111", "5300108", "2605459")):
        path = self.where["city_catalog"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"municipalities": [{"id": item} for item in ids]}), encoding="utf-8")

    def write_population(self, values=None, year=2025):
        # Match the public IBGE aggregate response consumed by ingest.cities.
        values = values or {"3550308": 11, "3166600": 12}
        payload = [{"resultados": [{"series": [
            {"localidade": {"id": identifier}, "serie": {str(year): str(population)}}
            for identifier, population in values.items()
        ]}]}]
        path = self.where["population"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.where["population_meta"].write_text(json.dumps({
            "url": accounts.POPULATION_URL.format(year=year), "fetchedAt": "2026-10-07T12:00:00+00:00",
        }), encoding="utf-8")

    def test_financial_selectors_and_decimal_cents(self):
        source = accounts._source(accounts.SOURCE_DATASET_URL, 2025, "2026-10-07T12:00:00+00:00", "cached")
        row = accounts._project_dca_payload(paginated_payload(full_dca()), "3550308", 2025, source)
        self.assertEqual(row["status"], "available")
        self.assertEqual({metric["id"]: metric["amountCents"] for metric in row["metrics"]}, {
            "revenue": 10025,
            "total-expense": 9001,
            "personnel": 3050,
            "health": 1525,
            "education": 1000,
        })
        self.assertIn("intraorçamentária", row["metrics"][0]["label"])
        self.assertIn("intraorçamentária", row["metrics"][1]["label"])
        self.assertTrue(all(metric["source"]["url"] for metric in row["metrics"]))

    def test_missing_invalid_and_conflicting_values_are_null_not_zero_or_summed(self):
        items = full_dca()
        health_spec = next(spec["selector"] for spec in accounts.METRIC_SPECS if spec["id"] == "health")
        items.extend([
            metric_item("3550308", health_spec, Decimal("15.26")),
            metric_item("3550308", {**health_spec, "anexo": "wrong"}, Decimal("900.00")),
        ])
        items = [row for row in items if row["cod_conta"] != "DO3.1.00.00.00.00"]
        row = accounts._project_dca_items(items, "3550308", 2025, accounts._source("https://x", 2025, None, "available"))
        values = {metric["id"]: metric["amountCents"] for metric in row["metrics"]}
        self.assertEqual(row["status"], "partial")
        self.assertIsNone(values["health"])
        self.assertIsNone(values["personnel"])
        self.assertEqual(values["total-expense"], 9001)
        self.assertIsNone(accounts._amount_cents(Decimal("1.001")))
        self.assertIsNone(accounts._amount_cents("not-a-number"))
        self.assertIsNone(accounts._amount_cents(True))
        self.assertIsNone(accounts._amount_cents(None))
        self.assertEqual(accounts._amount_cents(Decimal("-0.01")), -1)
        self.assertEqual(accounts._amount_cents(Decimal("0.00")), 0)

    def test_only_municipal_institution_and_requested_year_are_projected(self):
        items = full_dca()
        items.extend(full_dca("3550308"))
        for row in items[-5:]:
            row["instituicao"] = "Câmara Municipal de Teste"
        items.append(metric_item("3550308", accounts.METRIC_SPECS[0]["selector"], 999, year=2024))
        projected = accounts._project_dca_items(items, "3550308", 2025, accounts._source("https://x", 2025, None, "available"))
        self.assertEqual(projected["metrics"][0]["amountCents"], 10025)
        self.assertEqual(projected["metrics"][1]["amountCents"], 9001)

    def test_empty_dca_requires_complete_delivery_registry_and_exact_ordinary_dca(self):
        source = accounts._source("https://x", 2025, None, "available")
        source["deliveryUrl"] = "https://siconfi.example/extrato_entregas?an_referencia=2025&id_ente=3550308"
        dca = paginated_payload([])
        with self.assertRaises(ValueError):
            accounts._project_city_payloads(dca, None, "3550308", 2025, source)
        deliveries = paginated_payload([
            {"cod_ibge": "3550308", "exercicio": 2025, "entregavel": "DCA", "periodo": 1, "status_relatorio": "HO"},
            {"cod_ibge": "3550308", "exercicio": 2025, "entregavel": "Balanço Anual (DCA)", "periodo": 2, "status_relatorio": "HO"},
            {"cod_ibge": "3550308", "exercicio": 2024, "entregavel": "Balanço Anual (DCA)", "periodo": 1, "status_relatorio": "HO"},
            {"cod_ibge": "3550308", "exercicio": 2025, "entregavel": "Balanço Anual (DCA)", "periodo": 1, "status_relatorio": "RE", "data_status": "2026-05-02T00:00:00Z"},
        ])
        row = accounts._project_city_payloads(dca, deliveries, "3550308", 2025, source)
        self.assertEqual(row["status"], "partial")
        self.assertEqual(row["declaration"], {"status": "submitted", "submittedAt": "2026-05-02T00:00:00Z"})
        other_city_record = paginated_payload([{
            "cod_ibge": "3550308", "exercicio": 2025, "entregavel": "RGF", "periodo": 2,
            "periodicidade": "Q", "status_relatorio": "HO",
        }])
        no_delivery = accounts._project_city_payloads(dca, other_city_record, "3550308", 2025, source)
        self.assertEqual(no_delivery["status"], "not_filed")
        self.assertIn("Não entregou ao Tesouro", no_delivery["message"])
        self.assertEqual(no_delivery["source"]["url"], source["deliveryUrl"])
        self.assertIn("Extrato de Entregas", no_delivery["source"]["label"])
        with self.assertRaises(ValueError):
            accounts._project_city_payloads(dca, {"items": [], "hasMore": True}, "3550308", 2025, source)

    def test_empty_dca_without_any_identity_evidence_is_unavailable(self):
        source = accounts._source("https://x", 2025, None, "available")
        source["deliveryUrl"] = "https://siconfi.example/extrato_entregas?an_referencia=2025&id_ente=3550308"
        row = accounts._project_city_payloads(paginated_payload([]), paginated_payload([]),
                                              "3550308", 2025, source)
        self.assertEqual(row["status"], "unavailable")
        self.assertFalse(row["collectionComplete"])
        self.assertFalse(row["identityVerified"])
        self.assertNotIn("Não entregou ao Tesouro", row["message"])
        self.assertIn("não confirma que este código", row["message"])

    def test_official_entes_cache_and_same_code_uf_sphere_verify_municipality(self):
        self.write_catalog(ids=("3550308", "3166600", "1111111"))
        rows = [
            {"cod_ibge": 3550308, "uf": "SP", "esfera": "M", "ente": "São Paulo", "co_cnpj": "not-cached"},
            {"cod_ibge": 3166600, "uf": "MG", "esfera": "M", "ente": "Serra da Saudade"},
            {"cod_ibge": 1111111, "uf": "RJ", "esfera": "M", "ente": "UF divergente"},
            {"cod_ibge": 1111111, "uf": "SP", "esfera": "E", "ente": "Esfera estadual"},
        ]
        cache = accounts._cache_entes_payload(paginated_payload(rows), self.where["entities"],
                                              "2026-10-07T12:00:00+00:00")
        self.assertNotIn("co_cnpj", json.dumps(cache))
        verified = accounts._verified_ente_ids(self.where["entities"], [
            {"id": "3550308", "uf": "SP"}, {"id": "3166600", "uf": "MG"}, {"id": "1111111", "uf": "SP"},
        ])
        self.assertEqual(verified, {"3550308", "3166600"})
        source = accounts._source("https://x", 2025, None, "available")
        source["deliveryUrl"] = "https://siconfi.example/extrato_entregas?an_referencia=2025&id_ente=3550308"
        filed = accounts._project_city_payloads(paginated_payload([]), paginated_payload([]),
                                                "3550308", 2025, source, verified_identity=True)
        self.assertEqual(filed["status"], "not_filed")
        self.assertTrue(filed["identityVerified"])
        self.assertTrue(filed["collectionComplete"])

    def test_empty_api_dca_reads_allowlisted_delivery_fields_and_marks_submitted(self):
        dca_url = accounts.DCA_URL.format(year=2025, municipality_id="3550308")
        deliveries_url = accounts.DELIVERIES_URL.format(year=2025, municipality_id="3550308")
        delivery = {
            "cod_ibge": 3550308,
            "exercicio": 2025,
            "entregavel": "Balanço Anual (DCA)",
            "periodo": 1,
            "periodicidade": "A",
            "status_relatorio": "HO",
            "data_status": "2026-04-20T00:00:00Z",
            "cnpj": "must-not-be-cached",
            "email": "must-not-be-cached",
        }
        responses = [
            JsonResponse({"items": [], "hasMore": False}, dca_url),
            JsonResponse({"items": [delivery], "hasMore": False}, deliveries_url),
        ]
        with patch.object(accounts, "REQUEST_INTERVAL_SECONDS", 0), \
                patch.object(accounts, "_last_request_at", 0), \
                patch.object(accounts, "urlopen", side_effect=responses) as request:
            row = accounts._fetch_city("3550308", 2025)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(row["status"], "partial")
        self.assertEqual(row["declaration"], {"status": "submitted", "submittedAt": "2026-04-20T00:00:00Z"})
        self.assertEqual(row["metrics"], [])
        self.assertEqual(row["source"]["url"], deliveries_url)
        self.assertIn("Extrato de Entregas", row["source"]["label"])
        self.assertNotIn("cnpj", row["source"])

    def test_paged_response_follows_only_valid_next_link_until_complete(self):
        first_url = accounts.DCA_URL.format(year=2025, municipality_id="3550308")
        second_url = first_url + "&offset=5000"
        responses = [
            JsonResponse({
                "items": [{"exercicio": 2025, "cod_ibge": 3550308, "valor": 1}],
                "hasMore": True,
                "links": [{"rel": "next", "href": second_url}],
            }, first_url),
            JsonResponse({
                "items": [{"exercicio": 2025, "cod_ibge": 3550308, "valor": 2}],
                "hasMore": False,
                "links": [],
            }, second_url),
        ]
        with patch.object(accounts, "REQUEST_INTERVAL_SECONDS", 0), \
                patch.object(accounts, "_last_request_at", 0), \
                patch.object(accounts, "urlopen", side_effect=responses) as request:
            items, meta = accounts._fetch_pages(first_url, "/dca", "3550308", 2025)
        self.assertEqual(request.call_count, 2)
        self.assertEqual([item["valor"] for item in items], [1, 2])
        self.assertEqual(meta["finalUrl"], second_url)

    def test_entes_fetch_uses_pagination_and_caches_only_allowlisted_fields(self):
        first_url = accounts.ENTES_URL
        second_url = accounts.SICONFI_BASE_URL + "/entes?limit=5000&offset=5000"
        responses = [
            JsonResponse({
                "items": [{
                    "cod_ibge": 3550308, "uf": "SP", "esfera": "M", "ente": "São Paulo",
                    "co_cnpj": "must-not-survive", "email": "must-not-survive",
                }],
                "hasMore": True,
                "links": [{"rel": "next", "href": second_url}],
            }, first_url),
            JsonResponse({
                "items": [{"cod_ibge": 3166600, "uf": "MG", "esfera": "M", "ente": "Serra da Saudade"}],
                "hasMore": False,
                "links": [],
            }, second_url),
        ]
        with patch.object(accounts, "REQUEST_INTERVAL_SECONDS", 0), \
                patch.object(accounts, "_last_request_at", 0), \
                patch.object(accounts, "urlopen", side_effect=responses) as request:
            cache = accounts._fetch_entes(self.where["entities"])
        self.assertEqual(request.call_count, 2)
        self.assertEqual([item["cod_ibge"] for item in cache["items"]], ["3550308", "3166600"])
        self.assertTrue(cache["complete"])
        serialized = self.where["entities"].read_text(encoding="utf-8")
        self.assertNotIn("co_cnpj", serialized)
        self.assertNotIn("must-not-survive", serialized)

    def test_collect_fetches_missing_registry_and_refreshes_existing_registry(self):
        city = {"id": "3550308", "name": "São Paulo", "uf": "SP"}
        catalog_path = self.where["city_catalog"]
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(json.dumps({"municipalities": [city]}), encoding="utf-8")

        def fetch_registry(_destination):
            return accounts._cache_entes_payload(paginated_payload([{
                "cod_ibge": 3550308, "uf": "SP", "esfera": "M", "ente": "São Paulo",
                "co_cnpj": "must-not-survive",
            }]), self.where["entities"], "2026-10-07T12:00:00+00:00")

        fetched_identity = []

        def fetch_city(municipality_id, year, verified_identity=False):
            fetched_identity.append(verified_identity)
            source = accounts._source(
                accounts.DCA_URL.format(year=year, municipality_id=municipality_id), year,
                "2026-10-07T12:00:00+00:00", "available",
            )
            source["deliveryUrl"] = accounts.DELIVERIES_URL.format(year=year, municipality_id=municipality_id)
            return accounts._project_city_payloads(
                paginated_payload([]), paginated_payload([]), municipality_id, year,
                source, verified_identity=verified_identity,
            )

        with patch.object(accounts, "_fetch_population", side_effect=OSError("offline")), \
                patch.object(accounts, "_fetch_entes", side_effect=fetch_registry) as registry_request, \
                patch.object(accounts, "_fetch_city", side_effect=fetch_city):
            first = accounts.collect(self.root, 2025)
            second = accounts.collect(self.root, 2025, refresh=True)

        self.assertEqual(registry_request.call_count, 2)
        self.assertEqual(fetched_identity, [True, True])
        self.assertTrue(first["coverage"]["nationalCollectionComplete"])
        self.assertTrue(second["coverage"]["nationalCollectionComplete"])
        self.assertNotIn("co_cnpj", self.where["entities"].read_text(encoding="utf-8"))

    def test_collect_fetches_requested_population_year_without_replacing_legacy_population(self):
        self.write_catalog(ids=("5300108",))
        legacy = self.where["legacy_population"]
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy_payload = [{"resultados": [{"series": [{
            "localidade": {"id": "5300108"}, "serie": {"2026": "3000000"},
        }]}]}]
        legacy.write_text(json.dumps(legacy_payload), encoding="utf-8")
        legacy_bytes = legacy.read_bytes()

        def fetch_population(_where, requested_year):
            self.assertEqual(requested_year, 2025)
            self.write_population({"5300108": 2900000}, year=requested_year)

        with patch.object(accounts, "_fetch_population", side_effect=fetch_population) as population_request, \
                patch.object(accounts, "_fetch_entes", return_value={}):
            snapshot = accounts.collect(self.root, 2025)

        population_request.assert_called_once()
        self.assertEqual(snapshot["population"]["year"], 2025)
        self.assertEqual(snapshot["population"]["municipalities"]["5300108"], 2900000)
        self.assertEqual(legacy.read_bytes(), legacy_bytes)

    def test_pagination_checks_host_path_and_requested_city_and_year(self):
        endpoint = "/dca"
        trusted = "https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt/dca?an_exercicio=2025&id_ente=3550308&offset=5000"
        self.assertEqual(accounts._validate_next_url(trusted, endpoint, "3550308", 2025), trusted)
        for bad in (
            "http://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt/dca?an_exercicio=2025&id_ente=3550308",
            "https://attacker.example/ords/cdwhprd/siconfi/tt/dca?an_exercicio=2025&id_ente=3550308",
            "https://apidatalake.tesouro.gov.br/elsewhere?an_exercicio=2025&id_ente=3550308",
            "https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt/dca?an_exercicio=2024&id_ente=3550308",
            "https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt/dca?an_exercicio=2025&id_ente=3166600",
        ):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                accounts._validate_next_url(bad, endpoint, "3550308", 2025)

    def test_failed_refresh_preserves_previous_metric_cache_as_stale(self):
        cache_path = accounts._cache_path(self.where["cache_dir"], "3550308")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        prior = accounts._project_dca_items(full_dca(), "3550308", 2025,
                                             accounts._source("https://x", 2025, "2026-10-01T00:00:00+00:00", "cached"))
        accounts._atomic_json(cache_path, prior)
        preserved = accounts._source_failure(cache_path, "3550308", 2025, TimeoutError())
        self.assertEqual(preserved["status"], "stale")
        self.assertEqual(preserved["metrics"][0]["amountCents"], 10025)
        self.assertEqual(preserved["source"]["status"], "stale")

    def test_unavailable_failure_does_not_become_a_stale_confirmed_observation(self):
        cache_path = accounts._cache_path(self.where["cache_dir"], "3550308")
        accounts._atomic_json(cache_path, {
            "year": 2025, "id": "3550308", "status": "unavailable",
            "declaration": {"status": "unavailable"}, "metrics": [],
        })
        result = accounts._source_failure(cache_path, "3550308", 2025, TimeoutError())
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["collectionComplete"])

    def test_old_unverified_nonfiling_cache_is_not_reused(self):
        cache_path = accounts._cache_path(self.where["cache_dir"], "3550308")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        old_row = {
            "year": 2025, "id": "3550308", "status": "not_filed",
            "declaration": {"status": "not_filed"}, "metrics": [],
            "collectionComplete": True,
            "source": accounts._source(
                accounts.DCA_URL.format(year=2025, municipality_id="3550308"), 2025,
                "2026-10-07T12:00:00+00:00", "cached",
            ),
        }
        accounts._atomic_json(cache_path, old_row)
        self.assertIsNone(accounts._read_cache(cache_path, "3550308", 2025))
        old_row["identityVerified"] = True
        old_row["identityEvidence"] = "registro válido no extrato do Siconfi"
        accounts._atomic_json(cache_path, old_row)
        self.assertEqual(accounts._read_cache(cache_path, "3550308", 2025)["status"], "not_filed")

    def test_offline_snapshot_uses_two_city_caches_and_marks_national_coverage_partial(self):
        self.write_catalog()
        self.write_population()
        self.where["cache_dir"].mkdir(parents=True)
        for city_id in ("3550308", "3166600"):
            row = accounts._project_dca_items(full_dca(city_id), city_id, 2025,
                                              accounts._source("https://x", 2025, "2026-10-07T12:00:00+00:00", "cached"))
            row["metrics"][0]["label"] = "Rótulo legado da receita"
            row["metrics"][1]["label"] = "Rótulo legado da despesa"
            if city_id == "3550308":
                row["metrics"][0]["classification"] = "legacy-classification"
                row["metrics"][0]["stage"] = "legacy-stage"
            accounts._atomic_json(accounts._cache_path(self.where["cache_dir"], city_id), row)
        snapshot = accounts.build_snapshot(self.root, 2025)
        self.assertFalse(snapshot["coverage"]["nationalCollectionComplete"])
        self.assertEqual(snapshot["coverage"]["municipalitiesAvailable"], 2)
        self.assertEqual(snapshot["coverage"]["municipalitiesUnavailable"], 1)
        self.assertEqual(snapshot["coverage"]["municipalitiesNotApplicable"], 2)
        self.assertEqual(snapshot["coverage"]["applicableMunicipalityCount"], 3)
        self.assertIn("não mede atualização", snapshot["coverage"]["nationalCollectionCompleteNote"])
        self.assertEqual(snapshot["municipalities"]["3550308"]["metrics"][0]["amountCents"], 10025)
        self.assertIn("intraorçamentária", snapshot["municipalities"]["3550308"]["metrics"][0]["label"])
        self.assertEqual(snapshot["municipalities"]["3550308"]["metrics"][0]["classification"], "legacy-classification")
        self.assertEqual(snapshot["municipalities"]["3550308"]["metrics"][0]["stage"], "legacy-stage")
        self.assertIn("intraorçamentária", snapshot["municipalities"]["3550308"]["metrics"][1]["label"])
        self.assertEqual(snapshot["municipalities"]["5300108"]["status"], "not_applicable")
        self.assertEqual(snapshot["population"]["year"], 2025)
        self.assertEqual(snapshot["population"]["source"]["status"], "cached")
        self.assertIsNotNone(json.loads(self.where["output"].read_text(encoding="utf-8")))

    def test_national_completeness_accumulates_verified_caches_and_excludes_special_rows(self):
        catalog = [
            {"id": "3550308", "name": "São Paulo", "uf": "SP"},
            {"id": "3166600", "name": "Serra da Saudade", "uf": "MG"},
            {"id": "5300108", "name": "Brasília", "uf": "DF"},
            {"id": "2605459", "name": "Fernando de Noronha", "uf": "PE"},
        ]
        catalog_path = self.where["city_catalog"]
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(json.dumps({"municipalities": catalog}), encoding="utf-8")
        registry = accounts._cache_entes_payload(paginated_payload([
            {"cod_ibge": 3550308, "uf": "SP", "esfera": "M", "ente": "São Paulo", "co_cnpj": "drop"},
            {"cod_ibge": 3166600, "uf": "MG", "esfera": "M", "ente": "Serra da Saudade"},
        ]), self.where["entities"], "2026-10-07T12:00:00+00:00")
        self.assertEqual(len(registry["items"]), 2)
        verified_ids = accounts._verified_ente_ids(self.where["entities"], catalog)
        self.assertEqual(verified_ids, {"3550308", "3166600"})
        self.where["cache_dir"].mkdir(parents=True, exist_ok=True)
        for city in catalog[:2]:
            city_id = city["id"]
            source = accounts._source(
                accounts.DCA_URL.format(year=2025, municipality_id=city_id), 2025,
                "2026-10-07T12:00:00+00:00", "cached",
            )
            source["deliveryUrl"] = accounts.DELIVERIES_URL.format(year=2025, municipality_id=city_id)
            row = accounts._project_city_payloads(
                paginated_payload([]), paginated_payload([]), city_id, 2025, source,
                verified_identity=city_id in verified_ids,
            )
            self.assertEqual(row["status"], "not_filed")
            accounts._atomic_json(accounts._cache_path(self.where["cache_dir"], city_id), row)

        snapshot = accounts.build_snapshot(self.root, 2025)
        coverage = snapshot["coverage"]
        self.assertEqual(coverage["municipalityCount"], 4)
        self.assertEqual(coverage["applicableMunicipalityCount"], 2)
        self.assertEqual(coverage["municipalitiesConfirmedComplete"], 2)
        self.assertEqual(coverage["municipalitiesNotFiled"], 2)
        self.assertEqual(coverage["municipalitiesNotApplicable"], 2)
        self.assertTrue(coverage["nationalCollectionComplete"])
        self.assertEqual(snapshot["municipalities"]["3550308"]["status"], "not_filed")
        self.assertEqual(snapshot["municipalities"]["3166600"]["status"], "not_filed")
        self.assertEqual(snapshot["municipalities"]["5300108"]["status"], "not_applicable")
        self.assertEqual(snapshot["municipalities"]["2605459"]["status"], "not_applicable")

    def test_complete_coverage_is_preserved_when_observed_city_cache_is_stale(self):
        self.write_catalog(ids=("3550308",))
        row = accounts._project_dca_items(full_dca(), "3550308", 2025, accounts._source(
            accounts.DCA_URL.format(year=2025, municipality_id="3550308"), 2025,
            "2026-10-06T12:00:00+00:00", "stale", "A atualização falhou; cache anterior preservado.",
        ))
        row["status"] = "stale"
        row["source"]["status"] = "stale"
        accounts._atomic_json(accounts._cache_path(self.where["cache_dir"], "3550308"), row)
        snapshot = accounts.build_snapshot(self.root, 2025)
        self.assertTrue(snapshot["coverage"]["nationalCollectionComplete"])
        self.assertEqual(snapshot["coverage"]["applicableMunicipalityCount"], 1)
        self.assertEqual(snapshot["source"]["status"], "stale")
        self.assertIn("não mede atualização", snapshot["coverage"]["nationalCollectionCompleteNote"])

    def test_snapshot_guard_refuses_coverage_regression(self):
        previous = {"coverage": {"nationalCollectionComplete": True}, "municipalities": {
            "3550308": {"status": "available"},
        }}
        replacement = {"coverage": {"nationalCollectionComplete": False}, "municipalities": {
            "3550308": {"status": "unavailable"},
        }}
        with self.assertRaises(RuntimeError):
            accounts._guard_replacement(previous, replacement)

    def test_snapshot_guard_allows_correcting_unverified_nonfiling_to_unavailable(self):
        previous = {
            "year": 2025,
            "coverage": {"nationalCollectionComplete": True},
            "municipalities": {
                "3550308": {"status": "not_filed", "message": "old unverified claim"},
                "3166600": {"status": "available", "identityVerified": True},
            },
        }
        replacement = {
            "year": 2025,
            "coverage": {"nationalCollectionComplete": False},
            "municipalities": {
                "3550308": {"status": "unavailable"},
                "3166600": {"status": "available", "identityVerified": True},
            },
        }
        accounts._guard_replacement(previous, replacement)

    def test_unrecognized_delivery_status_does_not_claim_nonfiling(self):
        payload = paginated_payload([{
            "cod_ibge": "3550308", "exercicio": 2025,
            "entregavel": "Balanço Anual (DCA)", "periodo": 1,
            "status_relatorio": "PENDING",
        }])
        status, date = accounts._extract_status(payload, "3550308", 2025)
        self.assertEqual(status, "unknown")
        self.assertIsNone(date)

    def test_national_jsonl_cache_is_allowlisted_and_stream_projected(self):
        path = self.where["national_items"]
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {**full_dca()[0], "cnpj": "must-not-survive", "email": "must-not-survive"}
        path.write_text(json.dumps(row, default=str) + "\n", encoding="utf-8")
        grouped = accounts._project_national_items(path, 2025)
        self.assertEqual(set(grouped), {"3550308"})
        self.assertNotIn("cnpj", grouped["3550308"][0])
        self.assertNotIn("email", grouped["3550308"][0])

    def test_national_rows_require_a_complete_year_manifest_for_national_coverage(self):
        self.write_catalog(ids=("3550308",))
        path = self.where["national_items"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, default=str) + "\n" for row in full_dca()), encoding="utf-8")
        partial = accounts.build_snapshot(self.root, 2025)
        self.assertEqual(partial["municipalities"]["3550308"]["status"], "partial")
        self.assertFalse(partial["coverage"]["nationalCollectionComplete"])
        self.where["national_items_meta"].write_text(json.dumps({
            "year": 2025, "complete": True, "status": "available", "fetchedAt": "2026-10-07T12:00:00+00:00",
        }), encoding="utf-8")
        complete = accounts.build_snapshot(self.root, 2025)
        self.assertEqual(complete["municipalities"]["3550308"]["status"], "available")
        self.assertTrue(complete["coverage"]["nationalCollectionComplete"])


if __name__ == "__main__":
    unittest.main()
