import unittest
from unittest.mock import patch

from fastapi import HTTPException

import main


class ServerRestartTests(unittest.TestCase):
    def test_restart_is_unavailable_outside_supervised_service(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(HTTPException) as error:
                main.restart_server()

        self.assertEqual(error.exception.status_code, 503)

    def test_restart_schedules_a_graceful_exit_under_systemd(self):
        with (
            patch.dict("os.environ", {"WINE_APP_SUPERVISED": "systemd"}),
            patch("main.threading.Timer") as timer,
        ):
            response = main.restart_server()

        self.assertEqual(response.status, "restarting")
        timer.assert_called_once()
        self.assertEqual(timer.call_args.args[0], 2.0)
        timer.return_value.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
