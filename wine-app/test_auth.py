import os
import time
import unittest
from unittest.mock import patch

import auth


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "CELLAR_USERNAME": "cellar-owner",
                "CELLAR_PASSWORD": "TestPassword123!",
                "CELLAR_SESSION_SECRET": "a-session-signing-secret-at-least-32-chars",
            },
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_credentials_must_both_match(self):
        self.assertTrue(auth.verify_credentials("cellar-owner", "TestPassword123!"))
        self.assertFalse(auth.verify_credentials("someone-else", "TestPassword123!"))
        self.assertFalse(auth.verify_credentials("cellar-owner", "wrong-password"))

    def test_password_of_requested_length_is_accepted(self):
        with patch.dict(
            os.environ, {"CELLAR_PASSWORD": "TestPassword123!"}, clear=False
        ):
            auth.validate_configuration()

    def test_signed_session_is_valid_until_tampered_or_expired(self):
        token = auth.create_session_token()
        self.assertTrue(auth.validate_session_token(token))
        self.assertFalse(auth.validate_session_token(token + "x"))
        self.assertFalse(auth.validate_session_token("not-a-token"))

        with patch(
            "auth.time.time",
            return_value=time.time() + auth.session_ttl_seconds() + 1,
        ):
            self.assertFalse(auth.validate_session_token(token))

    def test_session_secret_must_be_long_enough(self):
        with patch.dict(os.environ, {"CELLAR_SESSION_SECRET": "short"}, clear=False):
            with self.assertRaisesRegex(ValueError, "at least 32 characters"):
                auth.create_session_token()

    def test_session_lifetime_is_configurable_in_hours(self):
        with patch.dict(os.environ, {"CELLAR_SESSION_TTL_HOURS": "24"}, clear=False):
            self.assertEqual(auth.session_ttl_seconds(), 24 * 60 * 60)

    def test_existing_days_setting_configures_session_lifetime(self):
        with patch.dict(
            os.environ,
            {"WINE_APP_TTL_DAYS": "30", "CELLAR_SESSION_TTL_HOURS": ""},
            clear=False,
        ):
            self.assertEqual(auth.session_ttl_seconds(), 30 * 24 * 60 * 60)

    def test_password_must_contain_at_least_ten_characters(self):
        with patch.dict(os.environ, {"CELLAR_PASSWORD": "short"}, clear=False):
            with self.assertRaisesRegex(ValueError, "at least 10 characters"):
                auth.validate_configuration()


if __name__ == "__main__":
    unittest.main()
