import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market_lab.alpaca import AlpacaAPIError, AlpacaReadOnlyClient, load_alpaca_credentials, sanitized_account_status


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class AlpacaReadOnlyTests(unittest.TestCase):
    def test_loads_named_env_file_without_requiring_process_env(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".alpaca.env"
            path.write_text("APCA_API_KEY_ID=key123\nAPCA_API_SECRET_KEY=secret456\nALPACA_MODE=paper\n")
            creds = load_alpaca_credentials(path)
            self.assertEqual(creds.api_key_id, "key123")
            self.assertEqual(creds.api_secret_key, "secret456")
            self.assertEqual(creds.mode, "paper")
            self.assertEqual(creds.trading_base_url, "https://paper-api.alpaca.markets")

    def test_loads_two_line_local_file_format(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".alpaca.env"
            path.write_text("raw-key\nraw-secret\n")
            creds = load_alpaca_credentials(path)
            self.assertEqual(creds.api_key_id, "raw-key")
            self.assertEqual(creds.api_secret_key, "raw-secret")

    def test_client_uses_get_only_and_secret_headers(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".alpaca.env"
            path.write_text("APCA_API_KEY_ID=key123\nAPCA_API_SECRET_KEY=secret456\n")
            client = AlpacaReadOnlyClient(load_alpaca_credentials(path))
            captured = {}

            def fake_urlopen(request, timeout=0):
                captured["method"] = request.get_method()
                captured["headers"] = dict(request.header_items())
                captured["url"] = request.full_url
                return _FakeResponse({"status": "ACTIVE", "currency": "USD", "trading_blocked": False})

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                status = sanitized_account_status(client)
            self.assertEqual(captured["method"], "GET")
            self.assertIn("/v2/account", captured["url"])
            header_values = {k.lower(): v for k, v in captured["headers"].items()}
            self.assertEqual(header_values.get("apca-api-key-id"), "key123")
            self.assertEqual(header_values.get("apca-api-secret-key"), "secret456")
            self.assertEqual(status["status"], "ACTIVE")
            self.assertNotIn("api_key_id", status)

    def test_stock_bars_parses_symbol_bucket(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".alpaca.env"
            path.write_text("raw-key\nraw-secret\n")
            client = AlpacaReadOnlyClient(load_alpaca_credentials(path))

            with patch("urllib.request.urlopen", return_value=_FakeResponse({"bars": {"SPY": [{"c": 500.0}]}})):
                bars = client.stock_bars("spy", start="2026-01-01", limit=1)
            self.assertEqual(bars, [{"c": 500.0}])

    def test_http_error_is_sanitized_exception(self):
        import urllib.error

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".alpaca.env"
            path.write_text("raw-key\nraw-secret\n")
            client = AlpacaReadOnlyClient(load_alpaca_credentials(path))
            import io
            from email.message import Message
            err = urllib.error.HTTPError("https://paper-api.alpaca.markets/v2/account", 401, "Unauthorized", Message(), io.BytesIO(b'{"message":"unauthorized."}'))
            with patch("urllib.request.urlopen", side_effect=err):
                with self.assertRaises(AlpacaAPIError) as ctx:
                    client.account()
            self.assertEqual(ctx.exception.status, 401)
            self.assertIn("unauthorized", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
