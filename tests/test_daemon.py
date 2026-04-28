import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any

from social_lens_bridge.config import BridgeConfig
from social_lens_bridge.daemon import BridgeDaemon
from social_lens_bridge.models import SourcePost
from social_lens_bridge.state import BridgeState


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
        "bluesky_did": "did:plc:source",
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


def bluesky_event(rkey: str, text: str) -> dict[str, Any]:
    return {
        "did": "did:plc:source",
        "commit": {
            "operation": "create",
            "collection": "app.bsky.feed.post",
            "rkey": rkey,
            "record": {"text": text, "createdAt": "2026-04-28T10:00:00Z"},
        },
    }


def nostr_event(event_id: str, text: str, *, created_at: int = 123) -> dict[str, Any]:
    return {
        "id": event_id,
        "pubkey": "b" * 64,
        "created_at": created_at,
        "kind": 1,
        "tags": [],
        "content": text,
    }


class BurstLiveDaemon(BridgeDaemon):
    def __init__(self, config: BridgeConfig, state: BridgeState) -> None:
        super().__init__(config, state)
        self.published: list[str] = []

    async def _read_jetstream_events(self, did: str) -> tuple[dict[str, Any], ...]:
        raise AssertionError("live mode should consume the Jetstream stream")

    async def _stream_jetstream_events(self, did: str):
        yield bluesky_event("one", "first")
        yield bluesky_event("two", "second")

    def _publish_source_post_to_lens(self, post: SourcePost | None, *, label: str) -> bool:
        if post is None:
            return False
        self.published.append(post.uri)
        return True


class CancelledBlueskyLiveDaemon(BurstLiveDaemon):
    async def _stream_jetstream_events(self, did: str):
        yield bluesky_event("one", "first")
        raise asyncio.CancelledError


class CancelledNostrLiveDaemon(BridgeDaemon):
    def __init__(self, config: BridgeConfig, state: BridgeState) -> None:
        super().__init__(config, state)
        self.published: list[str] = []

    async def _stream_nostr_events(self, *, public_key: str, since: int | None):
        yield nostr_event("a" * 64, "first")
        raise asyncio.CancelledError

    def _publish_nostr_events_to_lens(
        self,
        events: tuple[dict[str, Any], ...],
        public_key: str,
    ) -> int:
        self.published.extend(str(event["id"]) for event in events)
        return len(events)


class DaemonTests(unittest.TestCase):
    def test_bluesky_live_once_processes_a_burst_of_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon = BurstLiveDaemon(
                make_config(),
                BridgeState(Path(tmp) / "bridge.sqlite3"),
            )

            count = asyncio.run(daemon._run_bluesky_to_lens_live_once())

        self.assertEqual(count, 2)
        self.assertEqual(
            daemon.published,
            [
                "at://did:plc:source/app.bsky.feed.post/one",
                "at://did:plc:source/app.bsky.feed.post/two",
            ],
        )

    def test_bluesky_live_once_returns_count_on_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon = CancelledBlueskyLiveDaemon(
                make_config(),
                BridgeState(Path(tmp) / "bridge.sqlite3"),
            )

            count = asyncio.run(daemon._run_bluesky_to_lens_live_once())

        self.assertEqual(count, 1)
        self.assertEqual(
            daemon.published,
            ["at://did:plc:source/app.bsky.feed.post/one"],
        )

    def test_nostr_live_once_returns_count_on_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = BridgeState(Path(tmp) / "bridge.sqlite3")
            daemon = CancelledNostrLiveDaemon(
                make_config(nostr_public_key="b" * 64),
                state,
            )

            count = asyncio.run(daemon._run_nostr_to_lens_live_once())
            cursor = state.get_cursor("nostr:live")

        self.assertEqual(count, 1)
        self.assertEqual(daemon.published, ["a" * 64])
        self.assertEqual(cursor, "124")


if __name__ == "__main__":
    unittest.main()
