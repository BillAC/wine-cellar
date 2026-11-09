import tempfile
import unittest
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import crud
import main
import models
from database import Base


class SessionFeaturesBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

    def test_01_location_hierarchy_and_group_edit_persistence(self):
        parent = main.create_location_endpoint(
            main.LocationBase(name="Cellar Rack A", sub_location="Top"),
            self.session,
        )
        child = main.create_location_endpoint(
            main.LocationBase(
                name="Row 1",
                sub_location="Left",
                parent_location_id=parent.id,
            ),
            self.session,
        )

        for qr in ("B-101", "B-102"):
            crud.create_wine(
                self.session,
                {
                    "qr_id": qr,
                    "name": "Estate Reserve",
                    "winery": "Test Winery",
                    "vintage": 2020,
                    "color": "Red",
                    "location_id": parent.id,
                },
            )

        batch_req = main.WineBatchUpdate(
            qr_ids=["B-101", "B-102"],
            updates=main.WineUpdate(
                color="White",
                location_id=child.id,
                comment="Anniversary bottle",
                market_price=65.50,
                purchase_price=48.00,
                drink_from=2024,
                drink_until=2030,
            ),
            force_move=True,
        )
        updated = main.update_wine_batch_endpoint(batch_req, self.session)
        self.assertEqual(len(updated), 2)
        for bottle in updated:
            self.assertEqual(bottle.color, "White")
            self.assertEqual(bottle.location_id, child.id)
            self.assertEqual(bottle.location.name, "Row 1")
            self.assertEqual(bottle.comment, "Anniversary bottle")
            self.assertEqual(bottle.market_price, 65.50)
            self.assertEqual(bottle.purchase_price, 48.00)
            self.assertEqual(bottle.drink_from, 2024)
            self.assertEqual(bottle.drink_until, 2030)

    def test_02_drinking_window_validation(self):
        # drink_until < drink_from raises ValidationError
        with self.assertRaises(ValidationError):
            main.WineCreate(
                qr_id="DW-BAD",
                name="Test Wine",
                drink_from=2030,
                drink_until=2025,
                is_verified=True,
            )

        # Out-of-range year (< 1800 or > 2200) raises ValidationError
        with self.assertRaises(ValidationError):
            main.WineCreate(
                qr_id="DW-BAD2",
                name="Test Wine",
                drink_from=1700,
                is_verified=True,
            )

        good = main.confirm_wine_draft(
            main.WineCreate(
                qr_id="DW-GOOD",
                name="Test Wine",
                drink_from=2024,
                drink_until=2028,
                market_price=42.0,
                color="Red",
                is_verified=True,
            ),
            self.session,
        )
        self.assertEqual(good.drink_from, 2024)
        self.assertEqual(good.drink_until, 2028)
        self.assertEqual(good.market_price, 42.0)
        self.assertEqual(good.color, "Red")

    def test_03_checkout_workflow_and_group_vs_single_scope_and_return(self):
        for qr in ("CHK-1", "CHK-2"):
            crud.create_wine(
                self.session,
                {
                    "qr_id": qr,
                    "name": "Rubicon",
                    "winery": "Meerlust",
                    "vintage": 2018,
                    "color": "Red",
                    "grapeminds_tasting_notes": "Original notes",
                    "pairing": "Original pairing",
                },
            )

        # 1) Check out CHK-1 with apply_to_group_qr_ids
        chk_res = main.remove_wine_endpoint(
            "CHK-1",
            main.WineRemovalRequest(
                status=models.WineStatus.REMOVED,
                checkout_date=date(2026, 11, 4),
                comment="Opened",
                grapeminds_tasting_notes="Cedar, cassis, dark plum",
                pairing="Grilled ribeye steak",
                apply_to_group_qr_ids=["CHK-1", "CHK-2"],
            ),
            self.session,
        )
        self.assertEqual(chk_res.status, models.WineStatus.REMOVED)
        self.assertEqual(chk_res.checkout_date, date(2026, 11, 4))
        self.assertEqual(chk_res.comment, "Opened")
        self.assertEqual(chk_res.grapeminds_tasting_notes, "Cedar, cassis, dark plum")
        self.assertEqual(chk_res.pairing, "Grilled ribeye steak")

        # Verify CHK-2 also received the updated tasting notes & pairing, while staying in_cellar
        b2 = crud.get_wine_by_qr_id(self.session, "CHK-2")
        self.assertEqual(b2.status, models.WineStatus.IN_CELLAR)
        self.assertEqual(b2.grapeminds_tasting_notes, "Cedar, cassis, dark plum")
        self.assertEqual(b2.pairing, "Grilled ribeye steak")

        # 2) Return CHK-1 to cellar
        b1_ret = main.update_wine_status_endpoint(
            "CHK-1",
            new_status=models.WineStatus.IN_CELLAR,
            db=self.session,
        )
        self.assertEqual(b1_ret.status, models.WineStatus.IN_CELLAR)

        # 3) Check out CHK-1 for single bottle only (no apply_to_group_qr_ids)
        chk_single = main.remove_wine_endpoint(
            "CHK-1",
            main.WineRemovalRequest(
                status=models.WineStatus.GIFTED,
                checkout_date=date(2026, 11, 4),
                comment="Gifted to friend",
                grapeminds_tasting_notes="Single bottle note only",
                pairing="Lamb chops",
            ),
            self.session,
        )
        self.assertEqual(chk_single.comment, "Gifted to friend")
        self.session.expire_all()
        b2_after = crud.get_wine_by_qr_id(self.session, "CHK-2")
        self.assertEqual(b2_after.grapeminds_tasting_notes, "Cedar, cassis, dark plum")
        self.assertEqual(b2_after.pairing, "Grilled ribeye steak")

    def test_04_wineapi_lookup_request_accepts_colon_prefixed_id(self):
        req = main.GrapemindsLookupRequest(
            grapeminds_id="wineapi:0d487bb6-d110-4a5c-81d5-cb5ef7835b4d"
        )
        self.assertEqual(
            req.grapeminds_id, "wineapi:0d487bb6-d110-4a5c-81d5-cb5ef7835b4d"
        )

    def test_05_explorer_provider_selection_and_automatic_fallback(self):
        # 1) Primary provider wineapi returns results -> no fallback needed
        with (
            patch.object(
                main.enricher,
                "search_wineapi_wines",
                return_value=[{"id": "wineapi:123", "name": "Test Wine", "provider": "wineapi"}],
            ) as wapi_search,
            patch.object(main.enricher, "search_wines") as gm_search,
        ):
            body = main.search_grapeminds_wines(
                q="Meerlust", provider="wineapi", include_meta=True, db=self.session
            )
            self.assertEqual(body["active_provider"], "wineapi")
            self.assertFalse(body["fallback_used"])
            self.assertEqual(len(body["results"]), 1)
            wapi_search.assert_called_once()
            gm_search.assert_not_called()

        # 2) Primary provider wineapi returns empty -> automatically falls back to grapeminds
        with (
            patch.object(
                main.enricher,
                "search_wineapi_wines",
                return_value=[],
            ) as wapi_search,
            patch.object(
                main.enricher,
                "search_wines",
                return_value=[{"id": "999", "name": "Fallback Wine", "provider": "grapeminds"}],
            ) as gm_search,
        ):
            body = main.search_grapeminds_wines(
                q="RareWine", provider="wineapi", include_meta=True, db=self.session
            )
            self.assertEqual(body["active_provider"], "grapeminds")
            self.assertTrue(body["fallback_used"])
            self.assertEqual(body["results"][0]["name"], "Fallback Wine")
            wapi_search.assert_called_once()
            gm_search.assert_called_once()

        # 3) Primary provider grapeminds returns empty -> automatically falls back to wineapi
        with (
            patch.object(
                main.enricher,
                "search_wines",
                return_value=[],
            ) as gm_search,
            patch.object(
                main.enricher,
                "search_wineapi_wines",
                return_value=[{"id": "wineapi:abc", "name": "WineAPI Fallback", "provider": "wineapi"}],
            ) as wapi_search,
        ):
            body = main.search_grapeminds_wines(
                q="USAWine", provider="grapeminds", include_meta=True, db=self.session
            )
            self.assertEqual(body["active_provider"], "wineapi")
            self.assertTrue(body["fallback_used"])
            self.assertEqual(body["results"][0]["id"], "wineapi:abc")

    async def test_06_scan_endpoint_with_wineapi_vision_fallback(self):
        img_buf = BytesIO()
        Image.new("RGB", (10, 10), color="white").save(img_buf, format="JPEG")
        photo = SimpleNamespace(read=AsyncMock(return_value=img_buf.getvalue()))

        mock_vision = {
            "winery": "RouteStock",
            "name": "Pinot Noir",
            "vintage": 2023,
            "region": "Sonoma Coast",
            "country_of_origin": "United States",
            "grape_type": "Pinot Noir",
            "color": "Red",
            "_provider": "wineapi",
            "_fallback_status": "used",
            "_wineapi_id": "wineapi:0d487bb6-d110-4a5c-81d5-cb5ef7835b4d",
        }
        with tempfile.TemporaryDirectory() as upload_dir:
            with (
                patch.object(main, "UPLOAD_DIR", upload_dir),
                patch.object(main.vision, "extract_from_image", return_value=mock_vision),
            ):
                draft = await main.scan_wine_label(qr_id="SCAN-1", photo=photo)

        self.assertEqual(draft.suggested_fields["winery"], "RouteStock")
        self.assertEqual(draft.suggested_fields["name"], "Pinot Noir")
        self.assertEqual(draft.suggested_fields["color"], "Red")
        self.assertEqual(
            draft.grapeminds_id, "wineapi:0d487bb6-d110-4a5c-81d5-cb5ef7835b4d"
        )


if __name__ == "__main__":
    unittest.main()
