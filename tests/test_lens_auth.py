import base64
import json
import tempfile
import unittest
from pathlib import Path

from social_lens_bridge.auth import AuthError, TokenSession
from social_lens_bridge.config import BridgeConfig
from social_lens_bridge.lens_auth import LensSessionManager, lens_auth_warning
from social_lens_bridge.state import BridgeState


class FakeOrbClient:
    def __init__(self, session: TokenSession) -> None:
        self.session = session
        self.refresh_calls: list[str] = []

    def refresh(self, refresh_token: str) -> TokenSession:
        self.refresh_calls.append(refresh_token)
        return self.session


def unsigned_jwt(payload: dict) -> str:
    def enc(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}."


def make_config(**overrides: object) -> BridgeConfig:
    values = {
        "orb_auth_base_url": "https://new.orb.club/api",
        "orb_auth_origin": "https://social-lens-bridge.local",
        "state_db": "/tmp/bridge.sqlite3",
        "lens_api_url": "https://api.lens.xyz/graphql",
        "lens_account": None,
        "lens_access_token": None,
        "lens_refresh_token": None,
        "lens_id_token": None,
        "bluesky_did": None,
        "bluesky_handle": None,
        "bluesky_app_password": None,
        "bluesky_service_url": "https://bsky.social",
        "bluesky_jetstream_url": "wss://jetstream.example/subscribe",
        "bluesky_jetstream_read_timeout_seconds": 15.0,
        "nostr_public_key": None,
        "nostr_nsec": None,
        "nostr_private_key_hex": None,
        "nostr_relays": ("wss://relay.example",),
        "nostr_relay_read_timeout_seconds": 15.0,
        "poll_interval_seconds": 30,
        "max_media_items": 4,
        "max_media_bytes": 5000000,
    }
    values.update(overrides)
    return BridgeConfig(**values)


class LensAuthTests(unittest.TestCase):
    def test_refresh_only_env_token_bootstraps_access_and_saves_state(self) -> None:
        refreshed = TokenSession(
            access_token=unsigned_jwt({"act": {"sub": "0xabc"}, "exp": 9999999999}),
            refresh_token="refresh-2",
            id_token="id-2",
            account="0xabc",
        )
        fake = FakeOrbClient(refreshed)
        with tempfile.TemporaryDirectory() as tmp:
            state = BridgeState(Path(tmp) / "bridge.sqlite3")
            manager = LensSessionManager(
                make_config(lens_refresh_token="refresh-1"),
                state,
                orb_client_factory=lambda: fake,
            )

            session = manager.load()
            session_again = manager.load()

            self.assertEqual(session.access_token, refreshed.access_token)
            self.assertEqual(session_again.access_token, refreshed.access_token)
            self.assertEqual(fake.refresh_calls, ["refresh-1"])
            self.assertEqual(state.load_token("lens").refresh_token, "refresh-2")

    def test_expired_state_access_token_refreshes_when_refresh_token_exists(self) -> None:
        refreshed = TokenSession(
            access_token=unsigned_jwt({"act": {"sub": "0xabc"}, "exp": 9999999999}),
            refresh_token="refresh-2",
            account="0xabc",
        )
        fake = FakeOrbClient(refreshed)
        with tempfile.TemporaryDirectory() as tmp:
            state = BridgeState(Path(tmp) / "bridge.sqlite3")
            state.save_token(
                provider="lens",
                access_token=unsigned_jwt({"act": {"sub": "0xabc"}, "exp": 10}),
                refresh_token="refresh-1",
            )
            manager = LensSessionManager(make_config(), state, orb_client_factory=lambda: fake)

            session = manager.load()

            self.assertEqual(session.access_token, refreshed.access_token)
            self.assertEqual(fake.refresh_calls, ["refresh-1"])

    def test_expired_access_without_refresh_token_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = BridgeState(Path(tmp) / "bridge.sqlite3")
            manager = LensSessionManager(
                make_config(
                    lens_access_token=unsigned_jwt({"act": {"sub": "0xabc"}, "exp": 10}),
                ),
                state,
                orb_client_factory=lambda: FakeOrbClient(TokenSession(access_token="unused")),
            )

            with self.assertRaisesRegex(AuthError, "LENS_REFRESH_TOKEN"):
                manager.load()

    def test_access_only_env_token_warns_about_short_lifetime(self) -> None:
        warning = lens_auth_warning(
            make_config(
                lens_access_token=unsigned_jwt({"act": {"sub": "0xabc"}, "exp": 9999999999}),
            )
        )

        self.assertIn("about 10 minutes", warning or "")


if __name__ == "__main__":
    unittest.main()
