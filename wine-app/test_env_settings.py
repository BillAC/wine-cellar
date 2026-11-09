import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import env_settings


class EnvSettingsTests(unittest.TestCase):
    def test_env_auth_fills_only_keys_missing_from_env(self):
        with TemporaryDirectory() as temp_dir:
            Path(temp_dir, ".env").write_text(
                "CELLAR_USERNAME=from-env\n"
                "CELLAR_PASSWORD=\n"
                "OPENROUTER_API_KEY=vision-key\n"
            )
            Path(temp_dir, ".env.auth").write_text(
                "CELLAR_USERNAME=from-auth\nCELLAR_PASSWORD=from-auth-password\n"
            )
            with (
                patch.object(env_settings, "APP_DIR", temp_dir),
                patch.dict(os.environ, {}, clear=True),
            ):
                env_settings.load_app_env()
                self.assertEqual(os.environ["CELLAR_USERNAME"], "from-env")
                self.assertEqual(os.environ["CELLAR_PASSWORD"], "from-auth-password")
                self.assertEqual(os.environ["OPENROUTER_API_KEY"], "vision-key")

    def test_settings_read_typed_values_and_resolve_relative_paths(self):
        with TemporaryDirectory() as temp_dir:
            with (
                patch.object(env_settings, "APP_DIR", Path(temp_dir)),
                patch.dict(
                    os.environ,
                    {
                        "CELLAR_USERNAME": "cellar",
                        "CELLAR_SESSION_TTL_HOURS": "24",
                        "PASSWORD_RESET_TTL_HOURS": "2",
                        "ACCOUNT_ACTIVATION_TTL_HOURS": "72",
                        "CELLAR_COOKIE_SECURE": "true",
                        "WINE_APP_DATA_DIR": "data",
                        "GRAPEMINDS_MONTHLY_LIMIT": "50",
                        "SMTP_TLS": "false",
                    },
                    clear=True,
                ),
            ):
                settings = env_settings.get_settings()

        self.assertEqual(settings.cellar_username, "cellar")
        self.assertEqual(settings.session_ttl_hours, 24)
        self.assertEqual(settings.password_reset_ttl_hours, 2)
        self.assertEqual(settings.account_activation_ttl_hours, 72)
        self.assertTrue(settings.cookie_secure)
        self.assertEqual(settings.data_dir, Path(temp_dir) / "data")
        self.assertEqual(settings.wine_labels_dir, Path(temp_dir) / "data" / "wine-labels")
        self.assertEqual(settings.grapeminds_monthly_limit, 50)
        self.assertFalse(settings.smtp_tls)
        self.assertEqual(
            settings.database_url,
            f"sqlite:////{Path(temp_dir).as_posix().lstrip('/')}/data/wine_cellar.db",
        )

    def test_invalid_boolean_configuration_fails_explicitly(self):
        with patch.dict(
            os.environ, {"CELLAR_COOKIE_SECURE": "sometimes"}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "CELLAR_COOKIE_SECURE"):
                env_settings.get_settings()

    def test_non_positive_limits_fail_explicitly(self):
        with patch.dict(
            os.environ, {"GRAPEMINDS_MONTHLY_LIMIT": "0"}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "GRAPEMINDS_MONTHLY_LIMIT"):
                env_settings.get_settings()


if __name__ == "__main__":
    unittest.main()
