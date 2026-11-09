import datetime
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
import models
from database import Base
from models import TastingNote, WineEntry, WineStatus


class WineRemovalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

        self.wine = WineEntry(
            qr_id="BOTTLE-REMOVE-001",
            name="Reserve Cabernet",
            winery="Napa Cellars",
            vintage=2018,
            status=WineStatus.IN_CELLAR,
        )
        self.session.add(self.wine)
        self.session.commit()

    def test_remove_bottle_with_tasting_note_and_sensory_details(self):
        today = datetime.date.today()
        request = main.WineRemovalRequest(
            status=WineStatus.REMOVED,
            tasting_note=main.TastingNoteBase(
                notes="Rich dark fruit, velvety tannins, paired wonderfully with steak.",
                tasting_date=today,
                tannin=0.8,
                acidity=0.6,
                body=0.9,
                alcohol=0.7,
                fruit_intensity=0.8,
                aroma_tags="Blackberry, Oak, Vanilla",
            ),
        )

        result = main.remove_wine_endpoint("BOTTLE-REMOVE-001", request, self.session)

        self.assertEqual(result.status, WineStatus.REMOVED)
        self.assertEqual(len(result.tasting_notes), 1)
        note = result.tasting_notes[0]
        self.assertEqual(note.notes, "Rich dark fruit, velvety tannins, paired wonderfully with steak.")
        self.assertEqual(note.tasting_date, today)
        self.assertEqual(note.tannin, 0.8)
        self.assertEqual(note.acidity, 0.6)
        self.assertEqual(note.body, 0.9)
        self.assertEqual(note.alcohol, 0.7)
        self.assertEqual(note.fruit_intensity, 0.8)
        self.assertEqual(note.aroma_tags, "Blackberry, Oak, Vanilla")

        # Verify wine remains safely in database
        self.session.expire_all()
        db_wine = self.session.query(WineEntry).filter_by(qr_id="BOTTLE-REMOVE-001").one()
        self.assertEqual(db_wine.status, WineStatus.REMOVED)
        self.assertEqual(db_wine.name, "Reserve Cabernet")
        self.assertEqual(len(db_wine.tasting_notes), 1)

    def test_remove_bottle_without_tasting_note(self):
        request = main.WineRemovalRequest(
            status=WineStatus.REMOVED,
            tasting_note=None,
        )

        result = main.remove_wine_endpoint("BOTTLE-REMOVE-001", request, self.session)

        self.assertEqual(result.status, WineStatus.REMOVED)
        self.assertEqual(len(result.tasting_notes), 0)

        # Verify wine remains in DB
        self.session.expire_all()
        db_wine = self.session.query(WineEntry).filter_by(qr_id="BOTTLE-REMOVE-001").one()
        self.assertEqual(db_wine.status, WineStatus.REMOVED)

    def test_remove_bottle_with_gifted_status(self):
        request = main.WineRemovalRequest(
            status=WineStatus.GIFTED,
            tasting_note=None,
        )

        result = main.remove_wine_endpoint("BOTTLE-REMOVE-001", request, self.session)
        self.assertEqual(result.status, WineStatus.GIFTED)

    def test_remove_bottle_preserves_existing_tasting_notes(self):
        # Add an initial tasting note
        initial_note = TastingNote(
            wine_entry_id=self.wine.id,
            notes="Barrel sample test",
            tasting_date=datetime.date(2025, 1, 1),
        )
        self.session.add(initial_note)
        self.session.commit()

        # Now remove bottle with a second tasting note
        request = main.WineRemovalRequest(
            status=WineStatus.REMOVED,
            tasting_note=main.TastingNoteBase(
                notes="Drank bottle with friends.",
                tasting_date=datetime.date(2026, 10, 21),
            ),
        )

        result = main.remove_wine_endpoint("BOTTLE-REMOVE-001", request, self.session)
        self.assertEqual(len(result.tasting_notes), 2)
        notes_text = [n.notes for n in result.tasting_notes]
        self.assertIn("Barrel sample test", notes_text)
        self.assertIn("Drank bottle with friends.", notes_text)

    def test_checkout_bottle_saves_date_comment_and_group_taste_pairing(self):
        sibling = WineEntry(
            qr_id="BOTTLE-REMOVE-002",
            name="Reserve Cabernet",
            winery="Napa Cellars",
            vintage=2018,
            status=WineStatus.IN_CELLAR,
        )
        self.session.add(sibling)
        self.session.commit()

        checkout_day = datetime.date(2026, 11, 4)
        request = main.WineRemovalRequest(
            status=WineStatus.REMOVED,
            checkout_date=checkout_day,
            comment="Opened for anniversary dinner",
            pairing="Grilled ribeye steak",
            grapeminds_tasting_notes="Blackcurrant, cedar, long finish",
            apply_to_group_qr_ids=["BOTTLE-REMOVE-001", "BOTTLE-REMOVE-002"],
        )

        result = main.remove_wine_endpoint("BOTTLE-REMOVE-001", request, self.session)
        self.assertEqual(result.status, WineStatus.REMOVED)
        self.assertEqual(result.checkout_date, checkout_day)
        self.assertEqual(result.comment, "Opened for anniversary dinner")
        self.assertEqual(result.pairing, "Grilled ribeye steak")
        self.assertEqual(result.grapeminds_tasting_notes, "Blackcurrant, cedar, long finish")

        # Sibling bottle remains in_cellar without checkout_date/comment, but receives group taste & pairing
        self.session.expire_all()
        db_sibling = self.session.query(WineEntry).filter_by(qr_id="BOTTLE-REMOVE-002").one()
        self.assertEqual(db_sibling.status, WineStatus.IN_CELLAR)
        self.assertIsNone(db_sibling.checkout_date)
        self.assertIsNone(db_sibling.comment)
        self.assertEqual(db_sibling.pairing, "Grilled ribeye steak")
        self.assertEqual(db_sibling.grapeminds_tasting_notes, "Blackcurrant, cedar, long finish")

    def test_remove_missing_bottle_returns_404(self):
        request = main.WineRemovalRequest(status=WineStatus.REMOVED)
        with self.assertRaises(HTTPException) as ctx:
            main.remove_wine_endpoint("NONEXISTENT", request, self.session)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
