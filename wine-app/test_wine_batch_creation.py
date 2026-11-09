import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
import models
from database import Base


class WineBatchCreationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

    def make_wine(self, qr_id, **overrides):
        values = {
            "qr_id": qr_id,
            "name": "Example Cabernet",
            "winery": "Example Winery",
            "is_verified": True,
        }
        values.update(overrides)
        return main.WineCreate(**values)

    def test_batch_saves_each_bottle_with_its_own_incremented_qr_id(self):
        batch = main.WineBatchCreate(
            wines=[self.make_wine(str(number)) for number in range(1000, 1006)]
        )

        saved = main.confirm_wine_batch(batch, self.session)

        self.assertEqual([wine.qr_id for wine in saved], [str(n) for n in range(1000, 1006)])
        self.assertEqual([wine.name for wine in saved], ["Example Cabernet"] * 6)
        self.assertEqual(self.session.query(models.WineEntry).count(), 6)

    def test_confirmation_persists_the_scanned_label_photo_path(self):
        wine = self.make_wine(
            "PHOTO-001",
            photo_path="a1b2c3-label.jpg",
        )

        saved = main.confirm_wine_draft(wine, self.session)

        self.assertEqual(saved.photo_path, "a1b2c3-label.jpg")
        self.assertEqual(
            self.session.query(models.WineEntry).filter_by(qr_id="PHOTO-001").one().photo_path,
            "a1b2c3-label.jpg",
        )

    def test_batch_with_an_existing_qr_id_saves_no_bottles(self):
        self.session.add(models.WineEntry(qr_id="1002"))
        self.session.commit()
        batch = main.WineBatchCreate(
            wines=[self.make_wine(str(number)) for number in range(1000, 1006)]
        )

        with self.assertRaises(HTTPException) as raised:
            main.confirm_wine_batch(batch, self.session)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.session.query(models.WineEntry).count(), 1)

    def test_batch_with_repeated_ids_is_rejected(self):
        batch = main.WineBatchCreate(
            wines=[self.make_wine("1000"), self.make_wine("1000")]
        )

        with self.assertRaises(HTTPException) as raised:
            main.confirm_wine_batch(batch, self.session)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.session.query(models.WineEntry).count(), 0)

    def test_unverified_batch_is_rejected(self):
        batch = main.WineBatchCreate(
            wines=[self.make_wine("1000", is_verified=False)]
        )

        with self.assertRaises(HTTPException) as raised:
            main.confirm_wine_batch(batch, self.session)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(self.session.query(models.WineEntry).count(), 0)

    def test_invalid_location_rejects_entire_batch(self):
        batch = main.WineBatchCreate(
            wines=[
                self.make_wine("1000"),
                self.make_wine("1001", location_id=999),
            ]
        )

        with self.assertRaises(HTTPException) as raised:
            main.confirm_wine_batch(batch, self.session)

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(self.session.query(models.WineEntry).count(), 0)


if __name__ == "__main__":
    unittest.main()
