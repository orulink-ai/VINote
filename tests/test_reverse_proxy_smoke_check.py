import unittest
from unittest.mock import patch

from scripts.check_reverse_proxy import SmokeCheckError, run_checks


class ReverseProxySmokeCheckTest(unittest.TestCase):
    def test_run_checks_passes_for_healthy_stack(self):
        responses = [
            (200, '{"status":"ok"}', {"content-type": "application/json"}),
            (200, "<!doctype html><html></html>", {"content-type": "text/html"}),
            (200, '{"authenticated":false,"user":null}', {"content-type": "application/json"}),
            (200, "<!doctype html><html><body>Docs</body></html>", {"content-type": "text/html"}),
        ]

        with patch("scripts.check_reverse_proxy.fetch_url", side_effect=responses) as mock_fetch:
            messages = run_checks(
                host="127.0.0.1",
                frontend_port=3100,
                backend_port=8900,
                docs_port=3101,
                timeout=3.0,
            )

        self.assertEqual(mock_fetch.call_count, 4)
        self.assertEqual(
            [call.args[0] for call in mock_fetch.call_args_list],
            [
                "http://127.0.0.1:8900/healthz",
                "http://127.0.0.1:3100/",
                "http://127.0.0.1:3100/api/auth/session",
                "http://127.0.0.1:3101/",
            ],
        )
        self.assertIn("Backend health endpoint is healthy.", messages)
        self.assertIn("Frontend reverse proxy to /api is healthy.", messages)

    def test_run_checks_explains_frontend_proxy_bad_gateway(self):
        responses = [
            (200, '{"status":"ok"}', {"content-type": "application/json"}),
            (200, "<!doctype html><html></html>", {"content-type": "text/html"}),
            (
                502,
                "<html><head><title>502 Bad Gateway</title></head><body>bad gateway</body></html>",
                {"content-type": "text/html"},
            ),
        ]

        with patch("scripts.check_reverse_proxy.fetch_url", side_effect=responses):
            with self.assertRaises(SmokeCheckError) as ctx:
                run_checks(
                    host="127.0.0.1",
                    frontend_port=3100,
                    backend_port=8900,
                    docs_port=None,
                    timeout=3.0,
                )

        message = str(ctx.exception)
        self.assertIn("502 Bad Gateway", message)
        self.assertIn("reverse proxy", message)
        self.assertIn("backend upstream", message)


if __name__ == "__main__":
    unittest.main()
