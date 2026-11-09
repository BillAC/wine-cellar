import base64
import re
import json
import requests

from env_settings import get_settings, load_app_env

load_app_env()


class VisionService:
    """
    Extracts wine-label fields with Ollama first and escalates weak reads to
    OpenRouter when an API key is configured.
    """

    CONFIDENCE_THRESHOLD = 0.65
    CORE_IDENTITY_FIELDS = ("winery", "name")
    KNOWN_GRAPES = (
        "Cabernet Sauvignon",
        "Cabernet Franc",
        "Pinot Noir",
        "Sauvignon Blanc",
        "Chenin Blanc",
        "Pinot Grigio",
        "Pinot Gris",
        "Petite Sirah",
        "Chardonnay",
        "Merlot",
        "Syrah",
        "Shiraz",
        "Malbec",
        "Zinfandel",
        "Riesling",
        "Sangiovese",
        "Tempranillo",
        "Nebbiolo",
        "Grenache",
        "Viognier",
        "Gewürztraminer",
        "Gewurztraminer",
        "Albariño",
        "Albarino",
        "Mourvèdre",
        "Mourvedre",
        "Gamay",
        "Semillon",
        "Sémillon",
        "Barbera",
    )
    WINEAPI_COLOR_MAP = {
        "red": "Red",
        "white": "White",
        "rose": "Rosé",
        "rosé": "Rosé",
        "sparkling": "Sparkling",
        "dessert": "Dessert",
        "fortified": "Fortified",
    }

    def __init__(self):
        self.settings = get_settings()
        self.ollama_url = self.settings.ollama_url
        self.ollama_model = self.settings.ollama_vision_model
        self.openrouter_api_key = self.settings.openrouter_api_key
        self.openrouter_model = self.settings.openrouter_vision_model
        self.wineapi_key = self.settings.wineapiio_api_key
        self.wineapi_base_url = self.settings.wineapiio_base_url

    def extract_from_image(
        self, image_bytes: bytes, image_mime_type: str = "image/jpeg"
    ) -> dict:
        """
        Takes raw image bytes, returns a draft dict:
        {
            "winery": str | None,
            "name": str | None,
            "vintage": int | None,
            "region": str | None,
            "country_of_origin": str | None,
            "grape_type": str | None,
            "_raw": str   # The raw model output (for debugging/audit)
        }
        Always returns a dict; missing fields are None.
        """
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")

        prompt = (
            "Read the wine label and extract its printed text into exactly one JSON "
            "object with these exact keys: winery, name,"
            " vintage (4-digit year), region, country_of_origin, grape_type. "
            'Also include "confidence", an object with numeric 0-to-1 confidence '
            'scores for "winery" and "name". Confidence measures how clearly each '
            "identity value is legible on the label, not how plausible it seems. "
            "In some instances multiple grape varieties may be listed; "
            "if so, return the primary variety. "
            "Winery is the producer or estate. Name is the specific wine, cuvee, or "
            "varietal product name, not the producer. vintage is the four-digit year "
            "as an integer. country_of_origin should be a country name only when "
            "printed on the label; do not infer it from a region. Use null when a "
            "field is absent or unreadable. Do not use "
            "arrays except for the confidence object, markdown, commentary, or "
            "invented values. If any detail is unreadable, use null."
        )

        try:
            raw = self._extract_with_ollama(prompt, img_b64)
            if not raw.strip():
                raise ValueError("Ollama returned an empty vision response.")
        except (
            requests.RequestException,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ) as e:
            local_result = {"_raw": f"ERROR: {e}", "_error": True}
            fallback_reason = "ollama_error"
        else:
            local_result = self._parse_vision_output(raw)
            fallback_reason = self._fallback_reason(local_result)
            if fallback_reason is None:
                local_result["_provider"] = "ollama"
                return local_result

        if not self.openrouter_api_key and not self.wineapi_key:
            local_result["_provider"] = "ollama"
            local_result["_fallback_status"] = "not_configured"
            return local_result

        best_result = dict(local_result)
        fallback_errors = []
        attempted_any = False

        if self.openrouter_api_key:
            attempted_any = True
            try:
                raw = self._extract_with_openrouter(prompt, img_b64, image_mime_type)
                if not raw.strip():
                    raise ValueError("OpenRouter returned an empty vision response.")
                remote_result = self._parse_vision_output(raw)
            except (
                requests.RequestException,
                ValueError,
                KeyError,
                IndexError,
                TypeError,
                AttributeError,
            ) as e:
                print(f"OpenRouter vision fallback failed: {e}")
                fallback_errors.append(str(e))
            else:
                if self._vision_quality(remote_result) > self._vision_quality(best_result):
                    best_result = {
                        **best_result,
                        **{
                            key: value
                            for key, value in remote_result.items()
                            if key == "_confidence"
                            or (not key.startswith("_") and value not in (None, ""))
                        },
                        "_provider": "openrouter",
                        "_fallback_status": "used",
                        "_fallback_reason": fallback_reason,
                    }
                    best_result.pop("_error", None)
                    if self._fallback_reason(best_result) is None:
                        return best_result

        if self.wineapi_key and self._fallback_reason(best_result) is not None:
            attempted_any = True
            try:
                wineapi_result = self._extract_with_wineapi(image_bytes, image_mime_type)
            except (
                requests.RequestException,
                ValueError,
                KeyError,
                IndexError,
                TypeError,
                AttributeError,
            ) as e:
                print(f"WineAPI.io vision fallback failed: {e}")
                fallback_errors.append(str(e))
            else:
                if self._vision_quality(wineapi_result) > self._vision_quality(best_result):
                    best_result = {
                        **best_result,
                        **{
                            key: value
                            for key, value in wineapi_result.items()
                            if key in ("_confidence", "_wineapi_id")
                            or (not key.startswith("_") and value not in (None, ""))
                        },
                        "_provider": "wineapi",
                        "_fallback_status": "used",
                        "_fallback_reason": fallback_reason,
                    }
                    best_result.pop("_error", None)
                    return best_result

        if best_result.get("_fallback_status") == "used":
            return best_result

        if fallback_errors and attempted_any:
            local_result["_provider"] = "ollama"
            local_result["_fallback_status"] = "failed"
            local_result["_fallback_error"] = "; ".join(fallback_errors)
            return local_result

        local_result["_provider"] = "ollama"
        local_result["_fallback_status"] = "no_better_result"
        local_result["_fallback_reason"] = fallback_reason
        return local_result

    def _fallback_reason(self, result: dict) -> str | None:
        if result.get("_error"):
            return "ollama_error"
        confidence = result.get("_confidence", {})
        for field in self.CORE_IDENTITY_FIELDS:
            score = confidence.get(field) if isinstance(confidence, dict) else None
            if (
                not result.get(field)
                or not isinstance(score, (int, float))
                or score < self.CONFIDENCE_THRESHOLD
            ):
                return "weak_identity_read"
        return None

    def _vision_quality(self, result: dict) -> tuple[int, float, int]:
        identity_count = sum(bool(result.get(field)) for field in self.CORE_IDENTITY_FIELDS)
        confidence = result.get("_confidence", {})
        confidence_scores = [
            confidence.get(field, 0) for field in self.CORE_IDENTITY_FIELDS
        ] if isinstance(confidence, dict) else [0, 0]
        minimum_confidence = min(
            score if isinstance(score, (int, float)) else 0
            for score in confidence_scores
        )
        extracted_count = sum(
            bool(result.get(field))
            for field in (
                "winery",
                "name",
                "vintage",
                "region",
                "country_of_origin",
                "grape_type",
            )
        )
        return identity_count, minimum_confidence, extracted_count

    def _extract_with_ollama(self, prompt: str, img_b64: str) -> str:
        response = requests.post(
            f"{self.ollama_url}/api/generate",
            json={
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "images": [img_b64],
            },
            timeout=self.settings.ollama_timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json().get("response", "")
        if not isinstance(raw, str):
            raise ValueError("Ollama returned a non-text vision response.")
        return raw

    def select_wine_candidate(
        self, anchors: dict, candidates: list[dict]
    ) -> int | str | None:
        """Select a Grapeminds result ID using the configured local Ollama model."""
        if not candidates:
            return None

        prompt = (
            "Match the wine label anchors to at most one candidate from this "
            "Grapeminds catalog list. The catalog entries are the only possible "
            "sources of truth: do not invent an ID or wine facts. Account for "
            "producer aliases, label names that omit grape/region terms, and "
            "differences in capitalization. Use region, country, grape varieties, "
            "and vintage only as supporting evidence; an absent vintage is unknown, "
            "not a conflict. Reject candidates with clear contradictions, such as "
            "a different grape variety when the label identifies one. If no candidate "
            "is a confident match, return null for id. Return exactly one JSON object "
            'in this shape: {"id": integer-or-null}. '
            f"Label anchors: {json.dumps(anchors, ensure_ascii=False)}\n"
            f"Grapeminds candidates: {json.dumps(candidates, ensure_ascii=False)}"
        )
        response = requests.post(
            f"{self.ollama_url}/api/generate",
            json={
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "10m",
                "options": {"temperature": 0},
            },
            timeout=self.settings.ollama_timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json().get("response", "")
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("Ollama returned an empty candidate-matching response.")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Ollama returned an invalid candidate-matching response.")
        selected_id = result.get("id")
        if selected_id is not None and not isinstance(selected_id, (int, str)):
            raise ValueError("Ollama returned an invalid Grapeminds candidate ID.")
        return selected_id

    def verify_wine_candidate(self, anchors: dict, candidate: dict) -> bool:
        """Check that fetched Grapeminds details agree with the label anchors."""
        verification_fields = (
            "name",
            "winery",
            "vintage",
            "region",
            "country_of_origin",
            "grape_type",
            "color",
        )
        detail_summary = {
            field: candidate.get(field) for field in verification_fields
        }
        prompt = (
            "Check whether this Grapeminds wine detail record is a plausible match "
            "for the label anchors. Return true only when the producer/wine identity "
            "is plausible and there is no clear contradiction in known country, "
            "grape variety, or vintage. Missing label facts are unknown, not "
            "contradictions. Do not correct, infer, or add any wine facts. Return "
            'exactly one JSON object: {"consistent": true} or '
            '{"consistent": false}. '
            f"Label anchors: {json.dumps(anchors, ensure_ascii=False)}\n"
            f"Grapeminds detail record: {json.dumps(detail_summary, ensure_ascii=False)}"
        )
        response = requests.post(
            f"{self.ollama_url}/api/generate",
            json={
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "10m",
                "options": {"temperature": 0},
            },
            timeout=self.settings.ollama_timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json().get("response", "")
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("Ollama returned an empty wine-verification response.")
        result = json.loads(raw)
        if not isinstance(result, dict) or not isinstance(
            result.get("consistent"), bool
        ):
            raise ValueError("Ollama returned an invalid wine-verification response.")
        return result["consistent"]

    def _extract_with_openrouter(
        self, prompt: str, img_b64: str, image_mime_type: str
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        site_url = self.settings.openrouter_site_url
        app_name = self.settings.openrouter_app_name
        if site_url:
            headers["HTTP-Referer"] = site_url
        if app_name:
            headers["X-Title"] = app_name

        response = requests.post(
            f"{self.settings.openrouter_base_url}/chat/completions",
            headers=headers,
            json={
                "model": self.openrouter_model,
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{image_mime_type};base64,{img_b64}"
                                },
                            },
                        ],
                    }
                ],
            },
            timeout=self.settings.cloud_vision_timeout_seconds,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        content = message["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text = "\n".join(
                part["text"]
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
            if text:
                return text
        raise ValueError("OpenRouter returned no text in its vision response.")

    def _parse_vision_output(self, raw: str) -> dict:
        """Parses the model's free-text output into structured fields."""
        result = {
            "winery": None,
            "name": None,
            "vintage": None,
            "region": None,
            "country_of_origin": None,
            "grape_type": None,
            "_confidence": {"winery": None, "name": None},
            "_raw": raw,
        }

        # Try JSON first, including model responses wrapped in Markdown fences.
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            try:
                parsed = json.loads(json_match.group(0)) if json_match else None
            except json.JSONDecodeError:
                parsed = None

        if isinstance(parsed, dict):
            raw_confidence = parsed.get("confidence")
            if isinstance(raw_confidence, dict):
                for field in self.CORE_IDENTITY_FIELDS:
                    score = raw_confidence.get(field)
                    try:
                        numeric_score = float(score)
                    except (TypeError, ValueError):
                        continue
                    if 0 <= numeric_score <= 1:
                        result["_confidence"][field] = numeric_score

            aliases = {
                "winery": ("winery", "winey", "producer"),
                "name": ("name", "wine", "cuvee", "cuvée"),
                "vintage": ("vintage", "year"),
                "region": ("region", "appellation"),
                "country_of_origin": ("country_of_origin", "country"),
                "grape_type": ("grape_type", "grape", "grape_variety"),
            }
            for field, keys in aliases.items():
                value = next((parsed[key] for key in keys if key in parsed), None)
                if isinstance(value, dict):
                    nested_confidence = value.get("confidence")
                    try:
                        numeric_score = float(nested_confidence)
                    except (TypeError, ValueError):
                        numeric_score = None
                    if (
                        field in self.CORE_IDENTITY_FIELDS
                        and numeric_score is not None
                        and 0 <= numeric_score <= 1
                    ):
                        result["_confidence"][field] = numeric_score
                    value = value.get("value")
                if value not in (None, "", "None", "Unknown", "null"):
                    if field == "vintage":
                        try:
                            result[field] = int(value)
                        except (TypeError, ValueError):
                            continue
                    elif isinstance(value, str):
                        result[field] = value.strip()
            if result["winery"] or result["name"]:
                return result

        # Fallback: line-by-line parsing for "Winery: X" pattern
        field_map = {
            "winery": r"(?:Winery|Producer)[:\s]+(.+?)(?:\n|$)",
            "name": r"(?:Wine|Name)[:\s]+(.+?)(?:\n|$)",
            "vintage": r"Vintage[:\s]+(\d{4})",
            "region": r"Region[:\s]+(.+?)(?:\n|$)",
            "country_of_origin": r"(?:Country of origin|Country)[:\s]+(.+?)(?:\n|$)",
            "grape_type": r"Grape[:\s]+(.+?)(?:\n|$)",
        }

        for key, pattern in field_map.items():
            match = re.search(pattern, raw, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if value and value.lower() != "none" and value.lower() != "unknown":
                    if key == "vintage":
                        try:
                            result[key] = int(value)
                        except ValueError:
                            pass
                    else:
                        result[key] = value

        # Second fallback: numbered list pattern ("1. Meerlust, 2. Rubicon, ...")
        if not result["winery"] and not result["name"]:
            numbered = re.findall(r"\d+\.\s*([^,\n.]+)", raw)
            if len(numbered) >= 2:
                result["winery"] = numbered[0].strip()
                result["name"] = numbered[1].strip()

        return result

    def _extract_with_wineapi(
        self, image_bytes: bytes, image_mime_type: str = "image/jpeg"
    ) -> dict:
        """Identify a wine label photo via WineAPI.io POST /identify/image."""
        send_bytes = image_bytes
        send_mime = image_mime_type if image_mime_type in ("image/jpeg", "image/png") else "image/jpeg"
        if image_mime_type not in ("image/jpeg", "image/png"):
            try:
                from io import BytesIO
                from PIL import Image

                with Image.open(BytesIO(image_bytes)) as img:
                    buf = BytesIO()
                    img.convert("RGB").save(buf, format="JPEG", quality=92)
                    send_bytes = buf.getvalue()
            except Exception:
                send_bytes = image_bytes

        ext = ".png" if send_mime == "image/png" else ".jpg"
        response = requests.post(
            f"{self.wineapi_base_url}/identify/image",
            headers={"X-API-Key": self.wineapi_key},
            files={"image": (f"label{ext}", send_bytes, send_mime)},
            timeout=self.settings.cloud_vision_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("WineAPI.io returned an invalid vision response.")
        parsed = self._parse_wineapi_vision_output(payload)
        if not parsed.get("winery") and not parsed.get("name"):
            raise ValueError("WineAPI.io could not identify a wine from the image.")
        return parsed

    @staticmethod
    def _clean_wineapi_candidate_name(
        name: str | None, winery: str | None, region: str | None
    ) -> str | None:
        if not name or not isinstance(name, str):
            return None
        parts = [p.strip() for p in name.split(",") if p.strip()]
        if len(parts) > 1 and winery and parts[0].lower() == str(winery).strip().lower():
            parts = parts[1:]
        if len(parts) > 1 and region and parts[-1].lower() == str(region).strip().lower():
            parts = parts[:-1]
        cleaned = ", ".join(parts).strip()
        return cleaned or name.strip()

    def _parse_wineapi_vision_output(self, payload: dict) -> dict:
        vision_details = (
            payload.get("visionDetails")
            if isinstance(payload.get("visionDetails"), dict)
            else {}
        )
        raw_text = str(vision_details.get("rawLabelText") or "").strip()
        raw_lower = raw_text.lower()

        candidates = []
        if isinstance(payload.get("wine"), dict):
            candidates.append(payload["wine"])
        if isinstance(payload.get("suggestions"), list):
            candidates.extend(
                c for c in payload["suggestions"] if isinstance(c, dict)
            )

        best = None
        best_exact = 0
        if candidates:
            if raw_lower:
                def score_candidate(item_idx_tuple):
                    idx, c = item_idx_tuple
                    c_winery = c.get("winery")
                    c_region = c.get("region")
                    c_name = (
                        self._clean_wineapi_candidate_name(
                            c.get("name"), c_winery, c_region
                        )
                        or ""
                    )
                    exact = (
                        1
                        if c_name and len(c_name) >= 3 and c_name.lower() in raw_lower
                        else 0
                    )
                    tokens = set(
                        re.findall(r"[a-z0-9]{3,}", f"{c_name} {c_region or ''}".lower())
                    )
                    tokens -= {
                        "wine",
                        "red",
                        "white",
                        "rose",
                        "blend",
                        "reserve",
                        "estate",
                        "valley",
                        "coast",
                    }
                    hits = sum(1 for t in tokens if t in raw_lower)
                    return (exact, hits, -idx)

                best_idx, best = max(enumerate(candidates), key=score_candidate)
                best_exact = score_candidate((best_idx, best))[0]
            else:
                best = candidates[0]

        winery = (
            vision_details.get("winery")
            or vision_details.get("producer")
            or (best.get("winery") if best else None)
        )
        region = vision_details.get("region") or (
            best.get("region") if best else None
        )
        country = (
            vision_details.get("country")
            or vision_details.get("country_of_origin")
            or (best.get("country") if best else None)
        )
        name = vision_details.get("name") or vision_details.get("wine")
        if not name and raw_text and best_exact == 0:
            first_line = raw_text.splitlines()[0].strip()
            if (
                re.fullmatch(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' -]{2,30}", first_line)
                and len(first_line.split()) <= 3
                and first_line.lower()
                not in {
                    str(winery or "").strip().lower(),
                    str(region or "").strip().lower(),
                    str(country or "").strip().lower(),
                }
            ):
                name = first_line
        if not name and best:
            name = self._clean_wineapi_candidate_name(
                best.get("name"), winery, region
            )

        vintage = None
        if raw_text:
            years = [
                int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-2]\d)\b", raw_text)
            ]
            if years:
                vintage = years[0]
        if vintage is None:
            raw_v = vision_details.get("vintage") or (
                best.get("vintage") if best else None
            )
            try:
                if raw_v is not None:
                    vintage = int(raw_v)
            except (TypeError, ValueError):
                vintage = None

        grape_type = (
            vision_details.get("grape")
            or vision_details.get("grape_type")
            or (best.get("grape") if best else None)
        )
        if not grape_type:
            search_target = f"{name or ''}\n{raw_text}"
            for grape in self.KNOWN_GRAPES:
                if re.search(rf"\b{re.escape(grape)}\b", search_target, re.IGNORECASE):
                    grape_type = grape
                    break

        raw_color = (
            str(
                vision_details.get("type")
                or vision_details.get("color")
                or (best.get("type") if best else "")
                or ""
            )
            .strip()
            .lower()
        )
        color = self.WINEAPI_COLOR_MAP.get(raw_color)

        conf_val = payload.get("confidence")
        if not isinstance(conf_val, (int, float)) and best:
            conf_val = best.get("confidence")
        try:
            conf_score = float(conf_val) if conf_val is not None else 0.85
        except (TypeError, ValueError):
            conf_score = 0.85
        conf_score = max(0.0, min(1.0, conf_score))

        result = {
            "winery": winery.strip() if isinstance(winery, str) and winery.strip() else None,
            "name": name.strip() if isinstance(name, str) and name.strip() else None,
            "vintage": vintage,
            "region": region.strip() if isinstance(region, str) and region.strip() else None,
            "country_of_origin": (
                country.strip() if isinstance(country, str) and country.strip() else None
            ),
            "grape_type": (
                grape_type.strip()
                if isinstance(grape_type, str) and grape_type.strip()
                else None
            ),
            "_confidence": {
                "winery": conf_score if winery else None,
                "name": conf_score if name else None,
            },
            "_raw": json.dumps(payload, ensure_ascii=False),
        }
        if color:
            result["color"] = color
        if best and best.get("id"):
            result["_wineapi_id"] = f"wineapi:{best['id']}"
        return result
