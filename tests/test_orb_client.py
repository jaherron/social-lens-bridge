import base64
import json
import unittest

from social_lens_bridge.clients.orb import OrbQrClient


def unsigned_jwt(payload: dict) -> str:
    def enc(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}."


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request_json(self, method, url, *, body=None, headers=None):
        self.calls.append((method, url, body, headers))
        return self.responses.pop(0)


class OrbClientTests(unittest.TestCase):
    def test_init_poll_and_refresh_use_orb_proxy_contract(self) -> None:
        token = unsigned_jwt({"act": {"sub": "0xabc"}})
        refreshed_token = unsigned_jwt({"act": {"sub": "0xdef"}, "exp": 9999999999})
        http = FakeHttp(
            [
                {"data": {"status": "SUCCESS", "data": {"qrCode": "qr", "secret": "s"}}},
                {
                    "data": {
                        "status": "SUCCESS",
                        "data": {
                            "processed": True,
                            "accessToken": token,
                            "refreshToken": "refresh",
                            "user_id": "0xabc",
                            "handle": "orb",
                        },
                    }
                },
                {
                    "accessToken": refreshed_token,
                    "refreshToken": "new-refresh",
                    "idToken": "new-id",
                },
            ]
        )
        client = OrbQrClient(
            "https://new.orb.club/api",
            origin="https://social-lens-bridge.local",
            http=http,
        )

        init = client.init_login()
        session = client.poll_login(init.secret)
        refreshed = client.refresh("refresh")

        self.assertEqual(init.qr_code, "qr")
        self.assertEqual(session.account, "0xabc")
        self.assertEqual(refreshed.access_token, refreshed_token)
        self.assertEqual(refreshed.account, "0xdef")
        self.assertEqual(refreshed.refresh_token, "new-refresh")
        self.assertEqual(http.calls[0][1], "https://new.orb.club/api/qr/init")
        self.assertEqual(
            http.calls[0][3],
            {
                "origin": "https://social-lens-bridge.local",
                "referer": "https://social-lens-bridge.local",
            },
        )
        self.assertEqual(http.calls[1][2], {"secret": "s"})
        self.assertEqual(
            http.calls[1][3],
            {
                "origin": "https://social-lens-bridge.local",
                "referer": "https://social-lens-bridge.local",
            },
        )
        self.assertEqual(http.calls[2][2], {"refreshToken": "refresh"})
        self.assertEqual(
            http.calls[2][3],
            {
                "origin": "https://social-lens-bridge.local",
                "referer": "https://social-lens-bridge.local",
            },
        )


if __name__ == "__main__":
    unittest.main()
