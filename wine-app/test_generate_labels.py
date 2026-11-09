import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
import generate_labels
import main
import models
from database import Base


class GenerateLabelsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

    def test_template_specifications(self):
        self.assertEqual(generate_labels.LABEL_COUNT, 160)
        self.assertEqual(generate_labels.COLUMNS, 8)
        self.assertEqual(generate_labels.ROWS, 20)
        self.assertEqual(generate_labels.LABEL_WIDTH_IN, 1.0)
        self.assertEqual(generate_labels.LABEL_HEIGHT_IN, 0.5)
        self.assertEqual(generate_labels.PAGE_WIDTH_IN, 8.5)
        self.assertEqual(generate_labels.PAGE_HEIGHT_IN, 11.0)
        self.assertEqual(generate_labels.LEFT_MARGIN_IN, 0.25)
        self.assertEqual(generate_labels.TOP_MARGIN_IN, 0.5)
        self.assertEqual(generate_labels.HORIZONTAL_GAP_IN, 0.0)
        self.assertEqual(generate_labels.VERTICAL_GAP_IN, 0.0)
        self.assertIn("SpartanIndustrial", generate_labels.TEMPLATE_NAME)
        self.assertIn("R001", generate_labels.TEMPLATE_NAME)

    def test_parse_starting_label_numeric(self):
        prefix, start_num, width = generate_labels.parse_starting_label("1000")
        self.assertEqual(prefix, "")
        self.assertEqual(start_num, 1000)
        self.assertEqual(width, 4)

        prefix, start_num, width = generate_labels.parse_starting_label("1023")
        self.assertEqual(prefix, "")
        self.assertEqual(start_num, 1023)
        self.assertEqual(width, 4)

        prefix, start_num, width = generate_labels.parse_starting_label("005")
        self.assertEqual(prefix, "")
        self.assertEqual(start_num, 5)
        self.assertEqual(width, 3)

    def test_parse_starting_label_with_prefix(self):
        prefix, start_num, width = generate_labels.parse_starting_label("Basement-Rack1-1000")
        self.assertEqual(prefix, "Basement-Rack1-")
        self.assertEqual(start_num, 1000)
        self.assertEqual(width, 4)

        prefix, start_num, width = generate_labels.parse_starting_label("Wine_01")
        self.assertEqual(prefix, "Wine_")
        self.assertEqual(start_num, 1)
        self.assertEqual(width, 2)

    def test_parse_starting_label_invalid(self):
        with self.assertRaises(ValueError):
            generate_labels.parse_starting_label("NoDigitsHere")
        with self.assertRaises(ValueError):
            generate_labels.parse_starting_label("")

    def test_create_label_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "test_labels.pdf"
            first, last = generate_labels.create_label_pdf("1000", pdf_path)

            self.assertEqual(first, "1000")
            self.assertEqual(last, "1159")  # 1000 + 160 - 1
            self.assertTrue(pdf_path.is_file())
            self.assertGreater(pdf_path.stat().st_size, 50000)

    def test_check_label_conflicts_and_next_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            hist_path = out_dir / "used.json"
            generate_labels.save_used_numbers(hist_path, {1000, 1001, 1002})

            # Check starting at 1000
            conflicts = generate_labels.check_label_conflicts(
                "1000",
                output_dir=out_dir,
                history_path=hist_path,
                db=self.session,
            )
            self.assertTrue(conflicts["has_conflicts"])
            self.assertEqual(conflicts["conflicts"], [1000, 1001, 1002])
            self.assertEqual(conflicts["first_label"], "1000")
            self.assertEqual(conflicts["last_label"], "1159")

            # Check next starting label
            next_label = generate_labels.get_next_starting_label(
                output_dir=out_dir,
                history_path=hist_path,
                db=self.session,
            )
            self.assertEqual(next_label, "1003")

    def test_endpoints_direct_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with (
                patch.object(generate_labels, "DEFAULT_OUTPUT_DIR", out_dir),
                patch.object(auth, "decode_session_token", return_value={"username": "cellar", "role": "admin"}),
            ):
                mock_request = MagicMock()
                mock_request.cookies = {auth.SESSION_COOKIE: "valid_admin"}
                mock_request.base_url = "http://testserver:8000/"

                # 1. Info endpoint
                info = main.get_label_info_endpoint(db=self.session, http_request=mock_request)
                self.assertEqual(info.label_count, 160)
                self.assertEqual(info.columns, 8)
                self.assertEqual(info.rows, 20)
                self.assertIn("1\" x 0.5\"", info.dimensions)

                # 2. Check endpoint
                check_payload = main.LabelCheckRequest(starting_label="3000")
                check_resp = main.check_labels_endpoint(check_payload, db=self.session, http_request=mock_request)
                self.assertEqual(check_resp.first_label, "3000")
                self.assertEqual(check_resp.last_label, "3159")
                self.assertFalse(check_resp.has_conflicts)

                # 3. Generate endpoint
                gen_payload = main.LabelGenerateRequest(starting_label="3000", force=False)
                gen_resp = main.generate_labels_endpoint(gen_payload, db=self.session, http_request=mock_request)
                self.assertEqual(gen_resp.media_type, "application/pdf")
                self.assertEqual(gen_resp.headers["X-First-Label"], "3000")
                self.assertEqual(gen_resp.headers["X-Last-Label"], "3159")
                self.assertEqual(gen_resp.headers["X-Label-Count"], "160")
                self.assertTrue(os.path.isfile(gen_resp.path))

                # 4. Conflict check after generation
                with self.assertRaises(HTTPException) as ctx:
                    main.generate_labels_endpoint(gen_payload, db=self.session, http_request=mock_request)
                self.assertEqual(ctx.exception.status_code, 409)

                # 5. Force generation allows overwrite
                force_payload = main.LabelGenerateRequest(starting_label="3000", force=True)
                gen_forced = main.generate_labels_endpoint(force_payload, db=self.session, http_request=mock_request)
                self.assertEqual(gen_forced.media_type, "application/pdf")

    def test_non_admin_forbidden(self):
        with patch.object(auth, "decode_session_token", return_value={"username": "user1", "role": "user"}):
            mock_request = MagicMock()
            mock_request.cookies = {auth.SESSION_COOKIE: "user_token"}

            with self.assertRaises(HTTPException) as ctx:
                main.get_label_info_endpoint(db=self.session, http_request=mock_request)
            self.assertEqual(ctx.exception.status_code, 403)

            with self.assertRaises(HTTPException) as ctx:
                main.generate_labels_endpoint(
                    main.LabelGenerateRequest(starting_label="1000"),
                    db=self.session,
                    http_request=mock_request,
                )
            self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
