import unittest

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from database import Base, migrate_wine_metadata_columns
from models import TastingNote, WineEntry
from models import WindowStatus


class WineModelTests(unittest.TestCase):
    def test_deleting_wine_deletes_its_tasting_notes(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        with session_factory() as session:
            wine = WineEntry(qr_id="TEST-001")
            session.add(wine)
            session.flush()
            session.add(TastingNote(wine_entry_id=wine.id, notes="Bright and fresh"))
            session.commit()

            session.delete(wine)
            session.commit()

            self.assertEqual(session.query(TastingNote).count(), 0)
            self.assertEqual(session.query(WineEntry).count(), 0)
        engine.dispose()

    def test_wine_metadata_is_persisted_as_json(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        wine_metadata = {
            "color": "red",
            "country_of_origin": "South Africa",
            "grape_varieties": [{"name": "Cabernet Franc"}, {"name": "Merlot"}],
            "description": {"text": "A structured red blend."},
            "pairing": {"text": "Roast lamb."},
            "grapeminds_tasting_notes": {"text": "Blackcurrant and cedar."},
            "flavor_profile": {"body": 7, "tannins": 6},
        }
        with session_factory() as session:
            wine = WineEntry(qr_id="META-001", **wine_metadata)
            session.add(wine)
            session.commit()
            session.expire_all()

            saved = session.query(WineEntry).filter_by(qr_id="META-001").one()
            for key, value in wine_metadata.items():
                self.assertEqual(getattr(saved, key), value)
        engine.dispose()

    def test_existing_wine_table_gets_metadata_columns_idempotently(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE wine_entries (id INTEGER PRIMARY KEY, qr_id VARCHAR NOT NULL)"
            )

        migrate_wine_metadata_columns(engine)
        migrate_wine_metadata_columns(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("wine_entries")}
        self.assertTrue(
            {
                "color",
                "country_of_origin",
                "grape_varieties",
                "description",
                "pairing",
                "grapeminds_tasting_notes",
                "flavor_profile",
                "grapeminds_id",
                "comment",
            }.issubset(columns)
        )
        engine.dispose()

    def test_migration_merges_legacy_type_into_color_when_color_is_blank(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE wine_entries (id INTEGER PRIMARY KEY, qr_id VARCHAR NOT NULL, type VARCHAR, color VARCHAR)"
            )
            connection.exec_driver_sql(
                "INSERT INTO wine_entries (qr_id, type, color) VALUES "
                "('W-1', 'WHITE', NULL), "
                "('W-2', 'RED', 'red')"
            )

        migrate_wine_metadata_columns(engine)

        with engine.connect() as connection:
            rows = dict(
                connection.exec_driver_sql(
                    "SELECT qr_id, color FROM wine_entries ORDER BY qr_id"
                ).fetchall()
            )
        self.assertEqual(rows["W-1"], "White")
        self.assertEqual(rows["W-2"], "red")
        engine.dispose()


class WindowStatusEnumTests(unittest.TestCase):
    """Verify the WindowStatus enum exposes the four expected states."""

    def test_window_status_values(self):
        self.assertEqual(WindowStatus.TOO_YOUNG.value, "too_young")
        self.assertEqual(WindowStatus.IN_WINDOW.value, "in_window")
        self.assertEqual(WindowStatus.PAST_PEAK.value, "past_peak")
        self.assertEqual(WindowStatus.UNKNOWN.value, "unknown")

    def test_window_status_members_complete(self):
        members = {m.value for m in WindowStatus}
        self.assertEqual(
            members,
            {"too_young", "in_window", "past_peak", "unknown"},
        )


if __name__ == "__main__":
    unittest.main()
