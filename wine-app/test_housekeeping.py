import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
import models
from database import Base


class HousekeepingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

    def test_sync_housekeeping_retains_db_images_and_prunes_orphans(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            # DB has wine with label_a.jpg
            wine1 = models.WineEntry(
                qr_id="HK-001",
                name="Test Wine 1",
                photo_path="label_a.jpg",
                status=models.WineStatus.IN_CELLAR,
            )
            wine2 = models.WineEntry(
                qr_id="HK-002",
                name="Test Wine 2",
                photo_path=None,
                status=models.WineStatus.IN_CELLAR,
            )
            self.session.add_all([wine1, wine2])
            self.session.commit()

            # Create files in temp_dir
            kept_file = os.path.join(temp_dir, "label_a.jpg")
            orphan1 = os.path.join(temp_dir, "orphan1.jpg")
            orphan2 = os.path.join(temp_dir, "orphan2.jpg")
            for f in (kept_file, orphan1, orphan2):
                with open(f, "wb") as fh:
                    fh.write(b"dummy image data")

            result = main.sync_wine_labels_housekeeping(self.session, labels_dir=temp_dir)

            self.assertEqual(result["retained"], ["label_a.jpg"])
            self.assertEqual(sorted(result["pruned"]), ["orphan1.jpg", "orphan2.jpg"])
            self.assertTrue(os.path.exists(kept_file))
            self.assertFalse(os.path.exists(orphan1))
            self.assertFalse(os.path.exists(orphan2))

    def test_delete_wine_cleans_label_when_sole_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            photo_name = "sole_wine.jpg"
            photo_file = os.path.join(temp_dir, photo_name)
            with open(photo_file, "wb") as f:
                f.write(b"image data")

            wine = models.WineEntry(
                qr_id="HK-DEL-01",
                name="Sole Bottle",
                photo_path=photo_name,
                status=models.WineStatus.IN_CELLAR,
            )
            self.session.add(wine)
            self.session.commit()

            with patch.object(main, "WINE_LABELS_DIR", temp_dir):
                main.delete_wine_endpoint(
                    qr_id="HK-DEL-01",
                    db=self.session,
                    http_request=None,
                )

            self.assertFalse(os.path.exists(photo_file))

    def test_delete_wine_preserves_label_when_shared(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            photo_name = "shared_label.jpg"
            photo_file = os.path.join(temp_dir, photo_name)
            with open(photo_file, "wb") as f:
                f.write(b"image data")

            wine1 = models.WineEntry(
                qr_id="HK-DEL-02A",
                name="Shared Bottle 1",
                photo_path=photo_name,
                status=models.WineStatus.IN_CELLAR,
            )
            wine2 = models.WineEntry(
                qr_id="HK-DEL-02B",
                name="Shared Bottle 2",
                photo_path=photo_name,
                status=models.WineStatus.IN_CELLAR,
            )
            self.session.add_all([wine1, wine2])
            self.session.commit()

            with patch.object(main, "WINE_LABELS_DIR", temp_dir):
                # Delete first bottle
                main.delete_wine_endpoint(
                    qr_id="HK-DEL-02A",
                    db=self.session,
                    http_request=None,
                )
                # Label must still exist because wine2 references it
                self.assertTrue(os.path.exists(photo_file))

                # Delete second bottle
                main.delete_wine_endpoint(
                    qr_id="HK-DEL-02B",
                    db=self.session,
                    http_request=None,
                )
                # Now that no bottles reference it, label must be pruned
                self.assertFalse(os.path.exists(photo_file))

    def test_batch_delete_cleans_photo_when_all_referencing_bottles_deleted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            photo_a = "batch_a.jpg"
            photo_b = "batch_b.jpg"
            file_a = os.path.join(temp_dir, photo_a)
            file_b = os.path.join(temp_dir, photo_b)
            for f in (file_a, file_b):
                with open(f, "wb") as fh:
                    fh.write(b"data")

            w1 = models.WineEntry(qr_id="HK-B1", name="W1", photo_path=photo_a, status=models.WineStatus.IN_CELLAR)
            w2 = models.WineEntry(qr_id="HK-B2", name="W2", photo_path=photo_a, status=models.WineStatus.IN_CELLAR)
            w3 = models.WineEntry(qr_id="HK-B3", name="W3", photo_path=photo_b, status=models.WineStatus.IN_CELLAR)
            self.session.add_all([w1, w2, w3])
            self.session.commit()

            with patch.object(main, "WINE_LABELS_DIR", temp_dir):
                batch_payload = main.WineBatchDelete(qr_ids=["HK-B1", "HK-B2"])
                main.delete_wine_batch_endpoint(
                    batch=batch_payload,
                    db=self.session,
                    http_request=None,
                )

            # batch_a should be deleted because all referencing bottles (HK-B1, HK-B2) were deleted
            self.assertFalse(os.path.exists(file_a))
            # batch_b should be untouched
            self.assertTrue(os.path.exists(file_b))


if __name__ == "__main__":
    unittest.main()
