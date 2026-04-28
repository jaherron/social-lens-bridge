import io
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from social_lens_bridge.http import HttpJsonClient, HttpJsonError


class HttpTests(unittest.TestCase):
    def test_default_user_agent_does_not_use_python_urllib(self) -> None:
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def read(self) -> bytes:
                return b'{"ok": true}'

        def fake_urlopen(request, timeout):
            captured["user_agent"] = request.get_header("User-agent")
            return FakeResponse()

        with patch("social_lens_bridge.http.urlopen", fake_urlopen):
            HttpJsonClient().request_json("POST", "https://api.grove.storage/link/new?amount=1")

        self.assertEqual(captured["user_agent"], "social-lens-bridge/0.1")

    def test_http_error_preserves_non_json_response_body(self) -> None:
        def fake_urlopen(request, timeout):
            raise HTTPError(
                request.full_url,
                403,
                "Forbidden",
                {},
                io.BytesIO(b"error code: 1010"),
            )

        with patch("social_lens_bridge.http.urlopen", fake_urlopen):
            with self.assertRaises(HttpJsonError) as raised:
                HttpJsonClient().request_json(
                    "POST",
                    "https://api.grove.storage/link/new?amount=1",
                )

        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(raised.exception.body, "error code: 1010")


if __name__ == "__main__":
    unittest.main()
