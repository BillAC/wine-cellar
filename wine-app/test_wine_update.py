import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import Base
from models import Location, WineEntry


class WineUpdateTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        self.wines = [
            WineEntry(qr_id="BOTTLE-001", name="Pinot Noir", winery="Example Estate"),
            WineEntry(qr_id="BOTTLE-002", name="Pinot Noir", winery="Example Estate"),
        ]
        self.session.add_all(self.wines)
        self.session.commit()

    def test_updates_one_bottle_without_changing_other_bottles(self):
        updated = main.update_wine_endpoint(
            "BOTTLE-001",
            main.WineUpdate(name="Estate Pinot Noir", region="Willamette Valley"),
            self.session,
        )

        self.assertEqual(updated.name, "Estate Pinot Noir")
        self.assertEqual(updated.region, "Willamette Valley")
        self.session.expire_all()
        untouched = self.session.query(WineEntry).filter_by(qr_id="BOTTLE-002").one()
        self.assertEqual(untouched.name, "Pinot Noir")
        self.assertIsNone(untouched.region)

    def test_updates_bottle_storage_location(self):
        location = Location(name="Rack A")
        self.session.add(location)
        self.session.commit()

        updated = main.update_wine_endpoint(
            "BOTTLE-001",
            main.WineUpdate(location_id=location.id),
            self.session,
        )

        self.assertEqual(updated.location_id, location.id)
        self.assertEqual(updated.location.name, "Rack A")

    def test_updates_group_atomically_and_preserves_bottle_specific_fields(self):
        location = Location(name="Rack A")
        self.session.add(location)
        self.session.flush()
        self.wines[0].location_id = location.id
        self.wines[0].purchase_price = 20
        self.session.commit()
        request = main.WineBatchUpdate(
            qr_ids=["BOTTLE-001", "BOTTLE-002"],
            updates=main.WineUpdate(name="Estate Pinot Noir", region="Willamette Valley"),
        )

        updated = main.update_wine_batch_endpoint(request, self.session)

        self.assertEqual([wine.qr_id for wine in updated], ["BOTTLE-001", "BOTTLE-002"])
        self.assertEqual([wine.name for wine in updated], ["Estate Pinot Noir"] * 2)
        self.assertEqual(self.wines[0].location_id, location.id)
        self.assertEqual(self.wines[0].purchase_price, 20)

    def test_group_update_validates_storage_location(self):
        request = main.WineBatchUpdate(
            qr_ids=["BOTTLE-001", "BOTTLE-002"],
            updates=main.WineUpdate(location_id=999),
        )

        with self.assertRaises(HTTPException) as error:
            main.update_wine_batch_endpoint(request, self.session)

        self.assertEqual(error.exception.status_code, 422)
        self.session.expire_all()
        self.assertIsNone(self.wines[0].location_id)

    def test_group_update_batch_move_detects_location_conflict(self):
        loc_a = Location(name="Rack A")
        loc_b = Location(name="Rack B")
        new_loc = Location(name="Rack C")
        self.session.add_all([loc_a, loc_b, new_loc])
        self.session.flush()
        self.wines[0].location_id = loc_a.id
        self.wines[1].location_id = loc_b.id
        self.session.commit()

        request = main.WineBatchUpdate(
            qr_ids=["BOTTLE-001", "BOTTLE-002"],
            updates=main.WineUpdate(location_id=new_loc.id),
            force_move=False,
        )

        with self.assertRaises(HTTPException) as error:
            main.update_wine_batch_endpoint(request, self.session)

        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("conflicts", error.exception.detail)
        self.assertEqual(len(error.exception.detail["conflicts"]), 2)
        self.session.expire_all()
        self.assertEqual(self.wines[0].location_id, loc_a.id)
        self.assertEqual(self.wines[1].location_id, loc_b.id)

    def test_group_update_batch_move_with_force_move(self):
        loc_a = Location(name="Rack A")
        loc_b = Location(name="Rack B")
        new_loc = Location(name="Rack C")
        self.session.add_all([loc_a, loc_b, new_loc])
        self.session.flush()
        self.wines[0].location_id = loc_a.id
        self.wines[1].location_id = loc_b.id
        self.session.commit()

        request = main.WineBatchUpdate(
            qr_ids=["BOTTLE-001", "BOTTLE-002"],
            updates=main.WineUpdate(location_id=new_loc.id),
            force_move=True,
        )

        updated = main.update_wine_batch_endpoint(request, self.session)
        self.assertEqual([w.location_id for w in updated], [new_loc.id, new_loc.id])
        self.session.expire_all()
        self.assertEqual(self.wines[0].location_id, new_loc.id)
        self.assertEqual(self.wines[1].location_id, new_loc.id)

    def test_group_update_batch_move_when_bottles_share_location(self):
        loc = Location(name="Rack A")
        new_loc = Location(name="Rack B")
        self.session.add_all([loc, new_loc])
        self.session.flush()
        self.wines[0].location_id = loc.id
        self.wines[1].location_id = loc.id
        self.session.commit()

        request = main.WineBatchUpdate(
            qr_ids=["BOTTLE-001", "BOTTLE-002"],
            updates=main.WineUpdate(location_id=new_loc.id),
            force_move=False,
        )

        updated = main.update_wine_batch_endpoint(request, self.session)
        self.assertEqual([w.location_id for w in updated], [new_loc.id, new_loc.id])

    def test_group_update_rejects_missing_bottles_without_partial_changes(self):
        request = main.WineBatchUpdate(
            qr_ids=["BOTTLE-001", "MISSING"],
            updates=main.WineUpdate(name="Updated"),
        )

        with self.assertRaises(HTTPException) as error:
            main.update_wine_batch_endpoint(request, self.session)

        self.assertEqual(error.exception.status_code, 404)
        self.session.expire_all()
        self.assertEqual(self.wines[0].name, "Pinot Noir")

    def test_individual_update_validates_location(self):
        with self.assertRaises(HTTPException) as error:
            main.update_wine_endpoint(
                "BOTTLE-001",
                main.WineUpdate(location_id=999),
                self.session,
            )

        self.assertEqual(error.exception.status_code, 422)
        self.session.expire_all()
        self.assertIsNone(self.wines[0].location_id)

    def test_update_and_filter_by_grapeminds_id(self):
        import crud

        # 1. Update individual wine with grapeminds_id
        updated = main.update_wine_endpoint(
            "BOTTLE-001",
            main.WineUpdate(grapeminds_id="GM-54321"),
            self.session,
        )
        self.assertEqual(updated.grapeminds_id, "GM-54321")

        # 2. Batch update with grapeminds_id
        batch_req = main.WineBatchUpdate(
            qr_ids=["BOTTLE-001", "BOTTLE-002"],
            updates=main.WineUpdate(grapeminds_id="GM-SHARED-99"),
        )
        main.update_wine_batch_endpoint(batch_req, self.session)

        # 3. CRUD helper lookup
        matched = crud.get_wines_by_grapeminds_id(self.session, "GM-SHARED-99")
        self.assertEqual(len(matched), 2)
        self.assertEqual({w.qr_id for w in matched}, {"BOTTLE-001", "BOTTLE-002"})

        # 4. list_wines_endpoint filtering
        filtered = main.list_wines_endpoint(grapeminds_id="GM-SHARED-99", db=self.session)
        self.assertEqual(len(filtered), 2)

        no_match = main.list_wines_endpoint(grapeminds_id="NON-EXISTENT", db=self.session)
        self.assertEqual(len(no_match), 0)

    def test_updates_comment_and_color_on_single_and_batch_wines(self):
        updated = main.update_wine_endpoint(
            "BOTTLE-001",
            main.WineUpdate(color="Red", comment="Gift from Sarah"),
            self.session,
        )
        self.assertEqual(updated.color, "Red")
        self.assertEqual(updated.comment, "Gift from Sarah")

        batch_req = main.WineBatchUpdate(
            qr_ids=["BOTTLE-001", "BOTTLE-002"],
            updates=main.WineUpdate(comment="Drink with ribeye"),
        )
        batch_updated = main.update_wine_batch_endpoint(batch_req, self.session)
        self.assertEqual([w.comment for w in batch_updated], ["Drink with ribeye", "Drink with ribeye"])


if __name__ == "__main__":
    unittest.main()
