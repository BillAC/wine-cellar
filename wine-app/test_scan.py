import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image
from fastapi import HTTPException
import qrcode

import main


class ScanTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_qr_image_decodes_bottle_url(self):
        image_bytes = BytesIO()
        qrcode.make("http://cellar.example/wines/SCAN-001").save(image_bytes, format="PNG")
        photo = SimpleNamespace(read=AsyncMock(return_value=image_bytes.getvalue()))

        result = await main.scan_bottle_qr_image(photo=photo)

        self.assertEqual(result, {"qr_id": "SCAN-001"})

    async def test_scan_qr_image_reports_unreadable_code(self):
        image_bytes = BytesIO()
        Image.new("RGB", (20, 20), color="white").save(image_bytes, format="PNG")
        photo = SimpleNamespace(read=AsyncMock(return_value=image_bytes.getvalue()))

        with self.assertRaises(HTTPException) as error:
            await main.scan_bottle_qr_image(photo=photo)

        self.assertEqual(error.exception.status_code, 422)

    async def test_label_scan_does_not_require_a_bottle_id(self):
        image_bytes = BytesIO()
        Image.new("RGB", (2, 2), color="white").save(image_bytes, format="PNG")
        photo = SimpleNamespace(read=AsyncMock(return_value=image_bytes.getvalue()))

        with tempfile.TemporaryDirectory() as upload_dir:
            with (
                patch.object(main, "UPLOAD_DIR", upload_dir),
                patch.object(main.vision, "extract_from_image", return_value={"name": "Pinot Noir"}),
                patch.object(
                    main.enricher,
                    "enrich_from_anchors",
                ) as enrich,
            ):
                result = await main.scan_wine_label(qr_id=None, photo=photo)
            self.assertEqual(result.qr_id, "")
            self.assertEqual(result.suggested_fields["name"], "Pinot Noir")
            self.assertEqual(result.enrichment_status, "not_attempted")
            self.assertIsNone(result.enrichment_metadata)
            enrich.assert_not_called()
            self.assertTrue((Path(upload_dir) / result.photo_path).is_file())

    async def test_scan_returns_vision_fields_without_grapeminds_override(self):
        image_bytes = BytesIO()
        Image.new("RGB", (2, 2), color="white").save(image_bytes, format="PNG")
        photo = SimpleNamespace(read=AsyncMock(return_value=image_bytes.getvalue()))
        vision_result = {
            "winery": "Example Estate",
            "name": "Pinot Noir",
            "vintage": 2021,
            "region": "Label region",
            "country_of_origin": "South Africa",
            "grape_type": "Label grape",
        }
        with tempfile.TemporaryDirectory() as upload_dir:
            with (
                patch.object(main, "UPLOAD_DIR", upload_dir),
                patch.object(main.vision, "extract_from_image", return_value=vision_result),
                patch.object(
                    main.enricher,
                    "enrich_from_anchors",
                ) as enrich,
            ):
                result = await main.scan_wine_label(qr_id=None, photo=photo)

        enrich.assert_not_called()
        self.assertEqual(result.enrichment_status, "not_attempted")
        self.assertIsNone(result.enrichment_metadata)
        self.assertEqual(result.suggested_fields["region"], "Label region")
        self.assertEqual(
            result.suggested_fields["country_of_origin"], "South Africa"
        )
        self.assertEqual(result.suggested_fields["grape_type"], "Label grape")
        self.assertEqual(result.suggested_fields["vintage"], 2021)

    async def test_label_scan_rejects_an_overlong_bottle_id(self):
        photo = SimpleNamespace(read=AsyncMock())

        with self.assertRaises(HTTPException) as error:
            await main.scan_wine_label(qr_id="x" * 65, photo=photo)

        self.assertEqual(error.exception.status_code, 422)
        photo.read.assert_not_awaited()

    async def test_label_scan_runs_vision_off_the_request_thread(self):
        image_bytes = BytesIO()
        Image.new("RGB", (2, 2), color="white").save(image_bytes, format="PNG")
        photo = SimpleNamespace(read=AsyncMock(return_value=image_bytes.getvalue()))

        with tempfile.TemporaryDirectory() as upload_dir:
            with (
                patch.object(main, "UPLOAD_DIR", upload_dir),
                patch.object(
                    main.vision,
                    "extract_from_image",
                    return_value={"name": "Cabernet"},
                ) as extract,
            ):
                result = await main.scan_wine_label(qr_id="1001", photo=photo)

        extract.assert_called_once()
        self.assertEqual(result.suggested_fields["name"], "Cabernet")


if __name__ == "__main__":
    unittest.main()
