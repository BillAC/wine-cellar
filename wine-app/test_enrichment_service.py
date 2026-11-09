import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import enrichment_service


class WineEnrichmentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_path = Path(self.temp_dir.name) / "cache.json"
        self.usage_path = Path(self.temp_dir.name) / "usage.json"
        self.cache_patch = patch.object(
            enrichment_service, "CACHE_FILE", str(self.cache_path)
        )
        self.usage_patch = patch.object(
            enrichment_service, "USAGE_FILE", str(self.usage_path)
        )
        self.cache_patch.start()
        self.usage_patch.start()
        self.addCleanup(self.cache_patch.stop)
        self.addCleanup(self.usage_patch.stop)

    def test_mock_results_are_not_cached_as_real_lookup_results(self):
        with patch.dict(
            os.environ,
            {"GRAPEMINDS_MOCK_MODE": "true"},
            clear=False,
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors("Example Estate", "Pinot Noir")

        self.assertIn("[MOCK DATA]", result["notes"])
        self.assertEqual(status, "mock")
        self.assertEqual(json.loads(self.cache_path.read_text()), {})

    def test_lookup_by_id_fetches_and_maps_the_exact_grapeminds_record(self):
        response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": {
                        "id": 12345,
                        "name": "Estate Pinot Noir",
                        "producer": {"name": "Example Estate"},
                        "region": {"name": "Willamette Valley"},
                        "country_of_origin": "us",
                        "grapes": [{"name": "Pinot Noir"}],
                        "description": {"text": "Bright red fruit."},
                    }
                }
            ),
        )
        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch("enrichment_service.requests.get", return_value=response) as get,
        ):
            service = enrichment_service.WineEnrichmentService()
            metadata, status = service.enrich_by_id("12345")

        get.assert_called_once()
        self.assertEqual(
            get.call_args.args[0],
            "https://api.grapeminds.eu/public/v1/wines/12345",
        )
        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["Accept-Language"], "en")
        self.assertEqual(get.call_args.kwargs["timeout"], 15)
        self.assertEqual(status, "updated")
        self.assertEqual(metadata["id"], "12345")
        self.assertEqual(metadata["name"], "Estate Pinot Noir")
        self.assertEqual(metadata["winery"], "Example Estate")
        self.assertEqual(metadata["grape_type"], "Pinot Noir")
        self.assertEqual(metadata["country_of_origin"], "United States")

    def test_live_lookup_replaces_a_previously_cached_mock_result(self):
        cache_key = "example estate|pinot noir"
        self.cache_path.write_text(
            json.dumps(
                {
                    cache_key: {
                        "region": "Mock Region",
                        "grape_type": "Mock Grape",
                        "notes": "[MOCK DATA] No real API call was made.",
                    }
                }
            )
        )
        response = Mock(
            status_code=200,
            json=Mock(
                return_value=[
                    {
                        "display_name": "Example Estate, Pinot Noir",
                        "producer": {"name": "Example Estate"},
                        "region": "Real Region",
                        "grape_variety": "Real Grape",
                        "drinking_window": "2025-2035",
                        "description": "Live Grapeminds result",
                    }
                ]
            ),
        )

        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch("enrichment_service.requests.get", return_value=response) as get,
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors("Example Estate", "Pinot Noir")

        get.assert_called_once()
        self.assertEqual(status, "updated")
        self.assertEqual(result["region"], "Real Region")
        self.assertEqual(result["grape_type"], "Real Grape")
        self.assertNotIn("[MOCK DATA]", result["notes"])
        self.assertEqual(json.loads(self.cache_path.read_text())[cache_key]["region"], "Real Region")

    def test_forced_refresh_queries_grapeminds_for_cached_real_results(self):
        cache_key = "example estate|pinot noir"
        self.cache_path.write_text(
            json.dumps(
                {
                    cache_key: {
                        "region": "Old Region",
                        "grape_type": "Old Grape",
                        "notes": "Previous real result",
                    }
                }
            )
        )
        response = Mock(
            status_code=200,
            json=Mock(
                return_value=[
                    {
                        "display_name": "Example Estate, Pinot Noir",
                        "producer": {"name": "Example Estate"},
                        "region": "Fresh Region",
                        "grape_variety": "Fresh Grape",
                        "drinking_window": None,
                        "description": "Fresh result",
                    }
                ]
            ),
        )

        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch("enrichment_service.requests.get", return_value=response) as get,
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors(
                "Example Estate", "Pinot Noir", force_refresh=True
            )

        get.assert_called_once()
        self.assertEqual(status, "updated")
        self.assertEqual(result["region"], "Fresh Region")
        self.assertEqual(result["grape_type"], "Fresh Grape")

    def test_live_lookup_uses_documented_endpoint_and_maps_api_response(self):
        response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": [
                        {
                            "display_name": "Example Estate, Estate Pinot",
                            "producer": {
                                "name": "Example Estate",
                                "display_name": "Example Estate",
                            },
                            "region": {"name": "Napa Valley"},
                            "country_of_origin": "us",
                            "grape_varieties": [
                                {"name": "Cabernet Sauvignon"},
                                {"name": "Merlot"},
                            ],
                            "vintage": 2020,
                            "drinking_window": "2024-2035",
                            "description": "A structured wine description.",
                        }
                    ],
                    "meta": {"current_page": 1, "total": 1},
                }
            ),
        )
        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch("enrichment_service.requests.get", return_value=response) as get,
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors(
                "Example Estate", "Estate Pinot", force_refresh=True
            )

        request = get.call_args
        self.assertEqual(
            request.args[0],
            "https://api.grapeminds.eu/public/v1/wines/search",
        )
        self.assertEqual(
            request.kwargs["params"],
            {"q": "Estate Pinot", "limit": 50},
        )
        self.assertEqual(
            request.kwargs["headers"]["Authorization"],
            "Bearer test-key",
        )
        self.assertEqual(status, "updated")
        self.assertEqual(result["name"], "Estate Pinot")
        self.assertEqual(result["winery"], "Example Estate")
        self.assertEqual(result["region"], "Napa Valley")
        self.assertEqual(result["country_of_origin"], "United States")
        self.assertEqual(
            result["grape_type"],
            "Cabernet Sauvignon, Merlot",
        )
        self.assertEqual(result["vintage"], 2020)

    def test_little_eagle_label_matches_catalog_name_and_fetches_details(self):
        search_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": [
                        {
                            "id": 346681,
                            "display_name": (
                                "Eagles' Nest, Little Eagle Merlot, Constantia"
                            ),
                        }
                    ]
                }
            ),
        )
        detail_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": {
                        "id": 346681,
                        "display_name": (
                            "Eagles' Nest, Little Eagle Merlot, Constantia"
                        ),
                        "color": "red",
                        "producer": {"display_name": "Eagles' Nest"},
                        "region": {"name": "Constantia", "country": "za"},
                        "grapes": [],
                        "description": None,
                        "pairing": None,
                        "tasting_notes": None,
                        "flavor_profile": None,
                    }
                }
            ),
        )

        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch(
                "enrichment_service.requests.get",
                side_effect=[search_response, detail_response],
            ) as get,
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors(
                "Eagles' Nest Wines", "The Little Eagle Red", force_refresh=True
            )

        self.assertEqual(status, "updated")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(
            get.call_args_list[0].kwargs["params"],
            {"q": "Little Eagle", "limit": 50},
        )
        self.assertEqual(
            get.call_args_list[0].kwargs["headers"]["Accept-Language"],
            "en",
        )
        self.assertEqual(get.call_args_list[1].args[0].endswith("/wines/346681"), True)
        self.assertEqual(result["winery"], "Eagles' Nest")
        self.assertEqual(result["name"], "Little Eagle Merlot")
        self.assertEqual(result["region"], "Constantia")
        self.assertEqual(result["country_of_origin"], "South Africa")
        self.assertEqual(result["color"], "red")
        self.assertIsNone(result["vintage"])
        self.assertIsNone(result["grape_type"])

    def test_local_model_selects_from_grapeminds_candidates_when_exact_match_fails(self):
        search_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": [
                        {
                            "id": 10,
                            "display_name": "Emiliana, Natura Cabernet Sauvignon, Chile",
                            "color": "red",
                        },
                        {
                            "id": 20,
                            "display_name": "Emiliana, Natura Chardonnay, Chile",
                            "color": "white",
                        },
                    ]
                }
            ),
        )
        detail_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": {
                        "id": 20,
                        "display_name": "Emiliana, Natura Chardonnay, Chile",
                        "producer": {"display_name": "Emiliana"},
                        "region": {"name": "Chile", "country": "cl"},
                        "grapes": [{"name": "Chardonnay"}],
                        "color": "white",
                    }
                }
            ),
        )
        selector = Mock(return_value=20)
        verifier = Mock(return_value=True)

        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch(
                "enrichment_service.requests.get",
                side_effect=[search_response, detail_response],
            ) as get,
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors(
                "EMILIANA",
                "NATURA CHARDONNAY UN-OAKED",
                force_refresh=True,
                identification_context={
                    "country_of_origin": "Chile",
                    "grape_type": "Chardonnay",
                    "vintage": 2019,
                },
                candidate_selector=selector,
                candidate_verifier=verifier,
            )

        self.assertEqual(status, "updated")
        selector.assert_called_once()
        anchors, candidates = selector.call_args.args
        self.assertEqual(anchors["country_of_origin"], "Chile")
        self.assertEqual(anchors["grape_type"], "Chardonnay")
        self.assertEqual([candidate["id"] for candidate in candidates], [10, 20])
        self.assertEqual(result["name"], "Natura Chardonnay")
        self.assertEqual(result["country_of_origin"], "Chile")
        self.assertEqual(result["grape_type"], "Chardonnay")
        self.assertEqual(get.call_args_list[1].args[0].endswith("/wines/20"), True)
        verifier.assert_called_once()

    def test_local_model_cannot_select_candidate_outside_search_results(self):
        response = Mock(
            status_code=200,
            json=Mock(
                return_value={"data": [{"id": 10, "display_name": "Unrelated Wine"}]}
            ),
        )
        selector = Mock(return_value=999)
        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch("enrichment_service.requests.get", return_value=response) as get,
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors(
                "Example Producer",
                "Expected Wine",
                force_refresh=True,
                candidate_selector=selector,
            )

        self.assertIsNone(result)
        self.assertEqual(status, "matcher_error")
        get.assert_called_once()

    def test_selected_candidate_with_conflicting_country_is_rejected(self):
        search_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": [
                        {
                            "id": 20,
                            "display_name": "Fuego Blanco, Nature Chardonnay, Pedernal",
                        }
                    ]
                }
            ),
        )
        detail_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": {
                        "id": 20,
                        "display_name": "Fuego Blanco, Nature Chardonnay, Pedernal",
                        "producer": {"display_name": "Fuego Blanco"},
                        "region": {"name": "Pedernal", "country": "ar"},
                        "grapes": [{"name": "Chardonnay"}],
                    }
                }
            ),
        )
        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch(
                "enrichment_service.requests.get",
                side_effect=[search_response, detail_response],
            ),
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors(
                "EMILIANA",
                "NATURA CHARDONNAY UN-OAKED",
                force_refresh=True,
                identification_context={
                    "country_of_origin": "CHILE",
                    "grape_type": "Chardonnay",
                },
                candidate_selector=Mock(return_value=20),
            )

        self.assertIsNone(result)
        self.assertEqual(status, "no_match")

    def test_local_model_can_reject_fetched_candidate_details(self):
        search_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": [{"id": 20, "display_name": "Natura Chardonnay, Chile"}]
                }
            ),
        )
        detail_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": {
                        "id": 20,
                        "display_name": "Natura Chardonnay, Chile",
                        "producer": {"display_name": "Emiliana"},
                        "region": {"name": "Chile", "country": "cl"},
                        "grapes": [{"name": "Chardonnay"}],
                    }
                }
            ),
        )
        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch(
                "enrichment_service.requests.get",
                side_effect=[search_response, detail_response],
            ),
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors(
                "Emiliana",
                "Natura Chardonnay",
                force_refresh=True,
                candidate_selector=Mock(return_value=20),
                candidate_verifier=Mock(return_value=False),
            )

        self.assertIsNone(result)
        self.assertEqual(status, "no_match")

    def test_selected_candidate_with_weak_name_overlap_is_rejected(self):
        self.assertFalse(
            enrichment_service.WineEnrichmentService._is_consistent_with_anchors(
                {
                    "name": "Nature Chardonnay",
                    "country_of_origin": None,
                    "grape_type": "Chardonnay",
                },
                "NATURA CHARDONNAY UN-OAKED",
                {"country_of_origin": "Chile", "grape_type": "Chardonnay"},
            )
        )

    def test_search_result_by_display_name_then_fetches_wine_details(self):
        search_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": [
                        {
                            "id": 114565,
                            "display_name": "Meerlust, Rubicon Stellenbosch",
                        }
                    ],
                    "meta": {"total": 1},
                }
            ),
        )
        detail_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": {
                        "id": 114565,
                        "display_name": "Meerlust, Rubicon Stellenbosch",
                        "producer": {
                            "id": 2794,
                            "name": "Meerlust",
                            "display_name": "Meerlust",
                        },
                        "region": {"id": 317, "name": "Stellenbosch"},
                        "country": "za",
                        "grapes": [
                            {"id": 353283, "name": "Cabernet Franc"},
                            {"id": 353265, "name": "Cabernet Sauvignon"},
                            {"id": 353274, "name": "Merlot"},
                            {"id": 353292, "name": "Petit Verdot"},
                        ],
                        "color": "red",
                        "description": {"text": "A South African Bordeaux blend."},
                        "pairing": {"text": "Slow-braised lamb."},
                        "tasting_notes": {"text": "Dark fruit and cedar."},
                        "flavor_profile": {
                            "sweetness": 1,
                            "acidity": 6,
                            "tannins": 7,
                            "body": 7,
                        },
                    }
                }
            ),
        )
        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch(
                "enrichment_service.requests.get",
                side_effect=[search_response, detail_response],
            ) as get,
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors(
                None, "Rubicon", force_refresh=True
            )

        self.assertEqual(status, "updated")
        self.assertEqual(result["winery"], "Meerlust")
        self.assertEqual(result["name"], "Rubicon")
        self.assertEqual(result["region"], "Stellenbosch")
        self.assertEqual(result["country_of_origin"], "South Africa")
        self.assertEqual(
            result["grape_type"],
            "Cabernet Franc, Cabernet Sauvignon, Merlot, Petit Verdot",
        )
        self.assertEqual(result["color"], "red")
        self.assertEqual(
            result["grape_varieties"],
            [
                {"id": 353283, "name": "Cabernet Franc"},
                {"id": 353265, "name": "Cabernet Sauvignon"},
                {"id": 353274, "name": "Merlot"},
                {"id": 353292, "name": "Petit Verdot"},
            ],
        )
        self.assertEqual(result["description"], {"text": "A South African Bordeaux blend."})
        self.assertEqual(result["pairing"], {"text": "Slow-braised lamb."})
        self.assertEqual(
            result["grapeminds_tasting_notes"],
            {"text": "Dark fruit and cedar."},
        )
        self.assertEqual(result["flavor_profile"]["tannins"], 7)
        self.assertEqual(result["notes"], "A South African Bordeaux blend.")
        self.assertEqual(
            [call.args[0] for call in get.call_args_list],
            [
                "https://api.grapeminds.eu/public/v1/wines/search",
                "https://api.grapeminds.eu/public/v1/wines/114565",
            ],
        )
        self.assertEqual(
            get.call_args_list[0].kwargs["params"],
            {"q": "Rubicon", "limit": 50},
        )

    def test_meerlust_estate_label_anchor_matches_meerlust_catalog_entry(self):
        match = {
            "id": 114565,
            "display_name": "Meerlust, Rubicon Stellenbosch",
        }

        self.assertTrue(
            enrichment_service.WineEnrichmentService._is_matching_wine(
                match,
                "MEERLUST ESTATE",
                "Rubicon",
            )
        )

    def test_missing_detail_fields_keep_search_metadata(self):
        search_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": [
                        {
                            "id": 123,
                            "display_name": "Example Estate, Pinot Noir",
                            "producer": {"name": "Example Estate"},
                            "region": {"name": "Willamette Valley"},
                            "grapes": [{"name": "Pinot Noir"}],
                            "color": "red",
                        }
                    ]
                }
            ),
        )
        detail_response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": {
                        "id": 123,
                        "display_name": "Example Estate, Pinot Noir",
                        "producer": {"name": "Example Estate"},
                    }
                }
            ),
        )

        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch(
                "enrichment_service.requests.get",
                side_effect=[search_response, detail_response],
            ),
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors(
                "Example Estate", "Pinot Noir", force_refresh=True
            )

        self.assertEqual(status, "updated")
        self.assertEqual(result["region"], "Willamette Valley")
        self.assertEqual(result["grape_varieties"], [{"name": "Pinot Noir"}])
        self.assertEqual(result["color"], "red")

    def test_live_lookup_reports_http_error_status(self):
        response = Mock(status_code=401)
        with (
            patch.dict(
                os.environ,
                {
                    "GRAPEMINDS_API_KEY": "test-key",
                    "GRAPEMINDS_MOCK_MODE": "false",
                },
                clear=False,
            ),
            patch("enrichment_service.requests.get", return_value=response),
        ):
            service = enrichment_service.WineEnrichmentService()
            result, status = service.enrich_from_anchors(
                "Example Estate", "Estate Pinot", force_refresh=True
            )

        self.assertIsNone(result)
        self.assertEqual(status, "http_401")

    def test_starts_without_an_api_key_and_skips_live_lookups(self):
        with (
            patch.dict(os.environ, {"GRAPEMINDS_MOCK_MODE": "false"}, clear=True),
            patch("enrichment_service.requests.get") as get,
        ):
            service = enrichment_service.WineEnrichmentService()
            metadata, status = service.enrich_by_id("12345")
            anchored, anchor_status = service.enrich_from_anchors(
                "Example Estate", "Pinot Noir"
            )

        get.assert_not_called()
        self.assertIsNone(metadata)
        self.assertEqual(status, "not_configured")
        self.assertIsNone(anchored)
        self.assertEqual(anchor_status, "not_configured")
        self.assertFalse(service.get_usage_stats()["configured"])



    def test_search_catalog_wineapi_default_falls_back_to_grapeminds_when_empty(self):
        service = enrichment_service.WineEnrichmentService()
        with (
            patch.object(service, "search_wineapi_wines", return_value=[]) as wapi_search,
            patch.object(
                service,
                "search_wines",
                return_value=[{"id": "gm-1", "name": "Rubicon", "producer": "Meerlust"}],
            ) as gm_search,
        ):
            res = service.search_catalog("Meerlust Rubicon", provider="wineapi")

        wapi_search.assert_called_once_with("Meerlust Rubicon")
        gm_search.assert_called_once_with("Meerlust Rubicon")
        self.assertTrue(res["fallback_used"])
        self.assertEqual(res["requested_provider"], "wineapi")
        self.assertEqual(res["active_provider"], "grapeminds")
        self.assertEqual(res["results"][0]["provider"], "grapeminds")

    def test_map_wineapi_detail_extracts_market_price_and_pairings(self):
        raw = {
            "id": "7d50ad1a-79c1-4ec8-a2fb-2113b55f438d",
            "name": "RouteStock, Route 116 Pinot Noir, Sonoma Coast",
            "vintage": 2021,
            "type": "red",
            "winery": {"id": "w1", "name": "RouteStock"},
            "region": {"id": "r1", "name": "Sonoma Coast", "country": "United States"},
            "grapes": [{"id": "g1", "name": "Pinot Noir"}],
            "description": "Bright cherry and coastal spice.",
            "priceRange": {"min": 22.0, "max": 28.0, "currency": "USD"},
            "pairings": [{"food": "grilled lamb"}, {"food": "roasted duck"}],
        }
        mapped = enrichment_service.WineEnrichmentService._map_wineapi_detail(raw)
        self.assertEqual(mapped["name"], "Route 116 Pinot Noir")
        self.assertEqual(mapped["winery"], "RouteStock")
        self.assertEqual(mapped["region"], "Sonoma Coast")
        self.assertEqual(mapped["country_of_origin"], "United States")
        self.assertEqual(mapped["market_price"], 25.0)
        self.assertEqual(mapped["price_range_display"], "$22.00 – $28.00 USD")
        self.assertEqual(mapped["pairing"], "Grilled lamb, roasted duck")


if __name__ == "__main__":
    unittest.main()
