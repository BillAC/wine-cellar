import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import crud
import main
import models
from database import Base


class LocationManagementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.session = self.session_factory()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def create_location(self, name, parent_location_id=None):
        return main.create_location_endpoint(
            main.LocationBase(name=name, parent_location_id=parent_location_id),
            self.session,
        )

    def test_list_locations_returns_saved_locations(self):
        second = self.create_location("Second cellar")
        first = self.create_location("First cellar")

        locations = main.list_locations_endpoint(self.session)

        self.assertEqual([location.id for location in locations], [first.id, second.id])

    def test_rename_location_trims_name_and_updates_detail(self):
        location = self.create_location("Old name")

        updated = main.update_location_endpoint(
            location.id,
            main.LocationUpdate(name="  New name  ", sub_location="  North wall "),
            self.session,
        )

        self.assertEqual(updated.name, "New name")
        self.assertEqual(updated.sub_location, "North wall")

    def test_location_can_be_removed_when_empty_and_without_children(self):
        location = self.create_location("Empty rack")

        main.delete_location_endpoint(location.id, self.session)

        self.assertIsNone(self.session.get(models.Location, location.id))

    def test_location_with_wine_cannot_be_removed(self):
        location = self.create_location("Occupied rack")
        crud.create_wine(
            self.session,
            {"qr_id": "LOCATION-001", "location_id": location.id},
        )

        with self.assertRaises(HTTPException) as raised:
            main.delete_location_endpoint(location.id, self.session)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNotNone(self.session.get(models.Location, location.id))

    def test_location_with_child_cannot_be_removed(self):
        parent = self.create_location("Cellar")
        self.create_location("Rack A", parent.id)

        with self.assertRaises(HTTPException) as raised:
            main.delete_location_endpoint(parent.id, self.session)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNotNone(self.session.get(models.Location, parent.id))

    def test_missing_location_cannot_be_renamed_or_removed(self):
        with self.assertRaises(HTTPException) as rename_error:
            main.update_location_endpoint(
                999,
                main.LocationUpdate(name="Missing"),
                self.session,
            )
        with self.assertRaises(HTTPException) as delete_error:
            main.delete_location_endpoint(999, self.session)

        self.assertEqual(rename_error.exception.status_code, 404)
        self.assertEqual(delete_error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
