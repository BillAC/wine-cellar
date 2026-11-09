import base64
import os
import unittest
from unittest.mock import Mock, patch

import requests

from vision_service import VisionService


class VisionServiceTests(unittest.TestCase):
    def test_openrouter_sends_image_and_parses_text_response(self):
        response = Mock()
        response.json.return_value = {
            "choices": [
                {"message": {"content": "Winery: Example Estate\nWine: Red Blend"}}
            ]
        }

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_VISION_MODEL": "example/vision-model",
                "OPENROUTER_SITE_URL": "https://example.test",
                "OPENROUTER_APP_NAME": "Wine Cellar",
            },
            clear=True,
        ):
            service = VisionService()
            with patch("vision_service.requests.post", return_value=response) as post:
                result = service.extract_from_image(b"png-bytes", "image/png")

        self.assertEqual(result["winery"], "Example Estate")
        self.assertEqual(result["name"], "Red Blend")
        request = post.call_args.kwargs
        self.assertEqual(request["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(request["headers"]["HTTP-Referer"], "https://example.test")
        self.assertEqual(request["headers"]["X-Title"], "Wine Cellar")
        self.assertEqual(
            request["json"]["messages"][0]["content"][1]["image_url"]["url"],
            "data:image/png;base64," + base64.b64encode(b"png-bytes").decode("utf-8"),
        )
        self.assertEqual(request["timeout"], 60)

    def test_openrouter_extracts_text_from_multimodal_content_blocks(self):
        response = Mock()
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "Winery: Example Estate"},
                            {"type": "image_url", "image_url": {}},
                            {"type": "text", "text": "Wine: Red Blend"},
                        ]
                    }
                }
            ]
        }

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_VISION_MODEL": "example/vision-model",
            },
            clear=True,
        ):
            service = VisionService()
            with patch("vision_service.requests.post", return_value=response):
                result = service.extract_from_image(b"image")

        self.assertEqual(result["winery"], "Example Estate")
        self.assertEqual(result["name"], "Red Blend")

    def test_confident_ollama_read_does_not_call_openrouter(self):
        response = Mock()
        response.json.return_value = {
            "response": (
                '{"winery":"Example Estate","name":"Red Blend",'
                '"confidence":{"winery":0.9,"name":0.95}}'
            )
        }

        with patch.dict(os.environ, {}, clear=True):
            service = VisionService()
            with patch("vision_service.requests.post", return_value=response) as post:
                result = service.extract_from_image(b"image")

        self.assertEqual(result["_provider"], "ollama")
        self.assertEqual(result["winery"], "Example Estate")
        self.assertEqual(result["name"], "Red Blend")
        self.assertEqual(post.call_args.args[0], "http://localhost:11434/api/generate")
        self.assertEqual(post.call_args.kwargs["json"]["format"], "json")
        self.assertEqual(post.call_args.kwargs["timeout"], 120)

    def test_low_confidence_ollama_read_escalates_and_uses_better_openrouter_result(self):
        local = Mock()
        local.json.return_value = {
            "response": (
                '{"winery":"Example Estate","name":null,'
                '"confidence":{"winery":0.8,"name":0.2}}'
            )
        }
        remote = Mock()
        remote.json.return_value = {
            "choices": [{
                "message": {
                    "content": (
                        '{"winery":"Example Estate","name":"Reserve Pinot Noir",'
                        '"confidence":{"winery":0.95,"name":0.9}}'
                    )
                }
            }]
        }
        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
            clear=True,
        ):
            service = VisionService()
            with patch(
                "vision_service.requests.post",
                side_effect=[local, remote],
            ) as post:
                result = service.extract_from_image(b"image")

        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].args[0], "http://localhost:11434/api/generate")
        self.assertEqual(post.call_args_list[1].args[0], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(result["name"], "Reserve Pinot Noir")
        self.assertEqual(result["_provider"], "openrouter")
        self.assertEqual(result["_fallback_status"], "used")

    def test_ollama_error_escalates_to_openrouter(self):
        local = Mock()
        local.raise_for_status.side_effect = requests.ConnectionError("local error")
        remote = Mock()
        remote.json.return_value = {
            "choices": [{
                "message": {
                    "content": (
                        '{"winery":"Example Estate","name":"Reserve Pinot Noir",'
                        '"confidence":{"winery":0.95,"name":0.9}}'
                    )
                }
            }]
        }
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
            service = VisionService()
            with patch(
                "vision_service.requests.post",
                side_effect=[local, remote],
            ):
                result = service.extract_from_image(b"image")

        self.assertNotIn("_error", result)
        self.assertEqual(result["name"], "Reserve Pinot Noir")
        self.assertEqual(result["_provider"], "openrouter")

    def test_failed_openrouter_fallback_keeps_ollama_suggestions(self):
        local = Mock()
        local.json.return_value = {
            "response": (
                '{"winery":"Example Estate","name":"Red Blend",'
                '"confidence":{"winery":0.8,"name":0.3}}'
            )
        }
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
            service = VisionService()
            with patch(
                "vision_service.requests.post",
                side_effect=[local, requests.Timeout("cloud timeout")],
            ):
                result = service.extract_from_image(b"image")

        self.assertEqual(result["winery"], "Example Estate")
        self.assertEqual(result["name"], "Red Blend")
        self.assertEqual(result["_provider"], "ollama")
        self.assertEqual(result["_fallback_status"], "failed")

    def test_json_response_inside_markdown_fences_is_parsed(self):
        service = VisionService()
        result = service._parse_vision_output(
            '```json\n{"winery":"Example Estate","name":"Pinot Noir",'
            '"vintage":2021,"region":"Sonoma Coast"}\n```'
        )

        self.assertEqual(result["winery"], "Example Estate")
        self.assertEqual(result["name"], "Pinot Noir")
        self.assertEqual(result["vintage"], 2021)
        self.assertEqual(result["region"], "Sonoma Coast")

    def test_nested_field_confidence_values_are_parsed_without_regex_corruption(self):
        service = VisionService()
        result = service._parse_vision_output(
            '{"winery":{"confidence":0.95,"value":"RouteStock"},'
            '"name":{"confidence":0.85,"value":"Sonoma Coast Pinot Noir"},'
            '"vintage":2023,"region":"Sonoma Coast",'
            '"country_of_origin":null,"grape_type":"Pinot Noir"}'
        )

        self.assertEqual(result["winery"], "RouteStock")
        self.assertEqual(result["name"], "Sonoma Coast Pinot Noir")
        self.assertEqual(
            result["_confidence"],
            {"winery": 0.95, "name": 0.85},
        )
        self.assertIsNone(service._fallback_reason(result))

    def test_nested_low_confidence_triggers_openrouter_fallback(self):
        local = Mock()
        local.json.return_value = {
            "response": (
                '{"winery":{"confidence":0.9,"value":"Example Estate"},'
                '"name":{"confidence":0.4,"value":"Red Blend"}}'
            )
        }
        remote = Mock()
        remote.json.return_value = {
            "choices": [{
                "message": {
                    "content": (
                        '{"winery":"Example Estate","name":"Estate Reserve",'
                        '"confidence":{"winery":0.95,"name":0.9}}'
                    )
                }
            }]
        }
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
            service = VisionService()
            with patch(
                "vision_service.requests.post",
                side_effect=[local, remote],
            ) as post:
                result = service.extract_from_image(b"image")

        self.assertEqual(post.call_count, 2)
        self.assertEqual(result["name"], "Estate Reserve")
        self.assertEqual(result["_provider"], "openrouter")
        self.assertEqual(result["_fallback_status"], "used")

    def test_country_of_origin_is_parsed_from_json(self):
        result = VisionService()._parse_vision_output(
            '{"winery":"Meerlust","name":"Rubicon",'
            '"country_of_origin":"South Africa"}'
        )

        self.assertEqual(result["country_of_origin"], "South Africa")

    def test_candidate_matcher_uses_same_ollama_model_and_only_returns_id(self):
        response = Mock()
        response.json.return_value = {"response": '{"id":346681}'}
        with patch.dict(
            os.environ,
            {
                "OLLAMA_URL": "http://localhost:11434",
                "OLLAMA_VISION_MODEL": "qwen2.5vl:7b",
            },
            clear=True,
        ):
            service = VisionService()
            with patch("vision_service.requests.post", return_value=response) as post:
                selected = service.select_wine_candidate(
                    {"wine_name": "The Little Eagle Red"},
                    [{"id": 346681, "display_name": "Eagles' Nest, Little Eagle Merlot"}],
                )

        self.assertEqual(selected, 346681)
        self.assertEqual(
            post.call_args.args[0],
            "http://localhost:11434/api/generate",
        )
        self.assertEqual(post.call_args.kwargs["json"]["model"], "qwen2.5vl:7b")
        self.assertEqual(post.call_args.kwargs["json"]["keep_alive"], "10m")
        self.assertEqual(post.call_args.kwargs["json"]["options"]["temperature"], 0)

    def test_candidate_matcher_rejects_invalid_json_response(self):
        response = Mock()
        response.json.return_value = {"response": "not-json"}
        service = VisionService()

        with patch("vision_service.requests.post", return_value=response):
            with self.assertRaises(ValueError):
                service.select_wine_candidate({}, [{"id": 10}])

    def test_candidate_verifier_uses_same_ollama_model_and_returns_boolean(self):
        response = Mock()
        response.json.return_value = {"response": '{"consistent":true}'}
        with patch.dict(
            os.environ,
            {
                "OLLAMA_URL": "http://localhost:11434",
                "OLLAMA_VISION_MODEL": "qwen2.5vl:7b",
            },
            clear=True,
        ):
            service = VisionService()
            with patch("vision_service.requests.post", return_value=response) as post:
                consistent = service.verify_wine_candidate(
                    {"wine_name": "Natura Chardonnay"},
                    {
                        "name": "Natura Chardonnay",
                        "country_of_origin": "Chile",
                        "notes": "ignored long description",
                    },
                )

        self.assertTrue(consistent)
        request = post.call_args.kwargs["json"]
        self.assertEqual(request["model"], "qwen2.5vl:7b")
        self.assertEqual(request["keep_alive"], "10m")
        self.assertIn('"country_of_origin": "Chile"', request["prompt"])
        self.assertNotIn("ignored long description", request["prompt"])

    def test_common_misspelling_of_winery_key_is_recovered(self):
        service = VisionService()
        result = service._parse_vision_output(
            '{"winey":"Meerlust","name":"Rubicon","vintage":2018}'
        )

        self.assertEqual(result["winery"], "Meerlust")
        self.assertEqual(result["name"], "Rubicon")

    def test_empty_vision_response_is_reported_as_an_error(self):
        response = Mock()
        response.json.return_value = {"response": ""}
        with patch.dict(os.environ, {}, clear=True):
            service = VisionService()
            with patch("vision_service.requests.post", return_value=response):
                result = service.extract_from_image(b"image")

        self.assertTrue(result["_error"])

    def test_openrouter_fallback_model_has_a_default_and_does_not_require_key(self):
        with patch.dict(os.environ, {}, clear=True):
            service = VisionService()

        self.assertEqual(
            service.openrouter_model,
            "qwen/qwen2.5-vl-72b-instruct:free",
        )

    def test_wineapi_fallback_identifies_wine_when_ollama_fails(self):
        local = Mock()
        local.raise_for_status.side_effect = requests.ConnectionError("Ollama down")
        wineapi_resp = Mock()
        wineapi_resp.json.return_value = {
            "confidence": 0.95,
            "wine": {
                "id": "3d0e5e03-602c-4b50-ba1d-27fddac26061",
                "name": "RouteStock, Sauvignon Blanc, Napa Valley",
                "vintage": 2020,
                "type": "white",
                "winery": "RouteStock",
                "region": "Napa Valley",
                "country": "United States",
            },
            "suggestions": [
                {
                    "id": "0d487bb6-d110-4a5c-81d5-cb5ef7835b4d",
                    "name": "RouteStock, Pinot Noir, Sonoma Coast",
                    "vintage": 2020,
                    "type": "red",
                    "winery": "RouteStock",
                    "region": "Sonoma Coast",
                    "country": "United States",
                }
            ],
            "visionDetails": {
                "rawLabelText": "ROUTESTOCK\nSonoma Coast\nPINOT NOIR\n2023"
            },
        }
        with patch.dict(
            os.environ,
            {
                "WINEAPIIO_KEY": "wapi-test-key",
                "WINEAPIIO_BASE_URL": "https://api.wineapi.io",
            },
            clear=True,
        ):
            service = VisionService()
            with patch(
                "vision_service.requests.post",
                side_effect=[local, wineapi_resp],
            ) as post:
                result = service.extract_from_image(b"jpeg-bytes", "image/jpeg")

        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            post.call_args.args[0], "https://api.wineapi.io/identify/image"
        )
        self.assertEqual(
            post.call_args.kwargs["headers"]["X-API-Key"], "wapi-test-key"
        )
        self.assertEqual(result["_provider"], "wineapi")
        self.assertEqual(result["_fallback_status"], "used")
        self.assertEqual(result["winery"], "RouteStock")
        self.assertEqual(result["name"], "Pinot Noir")
        self.assertEqual(result["vintage"], 2023)
        self.assertEqual(result["region"], "Sonoma Coast")
        self.assertEqual(result["country_of_origin"], "United States")
        self.assertEqual(result["grape_type"], "Pinot Noir")
        self.assertEqual(result["color"], "Red")
        self.assertEqual(
            result["_wineapi_id"], "wineapi:0d487bb6-d110-4a5c-81d5-cb5ef7835b4d"
        )

    def test_wineapi_fallback_rescues_when_openrouter_fails(self):
        local = Mock()
        local.raise_for_status.side_effect = requests.ConnectionError("Ollama down")
        openrouter = Mock()
        openrouter.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")
        wineapi_resp = Mock()
        wineapi_resp.json.return_value = {
            "confidence": 0.92,
            "wine": {
                "id": "970f1bb1-398d-4fcc-b7de-3c4d6487969b",
                "name": "Meerlust, Cabernet Franc, Stellenbosch",
                "type": "red",
                "winery": "Meerlust",
                "region": "Stellenbosch",
                "country": "South Africa",
            },
            "suggestions": [],
            "visionDetails": {
                "rawLabelText": "Rubicon\nMEERLUST\nSTELLENBOSCH\n2018\nPRODUCT OF SOUTH AFRICA"
            },
        }
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "or-key",
                "WINEAPIIO_KEY": "wapi-key",
            },
            clear=True,
        ):
            service = VisionService()
            with patch(
                "vision_service.requests.post",
                side_effect=[local, openrouter, wineapi_resp],
            ) as post:
                result = service.extract_from_image(b"jpeg-bytes", "image/jpeg")

        self.assertEqual(post.call_count, 3)
        self.assertEqual(result["_provider"], "wineapi")
        self.assertEqual(result["_fallback_status"], "used")
        self.assertEqual(result["winery"], "Meerlust")
        self.assertEqual(result["name"], "Rubicon")
        self.assertEqual(result["vintage"], 2018)
        self.assertEqual(result["region"], "Stellenbosch")
        self.assertEqual(result["country_of_origin"], "South Africa")
        self.assertEqual(result["color"], "Red")


if __name__ == "__main__":
    unittest.main()
