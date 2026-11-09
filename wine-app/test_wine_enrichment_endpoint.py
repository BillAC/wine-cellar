import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import Base
from models import WineEntry


class WineEnrichmentEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        self.wine = WineEntry(
            qr_id="LOOKUP-001",
            name="Pinot Noir",
            winery="Example Estate",
            region="User-entered region",
        )
        self.session.add(self.wine)
        self.session.commit()

    def test_draft_lookup_fetches_by_id_without_persisting_a_wine(self):
        metadata = {
            "id": "12345",
            "name": "Estate Pinot Noir",
            "winery": "Example Estate",
            "region": "Willamette Valley",
        }
        with patch.object(
            main.enricher,
            "enrich_by_id",
            return_value=(metadata, "updated"),
        ) as enrich:
            response = main.lookup_wine_draft_enrichment(
                main.GrapemindsLookupRequest(grapeminds_id="12345")
            )

        enrich.assert_called_once_with("12345")
        self.assertEqual(response.status, "updated")
        self.assertEqual(response.metadata, metadata)
        self.assertEqual(self.session.query(WineEntry).count(), 1)

    def test_existing_wine_lookup_previews_by_id_without_changing_record(self):
        metadata = {
            "id": "12345",
            "name": "Estate Pinot Noir",
            "region": "Willamette Valley",
        }
        with patch.object(
            main.enricher,
            "enrich_by_id",
            return_value=(metadata, "updated"),
        ) as enrich:
            response = main.lookup_existing_wine_enrichment_endpoint(
                "LOOKUP-001",
                main.GrapemindsLookupRequest(grapeminds_id="12345"),
                self.session,
            )

        enrich.assert_called_once_with("12345")
        self.assertEqual(response.metadata, metadata)
        self.session.expire_all()
        self.assertEqual(self.wine.name, "Pinot Noir")
        self.assertEqual(self.wine.region, "User-entered region")
        self.assertIsNone(self.wine.grapeminds_id)

    def test_apply_saves_only_selected_fields_and_catalog_id(self):
        metadata = {
            "id": "12345",
            "name": "Estate Pinot Noir",
            "region": "Willamette Valley",
            "grape_type": "Pinot Noir",
            "grape_varieties": [{"name": "Pinot Noir"}],
            "description": {"text": "Bright red fruit."},
        }
        response = main.apply_existing_wine_enrichment_endpoint(
            "LOOKUP-001",
            main.GrapemindsApplyRequest(
                grapeminds_id="12345",
                selected_fields=["region", "grape_type"],
                metadata=metadata,
            ),
            self.session,
        )

        self.assertEqual(response.grapeminds_id, "12345")
        self.assertEqual(response.name, "Pinot Noir")
        self.assertEqual(response.region, "Willamette Valley")
        self.assertEqual(response.grape_type, "Pinot Noir")
        self.assertEqual(response.grape_varieties, [{"name": "Pinot Noir"}])
        self.assertIsNone(response.description)

    def test_apply_rejects_unknown_fields(self):
        with self.assertRaises(HTTPException) as error:
            main.apply_existing_wine_enrichment_endpoint(
                "LOOKUP-001",
                main.GrapemindsApplyRequest(
                    grapeminds_id="12345",
                    selected_fields=["qr_id"],
                    metadata={"qr_id": "OTHER"},
                ),
                self.session,
            )

        self.assertEqual(error.exception.status_code, 422)
        self.session.expire_all()
        self.assertEqual(self.wine.qr_id, "LOOKUP-001")
        self.assertIsNone(self.wine.grapeminds_id)

    def test_lookup_for_unknown_wine_returns_404(self):
        with self.assertRaises(HTTPException) as error:
            main.lookup_existing_wine_enrichment_endpoint(
                "MISSING",
                main.GrapemindsLookupRequest(grapeminds_id="12345"),
                self.session,
            )
        self.assertEqual(error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
