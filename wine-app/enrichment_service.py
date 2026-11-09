import os
import json
import requests
from urllib.parse import quote
from datetime import datetime
from typing import Callable

from env_settings import get_settings, load_app_env

load_app_env()

_SETTINGS = get_settings()
CACHE_FILE = str(_SETTINGS.enrichment_cache_file)
USAGE_FILE = str(_SETTINGS.enrichment_usage_file)


class WineEnrichmentService:
    """
    Budget-aware wrapper around the Grapeminds.eu wine API.

    Three layers of protection against burning the 200/month quota:
    1. Local cache: Repeated queries cost zero.
    2. Mock mode: GRAPEMINDS_MOCK_MODE=True returns fake data without a network call.
    3. Monthly usage tracking: Stops calling once the limit is reached.
    """

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.grapeminds_api_key
        self.base_url = self.settings.grapeminds_base_url
        self.mock_mode = self.settings.grapeminds_mock_mode
        self.wineapi_key = self.settings.wineapiio_api_key
        self.wineapi_base_url = self.settings.wineapiio_base_url
        self.grapeminds_monthly_limit = self.settings.grapeminds_monthly_limit
        self.wineapi_daily_limit = self.settings.wineapiio_daily_limit

        # Ensure cache + usage files exist
        self._init_storage_files()

    # ---- Storage helpers ----

    def _init_storage_files(self):
        for path, default in [(CACHE_FILE, {}), (USAGE_FILE, self._empty_usage())]:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):
                with open(path, "w") as f:
                    json.dump(default, f, indent=2)

    def _empty_usage(self) -> dict:
        return {
            "monthly_calls": {},          # {"2026-09": 42}
            "cache_hits_total": 0,
            "mock_calls_total": 0,
            "blocked_over_limit": 0,
        }

    def _read_json(self, path: str) -> dict:
        with open(path, "r") as f:
            return json.load(f)

    def _write_json(self, path: str, data: dict):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    # ---- Cache ----

    @staticmethod
    def _cache_key(producer_name: str | None, wine_name: str) -> str:
        """Normalize so 'Meerlust' and 'MEERLUST' share one cache entry."""
        return f"{(producer_name or '').strip().lower()}|{wine_name.strip().lower()}"

    def _cache_get(self, key: str):
        cache = self._read_json(CACHE_FILE)
        return cache.get(key, "__MISSING__")  # sentinel to distinguish from explicit null

    def _cache_set(self, key: str, value):
        cache = self._read_json(CACHE_FILE)
        cache[key] = value
        self._write_json(CACHE_FILE, cache)

    # ---- Usage tracking ----

    def _current_month(self) -> str:
        return datetime.now().strftime("%Y-%m")

    def _record_real_call(self):
        usage = self._read_json(USAGE_FILE)
        month = self._current_month()
        usage["monthly_calls"][month] = usage["monthly_calls"].get(month, 0) + 1
        self._write_json(USAGE_FILE, usage)

    def _record_cache_hit(self):
        usage = self._read_json(USAGE_FILE)
        usage["cache_hits_total"] += 1
        self._write_json(USAGE_FILE, usage)

    def _record_mock_call(self):
        usage = self._read_json(USAGE_FILE)
        usage["mock_calls_total"] += 1
        self._write_json(USAGE_FILE, usage)

    def _record_blocked(self):
        usage = self._read_json(USAGE_FILE)
        usage["blocked_over_limit"] += 1
        self._write_json(USAGE_FILE, usage)

    def _is_over_limit(self) -> bool:
        usage = self._read_json(USAGE_FILE)
        month = self._current_month()
        used = usage["monthly_calls"].get(month, 0)
        return used >= self.grapeminds_monthly_limit

    def _current_day(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _record_wineapi_call(self):
        usage = self._read_json(USAGE_FILE)
        day = self._current_day()
        daily = usage.setdefault("wineapi_daily_calls", {})
        daily[day] = daily.get(day, 0) + 1
        self._write_json(USAGE_FILE, usage)

    def _is_wineapi_over_limit(self) -> bool:
        usage = self._read_json(USAGE_FILE)
        day = self._current_day()
        used = usage.get("wineapi_daily_calls", {}).get(day, 0)
        return used >= self.wineapi_daily_limit

    def get_usage_stats(self) -> dict:
        """Returns current usage stats for display in the admin endpoint."""
        usage = self._read_json(USAGE_FILE)
        month = self._current_month()
        used = usage["monthly_calls"].get(month, 0)
        day = self._current_day()
        wineapi_used = usage.get("wineapi_daily_calls", {}).get(day, 0)
        return {
            "current_month": month,
            "calls_this_month": used,
            "monthly_limit": self.grapeminds_monthly_limit,
            "calls_remaining": max(0, self.grapeminds_monthly_limit - used),
            "cache_hits_total": usage["cache_hits_total"],
            "mock_calls_total": usage["mock_calls_total"],
            "blocked_over_limit": usage["blocked_over_limit"],
            "over_limit": used >= self.grapeminds_monthly_limit,
            "configured": self.mock_mode or bool(self.api_key),
            "wineapi_current_day": day,
            "wineapi_calls_today": wineapi_used,
            "wineapi_daily_limit": self.wineapi_daily_limit,
            "wineapi_calls_remaining": max(0, self.wineapi_daily_limit - wineapi_used),
            "wineapi_configured": bool(self.wineapi_key),
        }

    # ---- Mock data ----

    def _mock_response(self, producer_name: str, wine_name: str):
        """Deterministic fake response for testing without burning quota."""
        producer_key = producer_name.lower()
        wine_key = wine_name.lower()

        # A few canned entries for realistic testing
        canned = {
            "meerlust|rubicon": {
                "region": "Stellenbosch, South Africa",
                "grape_type": "Cabernet Sauvignon, Merlot, Cabernet Franc",
                "drinking_window": "2020-2040",
                "notes": "Iconic Bordeaux blend from Meerlust Estate, aged in French oak.",
            },
            "penfolds|grange": {
                "region": "South Australia",
                "grape_type": "Shiraz",
                "drinking_window": "2025-2050",
                "notes": "Australia's most collectable Shiraz, full-bodied and age-worthy.",
            },
        }

        key = f"{producer_key}|{wine_key}"
        if key in canned:
            return canned[key]

        # Generic fallback for unknown mocks
        return {
            "region": f"Mock Region for {producer_name}",
            "grape_type": f"Mock Grape for {wine_name}",
            "drinking_window": "Unknown (MOCK)",
            "notes": "[MOCK DATA] No real API call was made.",
        }

    # ---- Main public method ----

    def enrich_from_anchors(
        self,
        producer_name: str | None,
        wine_name: str,
        force_refresh: bool = False,
        identification_context: dict | None = None,
        candidate_selector: Callable[
            [dict, list[dict]], int | str | None
        ] | None = None,
        candidate_verifier: Callable[[dict, dict], bool] | None = None,
    ) -> tuple[dict | None, str]:
        """
        Returns enriched metadata dict, or None if no match.

        Order of operations:
        1. Check cache (free, instant).
        2. If mock mode, return canned/fake data (free).
        3. If over monthly limit, return None and log.
        4. Otherwise, make real API call, cache result, and log usage.
        """
        if not wine_name:
            return None, "not_attempted"

        key = self._cache_key(producer_name, wine_name)

        # 1. Cache check
        cached = self._cache_get(key)
        if cached != "__MISSING__":
            if (
                not self.mock_mode
                and isinstance(cached, dict)
                and str(cached.get("notes", "")).startswith("[MOCK DATA]")
            ):
                cached = "__MISSING__"
        if cached != "__MISSING__" and not force_refresh:
            self._record_cache_hit()
            print(f"💾 Cache HIT for {producer_name} - {wine_name}")
            # We cache both positive results and explicit nulls
            return (cached, "updated") if cached else (None, "no_match")

        # 2. Mock mode
        if not self.mock_mode and not self.api_key:
            return None, "not_configured"

        if self.mock_mode:
            print(f"🎭 MOCK MODE: returning fake data for {producer_name} - {wine_name}")
            result = self._mock_response(producer_name or "Unknown producer", wine_name)
            self._record_mock_call()
            return result, "mock"

        # 3. Budget guard
        if self._is_over_limit():
            self._record_blocked()
            print(
                f"🚫 Monthly limit ({self.grapeminds_monthly_limit}) reached. "
                f"Skipping live API call for {producer_name} - {wine_name}."
            )
            return None, "quota_limit"

        # Search by distinctive wine-name tokens; the combined producer and full
        # label text can be too restrictive for catalog entries with alternate names.
        params = {"q": self._search_query(wine_name), "limit": 50}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Accept-Language": "en",
        }

        print(f"🌍 [LIVE] Querying Grapeminds for: {producer_name} - {wine_name}")
        try:
            response = requests.get(
                f"{self.base_url}/wines/search",
                params=params,
                headers=headers,
                timeout=self.settings.catalog_timeout_seconds,
            )

            self._record_real_call()  # Count every real call, even if it fails

            if response.status_code == 200:
                payload = response.json()
                matches = payload.get("data", []) if isinstance(payload, dict) else payload
                if isinstance(matches, list) and matches:
                    used_model_match = False
                    candidates = [item for item in matches if isinstance(item, dict)]
                    ranked_matches = sorted(
                        (
                            item
                            for item in candidates
                            if self._is_matching_wine(
                                item, producer_name, wine_name
                            )
                        ),
                        key=lambda item: self._match_score(
                            item, producer_name, wine_name
                        ),
                        reverse=True,
                    )
                    if ranked_matches:
                        match = ranked_matches[0]
                    elif candidate_selector and candidates:
                        selector_candidates = [
                            self._candidate_summary(item) for item in candidates
                        ]
                        try:
                            selected_id = candidate_selector(
                                {
                                    "producer_name": producer_name,
                                    "wine_name": wine_name,
                                    **(identification_context or {}),
                                },
                                selector_candidates,
                            )
                        except (requests.RequestException, ValueError, TypeError) as error:
                            print(
                                "❌ Local model could not match Grapeminds results: "
                                f"{type(error).__name__}: {error}"
                            )
                            return None, "matcher_error"
                        match = next(
                            (
                                item
                                for item in candidates
                                if selected_id is not None
                                and str(item.get("id")) == str(selected_id)
                            ),
                            None,
                        )
                        if match is None:
                            if selected_id is not None:
                                print(
                                    "⚠️ Local model selected an ID outside the "
                                    "Grapeminds candidate list."
                                )
                                return None, "matcher_error"
                            print(
                                f"ℹ️ Local model found no confident Grapeminds "
                                f"match for {producer_name} - {wine_name}."
                            )
                            return None, "no_match"
                        used_model_match = True
                    else:
                        print(
                            f"ℹ️ Grapeminds returned {len(matches)} wines, "
                            f"but none matched {producer_name} - {wine_name}."
                        )
                        return None, "no_match"

                    result = self._map_wine_result(match)
                    wine_id = match.get("id")
                    if wine_id is not None:
                        if self._is_over_limit():
                            self._record_blocked()
                            print(
                                "🚫 Grapeminds monthly request limit reached; "
                                "using the matched search result without detail lookup."
                            )
                        else:
                            details_response = requests.get(
                                f"{self.base_url}/wines/{wine_id}",
                                headers=headers,
                                timeout=self.settings.catalog_timeout_seconds,
                            )
                            self._record_real_call()
                            if details_response.status_code == 200:
                                details_payload = details_response.json()
                                details = (
                                    details_payload.get("data")
                                    if isinstance(details_payload, dict)
                                    else None
                                )
                                if isinstance(details, dict):
                                    detail_fields = self._map_wine_result(details)
                                    result.update(
                                        {
                                            key: value
                                            for key, value in detail_fields.items()
                                            if value is not None
                                        }
                                    )
                            else:
                                print(
                                    "⚠️ Grapeminds found a matching wine, but its "
                                    f"details request returned HTTP "
                                    f"{details_response.status_code}."
                                )
                    if not self._is_consistent_with_anchors(
                        result,
                        wine_name,
                        identification_context or {},
                    ):
                        print(
                            "⚠️ Grapeminds candidate conflicts with label anchors; "
                            "discarding the result."
                        )
                        return None, "no_match"
                    if used_model_match and candidate_verifier:
                        try:
                            is_consistent = candidate_verifier(
                                {
                                    "producer_name": producer_name,
                                    "wine_name": wine_name,
                                    **(identification_context or {}),
                                },
                                result,
                            )
                        except (requests.RequestException, ValueError, TypeError) as error:
                            print(
                                "❌ Local model could not verify Grapeminds details: "
                                f"{type(error).__name__}: {error}"
                            )
                            return None, "matcher_error"
                        if is_consistent is not True:
                            print(
                                "⚠️ Local model rejected the selected Grapeminds "
                                "details as inconsistent with the label."
                            )
                            return None, "no_match"
                    self._cache_set(key, result)
                    return result, "updated"
                # No match found — cache the null so we don't retry
                self._cache_set(key, None)
                return None, "no_match"
            else:
                print(
                    f"⚠️ Grapeminds returned HTTP {response.status_code} "
                    f"for {producer_name} - {wine_name}."
                )
                return None, f"http_{response.status_code}"

        except (requests.RequestException, ValueError, TypeError) as error:
            print(
                f"❌ Grapeminds lookup failed for {producer_name} - {wine_name}: "
                f"{type(error).__name__}: {error}"
            )
            return None, "request_error"

    @staticmethod
    def _looks_like_uuid(value: str) -> bool:
        parts = value.strip().split("-")
        return (
            len(parts) == 5
            and [len(p) for p in parts] == [8, 4, 4, 4, 12]
            and all( all(c in "0123456789abcdefABCDEF" for c in p) for p in parts )
        )

    def enrich_by_id(self, grapeminds_id: str, provider: str | None = None) -> tuple[dict | None, str]:
        """Fetch a wine directly using its catalog ID (supports both Grapeminds and WineAPI.io UUIDs)."""
        wine_id = grapeminds_id.strip()
        if not wine_id:
            return None, "not_attempted"

        if wine_id.lower().startswith("wapi:"):
            wine_id = wine_id[5:].strip()
            provider = "wineapi"

        if (provider == "wineapi" or (provider is None and self._looks_like_uuid(wine_id))) and not self.mock_mode:
            return self.enrich_by_wineapi_id(wine_id)

        cache_key = f"grapeminds-id:{wine_id.casefold()}"
        cached = self._cache_get(cache_key)
        if cached != "__MISSING__":
            if not self.mock_mode and isinstance(cached, dict) and str(
                cached.get("notes", "")
            ).startswith("[MOCK DATA]"):
                cached = "__MISSING__"
        if cached != "__MISSING__":
            self._record_cache_hit()
            return (cached, "updated") if cached else (None, "no_match")

        if self.mock_mode:
            self._record_mock_call()
            return {
                "id": wine_id,
                "name": f"Mock wine {wine_id}",
                "winery": "Mock producer",
                "notes": "[MOCK DATA] No real API call was made.",
            }, "mock"

        if not self.api_key:
            return None, "not_configured"

        if self._is_over_limit():
            self._record_blocked()
            return None, "quota_limit"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Accept-Language": "en",
        }
        url = f"{self.base_url}/wines/{quote(wine_id, safe='')}"
        try:
            response = requests.get(
                url, headers=headers, timeout=self.settings.catalog_timeout_seconds
            )
            self._record_real_call()
            if response.status_code != 200:
                return None, f"http_{response.status_code}"

            payload = response.json()
            wine = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(wine, dict):
                self._cache_set(cache_key, None)
                return None, "no_match"

            metadata = self._map_wine_result(wine)
            metadata["id"] = str(wine.get("id") or wine_id)
            if not any(
                metadata.get(field)
                for field in ("name", "winery", "region", "description")
            ):
                self._cache_set(cache_key, None)
                return None, "no_match"
            self._cache_set(cache_key, metadata)
            return metadata, "updated"
        except (requests.RequestException, ValueError, TypeError, KeyError) as error:
            print(
                f"❌ Grapeminds ID lookup failed for {wine_id}: "
                f"{type(error).__name__}: {error}"
            )
            return None, "request_error"

    @staticmethod
    def _candidate_summary(wine: dict) -> dict:
        producer = wine.get("producer")
        if isinstance(producer, dict):
            producer = (
                producer.get("display_name")
                or producer.get("name")
                or producer.get("title")
            )
        region = wine.get("region")
        if isinstance(region, dict):
            region_name = region.get("name")
            country = region.get("country")
        else:
            region_name = region
            country = None
        grapes = wine.get("grapes") or wine.get("grape_varieties")
        grape_names = []
        for grape in grapes or []:
            if isinstance(grape, dict):
                grape_names.append(grape.get("name"))
            elif isinstance(grape, str):
                grape_names.append(grape)
        return {
            "id": wine.get("id"),
            "display_name": wine.get("display_name"),
            "name": wine.get("name") or wine.get("wine_name"),
            "producer": producer,
            "region": region_name,
            "country": country,
            "vintage": wine.get("vintage"),
            "grapes": [name for name in grape_names if name],
            "color": wine.get("color"),
        }

    @classmethod
    def _is_consistent_with_anchors(
        cls,
        result: dict,
        wine_name: str,
        context: dict,
    ) -> bool:
        anchor_country = context.get("country_of_origin")
        result_country = result.get("country_of_origin")
        if anchor_country and result_country:
            normalized_anchor_country = cls._normalize(
                cls._country_name(str(anchor_country))
            )
            normalized_result_country = cls._normalize(
                cls._country_name(str(result_country))
            )
            if normalized_anchor_country != normalized_result_country:
                return False

        anchor_grapes = cls._normalize_wine_tokens(
            str(context.get("grape_type") or "")
        )
        result_grapes = cls._normalize_wine_tokens(
            str(result.get("grape_type") or "")
        )
        if anchor_grapes and result_grapes and not anchor_grapes.intersection(
            result_grapes
        ):
            return False

        anchor_wine_tokens = cls._normalize_wine_tokens(wine_name)
        result_wine_tokens = cls._normalize_wine_tokens(
            str(result.get("name") or "")
        )
        if anchor_wine_tokens and result_wine_tokens:
            matching_wine_tokens = anchor_wine_tokens.intersection(result_wine_tokens)
            if len(matching_wine_tokens) * 2 < len(anchor_wine_tokens):
                return False

        return True

    @staticmethod
    def _is_matching_wine(
        wine: dict, producer_name: str | None, wine_name: str
    ) -> bool:
        producer = wine.get("producer")
        producer_label = ""
        if isinstance(producer, dict):
            producer_label = (
                producer.get("display_name")
                or producer.get("name")
                or producer.get("title")
                or ""
            )
        elif isinstance(producer, str):
            producer_label = producer

        display_parts = [
            part.strip()
            for part in str(wine.get("display_name") or "").split(",")
            if part.strip()
        ]
        if not producer_label and display_parts:
            producer_label = display_parts[0]
        wine_label = wine.get("name") or wine.get("wine_name")
        if not wine_label and display_parts:
            wine_label = display_parts[1] if len(display_parts) > 1 else display_parts[0]

        normalized_wine = WineEnrichmentService._normalize_wine_tokens(wine_name)
        normalized_result_producer = WineEnrichmentService._normalize(
            str(producer_label)
        )
        normalized_result_wine = WineEnrichmentService._normalize_wine_tokens(
            str(wine_label)
        )

        if not normalized_result_wine:
            return False
        producer_matches = True
        if producer_name:
            normalized_producer = WineEnrichmentService._normalize(producer_name)
            producer_matches = bool(normalized_result_producer) and (
                normalized_producer == normalized_result_producer
                or normalized_producer in normalized_result_producer
                or normalized_result_producer in normalized_producer
            )
        wine_matches = bool(normalized_wine) and normalized_wine.issubset(
            normalized_result_wine
        )
        return producer_matches and wine_matches

    @staticmethod
    def _normalize_wine_tokens(value: str) -> set[str]:
        generic_tokens = {
            "a",
            "an",
            "the",
            "red",
            "white",
            "rose",
            "wine",
            "wines",
            "estate",
            "winery",
            "vineyard",
            "vineyards",
        }
        return {
            token
            for token in WineEnrichmentService._normalize(value).split()
            if token not in generic_tokens
        }

    @classmethod
    def _search_query(cls, wine_name: str) -> str:
        generic_tokens = {"a", "an", "the", "red", "white", "rose", "wine"}
        tokens = [
            token for token in wine_name.split()
            if cls._normalize(token) not in generic_tokens
        ]
        return " ".join(tokens) or wine_name.strip()

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(
            "".join(
                character.lower() if character.isalnum() else " "
                for character in value
            ).split()
        )

    @classmethod
    def _match_score(
        cls, wine: dict, producer_name: str | None, wine_name: str
    ) -> int:
        display_name = str(wine.get("display_name") or "")
        display_parts = [
            part.strip() for part in display_name.split(",") if part.strip()
        ]
        producer = wine.get("producer")
        if isinstance(producer, dict):
            producer_label = (
                producer.get("display_name")
                or producer.get("name")
                or producer.get("title")
                or ""
            )
        elif isinstance(producer, str):
            producer_label = producer
        else:
            producer_label = display_parts[0] if display_parts else ""
        wine_label = wine.get("name") or wine.get("wine_name")
        if not wine_label and display_parts:
            wine_label = display_parts[1] if len(display_parts) > 1 else display_parts[0]

        score = 0
        if producer_name and cls._normalize(str(producer_label)) == cls._normalize(producer_name):
            score += 2
        expected_tokens = cls._normalize_wine_tokens(wine_name)
        candidate_tokens = cls._normalize_wine_tokens(str(wine_label))
        if expected_tokens and expected_tokens.issubset(candidate_tokens):
            score += 2 + len(expected_tokens)
        return score

    @staticmethod
    def _map_wine_result(wine: dict) -> dict:
        producer = wine.get("producer")
        producer_name = None
        if isinstance(producer, dict):
            producer_name = (
                producer.get("display_name")
                or producer.get("name")
                or producer.get("title")
            )
        elif isinstance(producer, str):
            producer_name = producer
        display_name = wine.get("display_name")
        display_parts = (
            [part.strip() for part in display_name.split(",") if part.strip()]
            if isinstance(display_name, str)
            else []
        )
        if not producer_name and display_parts:
            producer_name = display_parts[0]
        region_value = wine.get("region")
        region = region_value.get("name") if isinstance(region_value, dict) else region_value
        country = (
            wine.get("country_of_origin")
            or wine.get("country")
            or (
                region_value.get("country")
                if isinstance(region_value, dict)
                else None
            )
        )
        if isinstance(country, dict):
            country = (
                country.get("display_name")
                or country.get("name")
                or country.get("title")
                or country.get("code")
            )
        if isinstance(country, str):
            country = WineEnrichmentService._country_name(country)

        wine_name = wine.get("name") or wine.get("wine_name")
        if not wine_name and display_parts:
            wine_name = display_parts[1] if len(display_parts) > 1 else display_parts[0]
            if isinstance(region, str):
                normalized_title = WineEnrichmentService._normalize(str(wine_name))
                normalized_region = WineEnrichmentService._normalize(region)
                if normalized_region and normalized_title.endswith(
                    f" {normalized_region}"
                ):
                    wine_name = str(wine_name)[: -len(region)].rstrip(" ,-/")

        grapes = wine.get("grapes") or wine.get("grape_varieties")
        if grapes is None and wine.get("grape_variety"):
            grapes = [wine["grape_variety"]]
        if isinstance(grapes, dict):
            grapes = [grapes]
        grape_names = [
            grape.get("name", "")
            if isinstance(grape, dict)
            else str(grape)
            for grape in grapes or []
            if grape
        ]
        grape_names = [name for name in grape_names if name]
        description = wine.get("description")
        pairing = wine.get("pairing")
        tasting_notes = wine.get("tasting_notes")

        return {
            "name": wine_name,
            "winery": producer_name,
            "vintage": wine.get("vintage"),
            "region": region,
            "country_of_origin": country,
            "grape_type": ", ".join(grape_names) or wine.get("grape_variety"),
            "grape_varieties": grapes if isinstance(grapes, list) else None,
            "color": wine.get("color"),
            "description": description,
            "pairing": pairing,
            "grapeminds_tasting_notes": tasting_notes,
            "flavor_profile": wine.get("flavor_profile"),
            "drinking_window": wine.get("drinking_window"),
            "notes": (
                description.get("text")
                if isinstance(description, dict)
                else description
            ),
        }

    @staticmethod
    def _country_name(country: str) -> str:
        country_names = {
            "ar": "Argentina",
            "au": "Australia",
            "at": "Austria",
            "br": "Brazil",
            "ca": "Canada",
            "cl": "Chile",
            "hr": "Croatia",
            "cz": "Czech Republic",
            "fr": "France",
            "ge": "Georgia",
            "de": "Germany",
            "gr": "Greece",
            "hu": "Hungary",
            "il": "Israel",
            "it": "Italy",
            "lb": "Lebanon",
            "mx": "Mexico",
            "nz": "New Zealand",
            "pt": "Portugal",
            "ro": "Romania",
            "za": "South Africa",
            "es": "Spain",
            "ch": "Switzerland",
            "tr": "Türkiye",
            "us": "United States",
            "uy": "Uruguay",
        }
        return country_names.get(country.strip().casefold(), country.strip())

    def search_wines(self, query: str) -> list[dict]:
        """Search the Grapeminds catalog for wines matching a query string."""
        if not query or len(query.strip()) < 2:
            return []

        if self.mock_mode:
            print(f"🎭 MOCK MODE: searching for {query}")
            self._record_mock_call()
            return [
                {"id": "mock-1", "name": f"Mock Wine {query} 1", "producer": "Mock Producer", "region": "Mock Region"},
                {"id": "mock-2", "name": f"Mock Wine {query} 2", "producer": "Mock Producer", "region": "Mock Region"},
            ]

        if not self.api_key:
            return []

        if self._is_over_limit():
            self._record_blocked()
            return []

        params = {"q": query, "limit": 50}
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

        try:
            import requests
            response = requests.get(
                f"{self.base_url}/wines/search",
                params=params,
                headers=headers,
                timeout=self.settings.catalog_timeout_seconds,
            )
            if response.status_code != 200:
                return []
            payload = response.json()
            data = payload.get("data", []) if isinstance(payload, dict) else payload
            return [
                self._map_search_hit(item) for item in data if isinstance(item, dict)
            ]
        except Exception as e:
            print(f"❌ Grapeminds search error: {e}")
            return []

    @staticmethod
    def _map_search_hit(item: dict) -> dict:
        """Map a /wines/search hit to the summary shape the Explorer renders.

        The live search endpoint returns ``display_name``, ``producer_name`` and
        ``color``; it does not return ``name``/``producer``/``region``. Reading the
        wrong keys is what left every Explorer row blank, so fall back across the
        known aliases and never emit an empty cell.
        """
        producer = (
            item.get("producer_display_name")
            or item.get("producer_name")
            or item.get("producer")
        )
        if isinstance(producer, dict):
            producer = producer.get("display_name") or producer.get("name")

        name = item.get("display_name") or item.get("name") or item.get("wine_name")
        if isinstance(name, dict):
            name = name.get("display_name") or name.get("name")
        if not name:
            parts = [producer, item.get("color"), item.get("vintage")]
            name = " · ".join(
                str(part).strip() for part in parts if part
            ) or "Unnamed wine"

        region = item.get("region")
        if isinstance(region, dict):
            region = region.get("name")

        return {
            "id": item.get("id"),
            "name": name,
            "producer": producer or "",
            "region": region or "",
            "color": item.get("color") or "",
            "vintage": item.get("vintage"),
        }

    def search_wineapi_wines(self, query: str) -> list[dict]:
        """Search the WineAPI.io catalog for wines matching a query string."""
        if not query or len(query.strip()) < 2:
            return []
        if not self.wineapi_key or self._is_wineapi_over_limit():
            return []

        params = {"q": query.strip(), "limit": 30}
        headers = {
            "X-API-Key": self.wineapi_key,
            "Accept": "application/json",
            "User-Agent": "WineCellar/1.0",
        }
        try:
            response = requests.get(
                f"{self.wineapi_base_url}/wines/search",
                params=params,
                headers=headers,
                timeout=self.settings.catalog_timeout_seconds,
            )
            self._record_wineapi_call()
            if response.status_code != 200:
                return []
            payload = response.json()
            results = payload.get("results", []) if isinstance(payload, dict) else []
            return [
                self._map_wineapi_search_hit(item)
                for item in results
                if isinstance(item, dict)
            ]
        except Exception as e:
            print(f"❌ WineAPI.io search error: {e}")
            return []

    def search_catalog(self, query: str, provider: str = "wineapi") -> dict:
        """Search WineAPI.io or Grapeminds with automatic fallback when the selected provider returns empty."""
        requested = (provider or "wineapi").strip().lower()
        if requested not in {"wineapi", "grapeminds", "both"}:
            requested = "wineapi"

        if requested == "both":
            wapi_hits = self.search_wineapi_wines(query)
            gm_hits = [
                {**item, "provider": "grapeminds"}
                for item in self.search_wines(query)
            ]
            return {
                "results": wapi_hits + gm_hits,
                "requested_provider": "both",
                "active_provider": "both",
                "fallback_used": False,
            }

        if requested == "grapeminds":
            gm_hits = [
                {**item, "provider": "grapeminds"}
                for item in self.search_wines(query)
            ]
            if gm_hits:
                return {
                    "results": gm_hits,
                    "requested_provider": "grapeminds",
                    "active_provider": "grapeminds",
                    "fallback_used": False,
                }
            wapi_hits = self.search_wineapi_wines(query)
            return {
                "results": wapi_hits,
                "requested_provider": "grapeminds",
                "active_provider": "wineapi" if wapi_hits else "grapeminds",
                "fallback_used": bool(wapi_hits),
            }

        # Default: wineapi first, fallback to grapeminds
        wapi_hits = self.search_wineapi_wines(query)
        if wapi_hits:
            return {
                "results": wapi_hits,
                "requested_provider": "wineapi",
                "active_provider": "wineapi",
                "fallback_used": False,
            }
        gm_hits = [
            {**item, "provider": "grapeminds"}
            for item in self.search_wines(query)
        ]
        return {
            "results": gm_hits,
            "requested_provider": "wineapi",
            "active_provider": "grapeminds" if gm_hits else "wineapi",
            "fallback_used": bool(gm_hits),
        }

    def enrich_by_wineapi_id(self, wine_id: str) -> tuple[dict | None, str]:
        """Fetch a WineAPI.io wine profile by UUID."""
        clean_id = wine_id.strip()
        if not clean_id:
            return None, "not_attempted"

        cache_key = f"wineapi-id:{clean_id.casefold()}"
        cached = self._cache_get(cache_key)
        if cached != "__MISSING__" and cached is not None:
            self._record_cache_hit()
            return cached, "updated"

        if not self.wineapi_key:
            return None, "not_configured"

        if self._is_wineapi_over_limit():
            self._record_blocked()
            return None, "quota_limit"

        headers = {
            "X-API-Key": self.wineapi_key,
            "Accept": "application/json",
            "User-Agent": "WineCellar/1.0",
        }
        url = f"{self.wineapi_base_url}/wines/{quote(clean_id, safe='')}"
        try:
            response = requests.get(
                url, headers=headers, timeout=self.settings.catalog_timeout_seconds
            )
            self._record_wineapi_call()
            if response.status_code != 200:
                return None, f"http_{response.status_code}"

            wine = response.json()
            if not isinstance(wine, dict):
                return None, "no_match"

            metadata = self._map_wineapi_detail(wine)
            metadata["id"] = str(wine.get("id") or clean_id)
            update_status = response.headers.get("X-Update-Status", "").lower()
            if update_status == "pending":
                metadata["pending_enrichment"] = True
            else:
                self._cache_set(cache_key, metadata)
            return metadata, "updated"
        except (requests.RequestException, ValueError, TypeError, KeyError) as error:
            print(f"❌ WineAPI.io ID lookup failed for {clean_id}: {type(error).__name__}: {error}")
            return None, "request_error"

    @staticmethod
    def _clean_wineapi_display_name(raw_name: str, winery: str | None, region: str | None) -> str:
        name = (raw_name or "").strip()
        if not name:
            return ""
        parts = [p.strip() for p in name.split(",") if p.strip()]
        if len(parts) >= 2:
            if winery and parts[0].casefold() == winery.strip().casefold():
                parts = parts[1:]
            if len(parts) >= 2 and region and parts[-1].casefold() == region.strip().casefold():
                parts = parts[:-1]
            cleaned = ", ".join(parts).strip()
            if cleaned:
                return cleaned
        return name

    @classmethod
    def _map_wineapi_search_hit(cls, item: dict) -> dict:
        winery = item.get("winery") or ""
        region = item.get("region") or ""
        country = item.get("country") or ""
        raw_name = item.get("name") or ""
        clean_name = cls._clean_wineapi_display_name(raw_name, winery, region)
        region_display = " · ".join(p for p in [region, country] if p)
        return {
            "id": item.get("id"),
            "name": clean_name or raw_name or "Unnamed wine",
            "producer": winery,
            "region": region_display,
            "country": country,
            "color": item.get("type") or "",
            "vintage": item.get("vintage"),
            "provider": "wineapi",
        }

    @classmethod
    def _map_wineapi_detail(cls, wine: dict) -> dict:
        winery_obj = wine.get("winery")
        winery = (
            winery_obj.get("name")
            if isinstance(winery_obj, dict)
            else (winery_obj if isinstance(winery_obj, str) else None)
        )
        region_obj = wine.get("region")
        region = (
            region_obj.get("name")
            if isinstance(region_obj, dict)
            else (region_obj if isinstance(region_obj, str) else None)
        )
        country = (
            region_obj.get("country")
            if isinstance(region_obj, dict)
            else wine.get("country")
        )
        raw_name = wine.get("name") or ""
        clean_name = cls._clean_wineapi_display_name(raw_name, winery, region)

        grapes_raw = wine.get("grapes") or []
        grape_varieties = []
        grape_names = []
        for g in grapes_raw:
            if isinstance(g, dict) and g.get("name"):
                grape_varieties.append({"id": g.get("id"), "name": g["name"]})
                grape_names.append(g["name"])
            elif isinstance(g, str) and g.strip():
                grape_varieties.append({"name": g.strip()})
                grape_names.append(g.strip())

        pairings_raw = wine.get("pairings") or []
        pairing_items = []
        for p in pairings_raw:
            if isinstance(p, dict) and p.get("food"):
                pairing_items.append(str(p["food"]).strip())
            elif isinstance(p, str) and p.strip():
                pairing_items.append(p.strip())
        pairing_text = ", ".join(pairing_items) if pairing_items else None
        if pairing_text:
            pairing_text = pairing_text[0].upper() + pairing_text[1:]

        # Extract market price from priceRange or prices array
        market_price = None
        price_range_display = None
        price_range = wine.get("priceRange")
        if isinstance(price_range, dict):
            p_min = price_range.get("min")
            p_max = price_range.get("max")
            currency = price_range.get("currency") or "USD"
            if isinstance(p_min, (int, float)) and isinstance(p_max, (int, float)):
                market_price = round((float(p_min) + float(p_max)) / 2.0, 2)
                if float(p_min) == float(p_max):
                    price_range_display = f"${float(p_min):.2f} {currency}"
                else:
                    price_range_display = f"${float(p_min):.2f} – ${float(p_max):.2f} {currency}"
            elif isinstance(p_min, (int, float)):
                market_price = round(float(p_min), 2)
                price_range_display = f"${float(p_min):.2f} {currency}"
            elif isinstance(p_max, (int, float)):
                market_price = round(float(p_max), 2)
                price_range_display = f"${float(p_max):.2f} {currency}"

        prices_list = wine.get("prices") or []
        if market_price is None and prices_list:
            numeric_prices = []
            for pr in prices_list:
                if isinstance(pr, dict) and pr.get("price") is not None:
                    try:
                        numeric_prices.append(float(pr["price"]))
                    except (ValueError, TypeError):
                        pass
            if numeric_prices:
                market_price = round(sum(numeric_prices) / len(numeric_prices), 2)
                low, high = min(numeric_prices), max(numeric_prices)
                price_range_display = (
                    f"${low:.2f}" if low == high else f"${low:.2f} – ${high:.2f}"
                )

        return {
            "id": wine.get("id"),
            "provider": "wineapi",
            "name": clean_name or raw_name,
            "winery": winery,
            "vintage": wine.get("vintage"),
            "region": region,
            "country_of_origin": country,
            "grape_type": ", ".join(grape_names) if grape_names else None,
            "grape_varieties": grape_varieties if grape_varieties else None,
            "color": wine.get("type"),
            "description": wine.get("description"),
            "pairing": pairing_text,
            "grapeminds_tasting_notes": None,
            "flavor_profile": None,
            "market_price": market_price,
            "price_range_display": price_range_display,
            "prices": prices_list,
            "average_rating": wine.get("averageRating"),
            "scores": wine.get("scores") or [],
        }
