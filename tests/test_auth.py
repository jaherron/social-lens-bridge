import base64
import json
import unittest

from social_lens_bridge.auth import (
    AuthError,
    UserIdMismatch,
    access_token_needs_refresh,
    decode_jwt_payload,
    session_from_env_tokens,
    session_from_poll_response,
)


def unsigned_jwt(payload: dict) -> str:
    def enc(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}."


class AuthTests(unittest.TestCase):
    def test_poll_response_verifies_user_id_against_access_token_actor(self) -> None:
        token = unsigned_jwt({"act": {"sub": "0xabc"}})
        session = session_from_poll_response(
            {
                "status": "SUCCESS",
                "data": {
                    "processed": True,
                    "accessToken": token,
                    "refreshToken": "refresh",
                    "idToken": "id",
                    "user_id": "0xabc",
                    "handle": "orb",
                    "source": "orb",
                },
            }
        )

        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.account, "0xabc")
        self.assertEqual(session.handle, "@orb")
        self.assertEqual(decode_jwt_payload(token)["act"]["sub"], "0xabc")

    def test_poll_response_rejects_user_id_mismatch(self) -> None:
        token = unsigned_jwt({"act": {"sub": "0xabc"}})

        with self.assertRaises(UserIdMismatch):
            session_from_poll_response(
                {
                    "status": "SUCCESS",
                    "data": {
                        "processed": True,
                        "accessToken": token,
                        "user_id": "0xdef",
                    },
                }
            )

    def test_poll_response_returns_none_until_processed(self) -> None:
        self.assertIsNone(session_from_poll_response({"status": "SUCCESS", "data": {}}))

    def test_env_tokens_reject_id_only(self) -> None:
        with self.assertRaisesRegex(AuthError, "LENS_ID_TOKEN alone"):
            session_from_env_tokens(
                access_token=None,
                refresh_token=None,
                id_token="id",
            )

    def test_env_tokens_allow_refresh_only(self) -> None:
        session = session_from_env_tokens(
            access_token=None,
            refresh_token="refresh",
            id_token="id",
        )

        self.assertIsNone(session.access_token)
        self.assertEqual(session.refresh_token, "refresh")
        self.assertEqual(session.id_token, "id")

    def test_access_token_expiry_is_read_from_jwt(self) -> None:
        expired = session_from_env_tokens(
            access_token=unsigned_jwt({"act": {"sub": "0xabc"}, "exp": 10}),
            refresh_token="refresh",
            id_token=None,
        )
        fresh = session_from_env_tokens(
            access_token=unsigned_jwt({"act": {"sub": "0xabc"}, "exp": 9999999999}),
            refresh_token=None,
            id_token=None,
        )

        self.assertTrue(access_token_needs_refresh(expired, now=100))
        self.assertFalse(access_token_needs_refresh(fresh, now=100))


if __name__ == "__main__":
    unittest.main()
