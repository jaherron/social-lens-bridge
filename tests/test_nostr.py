import asyncio
import tempfile
import unittest
from pathlib import Path

from social_lens_bridge.clients.nostr import (
    NostrClient,
    build_unsigned_nostr_event,
    normalize_public_key,
    public_key_from_nsec_or_hex,
    secret_bytes_from_nsec_or_hex,
    source_post_from_nostr_event,
)
from social_lens_bridge.config import BridgeConfig
from social_lens_bridge.daemon import BridgeDaemon
from social_lens_bridge.models import PreparedPost, SourcePost
from social_lens_bridge.state import BridgeState


BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_encode(hrp: str, payload: bytes) -> str:
    data = _convert_bits(list(payload), 8, 5, True)
    combined = data + _bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join(BECH32_CHARSET[value] for value in combined)


def _bech32_create_checksum(hrp: str, data: list[int]) -> list[int]:
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_polymod(values: list[int]) -> int:
    generators = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            if (top >> i) & 1:
                chk ^= generators[i]
    return chk


def _convert_bits(data: list[int], from_bits: int, to_bits: int, pad: bool) -> list[int]:
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << to_bits) - 1
    max_acc = (1 << (from_bits + to_bits - 1)) - 1
    for value in data:
        acc = ((acc << from_bits) | value) & max_acc
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (to_bits - bits)) & maxv)
    return ret


DUMMY_SECRET = bytes([1]) * 32
DUMMY_PUBKEY = "1b84c5567b126440995d3ed5aaba0565d71e1834604819ff9c17f5e9d5dd078f"
DUMMY_NSEC = _bech32_encode("nsec", DUMMY_SECRET)
DUMMY_NPUB = _bech32_encode("npub", bytes.fromhex(DUMMY_PUBKEY))


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


class NostrTests(unittest.TestCase):
    def test_decodes_nsec_key(self) -> None:
        secret = secret_bytes_from_nsec_or_hex(DUMMY_NSEC)

        self.assertEqual(secret, DUMMY_SECRET)

    def test_derives_public_key_from_nsec(self) -> None:
        pubkey = public_key_from_nsec_or_hex(DUMMY_NSEC)

        self.assertEqual(pubkey, DUMMY_PUBKEY)

    def test_normalizes_npub_public_key_to_hex(self) -> None:
        self.assertEqual(normalize_public_key(DUMMY_NPUB), DUMMY_PUBKEY)
        self.assertEqual(normalize_public_key(DUMMY_PUBKEY.upper()), DUMMY_PUBKEY)

    def test_daemon_normalizes_configured_npub_for_nostr_to_lens_reads(self) -> None:
        statuses: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            daemon = BridgeDaemon(
                make_config(nostr_public_key=DUMMY_NPUB),
                BridgeState(Path(tmp) / "bridge.sqlite3"),
                status=statuses.append,
            )

            self.assertEqual(daemon._nostr_public_key(), DUMMY_PUBKEY)
            self.assertTrue(
                any(f"Using configured Nostr public key {DUMMY_PUBKEY[:12]}" in s for s in statuses),
                statuses,
            )

    def test_daemon_uses_nsec_pubkey_for_nostr_to_lens_reads(self) -> None:
        statuses: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            daemon = BridgeDaemon(
                make_config(nostr_nsec=DUMMY_NSEC),
                BridgeState(Path(tmp) / "bridge.sqlite3"),
                status=statuses.append,
            )

            self.assertEqual(daemon._nostr_public_key(), DUMMY_PUBKEY)
            self.assertTrue(
                any("Derived Nostr public key" in status for status in statuses),
                statuses,
            )

    def test_read_one_text_note_tries_next_relay_after_connection_failure(self) -> None:
        calls: list[str] = []

        class FakeWebSocket:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def send(self, message: str) -> None:
                self.message = message

            async def recv(self) -> str:
                return (
                    '["EVENT","orb-bridge",'
                    '{"id":"%s","pubkey":"%s","created_at":1,"kind":1,"tags":[],"content":"hello"}]'
                    % ("a" * 64, "b" * 64)
                )

        def connect(relay: str, *, ping_interval: int):
            calls.append(relay)
            if relay == "wss://down.example":
                raise RuntimeError("HTTP 503")
            return FakeWebSocket()

        event = asyncio.run(
            NostrClient(
                ("wss://down.example", "wss://ok.example"),
                connect=connect,
            ).read_one_text_note(pubkey="b" * 64)
        )

        self.assertEqual(calls, ["wss://down.example", "wss://ok.example"])
        self.assertEqual(event["content"], "hello")

    def test_read_one_text_note_times_out_and_logs_status_for_silent_relay(self) -> None:
        statuses: list[str] = []

        class SilentWebSocket:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def send(self, message: str) -> None:
                self.message = message

            async def recv(self) -> str:
                await asyncio.sleep(1)
                return '["EOSE","orb-bridge"]'

        def connect(relay: str, *, ping_interval: int):
            return SilentWebSocket()

        with self.assertRaisesRegex(RuntimeError, "timed out"):
            asyncio.run(
                NostrClient(
                    ("wss://silent.example",),
                    connect=connect,
                    status=statuses.append,
                    read_timeout_seconds=0.001,
                ).read_one_text_note(pubkey="b" * 64)
            )

        self.assertTrue(any("Connecting to Nostr relay wss://silent.example" in s for s in statuses))
        self.assertTrue(any("No matching Nostr event" in s for s in statuses), statuses)

    def test_stream_text_notes_keeps_subscription_open_after_eose(self) -> None:
        statuses: list[str] = []

        class EoseThenEventWebSocket:
            def __init__(self) -> None:
                self.messages = [
                    '["EOSE","orb-bridge"]',
                    (
                        '["EVENT","orb-bridge",'
                        '{"id":"%s","pubkey":"%s","created_at":1,"kind":1,'
                        '"tags":[],"content":"live"}]'
                    )
                    % ("a" * 64, "b" * 64),
                ]

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def send(self, message: str) -> None:
                self.message = message

            async def recv(self) -> str:
                if self.messages:
                    return self.messages.pop(0)
                await asyncio.sleep(10)
                return '["EOSE","orb-bridge"]'

        def connect(relay: str, *, ping_interval: int):
            return EoseThenEventWebSocket()

        async def read_event() -> dict[str, object]:
            stream = NostrClient(
                ("wss://relay.example",),
                connect=connect,
                status=statuses.append,
                read_timeout_seconds=0.01,
            ).stream_text_notes(pubkey="b" * 64)
            try:
                return await asyncio.wait_for(anext(stream), timeout=0.1)
            finally:
                await stream.aclose()

        event = asyncio.run(read_event())

        self.assertEqual(event["content"], "live")
        self.assertTrue(any("sent EOSE" in status for status in statuses), statuses)

    def test_read_one_text_note_fails_fast_on_relay_error_notice(self) -> None:
        statuses: list[str] = []

        class ErrorNoticeWebSocket:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def send(self, message: str) -> None:
                self.message = message

            async def recv(self) -> str:
                return '["NOTICE","ERROR: bad req: uneven size input to from_hex"]'

        def connect(relay: str, *, ping_interval: int):
            return ErrorNoticeWebSocket()

        with self.assertRaisesRegex(RuntimeError, "bad req"):
            asyncio.run(
                NostrClient(
                    ("wss://relay.example",),
                    connect=connect,
                    status=statuses.append,
                    read_timeout_seconds=15,
                ).read_one_text_note(pubkey=DUMMY_NPUB)
            )

        self.assertTrue(any("notice: ERROR: bad req" in s for s in statuses), statuses)

    def test_revalidates_pubkey_before_normalizing_note(self) -> None:
        event = {
            "id": "a" * 64,
            "pubkey": "b" * 64,
            "created_at": 1_775_000_000,
            "kind": 1,
            "tags": [],
            "content": "hello",
        }

        self.assertIsNone(source_post_from_nostr_event(event, expected_pubkey="c" * 64))

    def test_normalizes_kind_1_note_tags(self) -> None:
        event = {
            "id": "a" * 64,
            "pubkey": "b" * 64,
            "created_at": 1_775_000_000,
            "kind": 1,
            "tags": [
                ["e", "1" * 64, "wss://relay.example", "root"],
                ["e", "2" * 64, "wss://relay.example", "reply"],
                ["q", "3" * 64],
                ["r", "https://example.com"],
            ],
            "content": "hello",
        }

        post = source_post_from_nostr_event(event, expected_pubkey="b" * 64)

        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post.uri, f"nostr:{'a' * 64}")
        self.assertEqual(post.reply_to_uri, f"nostr:{'2' * 64}")
        self.assertEqual(post.quote_uri, f"nostr:{'3' * 64}")
        self.assertEqual(post.external_links, ("https://example.com",))

    def test_build_unsigned_event_uses_tags_not_content_marker(self) -> None:
        source = SourcePost(
            platform="lens",
            uri="lens://post/1",
            author_id="0xabc",
            created_at="2026-04-27T10:00:00Z",
            text="hello from lens",
        )
        prepared = PreparedPost(
            source=source,
            target_platform="nostr",
            text="hello from lens",
            source_url="lens://post/1",
            reply_to_target_uri=f"nostr:{'1' * 64}",
            quote_target_uri=f"nostr:{'2' * 64}",
        )

        event = build_unsigned_nostr_event(
            prepared,
            pubkey="b" * 64,
            created_at=1_775_000_000,
        )

        self.assertEqual(event["content"], "hello from lens")
        self.assertNotIn("Mirrored from Lens:", event["content"])
        self.assertIn(["bridge-route", "lens-to-nostr"], event["tags"])
        self.assertFalse(any(tag[0] == "client" and "orb" in tag[1] for tag in event["tags"]))
        self.assertIn(["bridge-source", "lens://post/1"], event["tags"])
        self.assertIn(["e", "1" * 64, "", "reply"], event["tags"])
        self.assertIn(["q", "2" * 64], event["tags"])

    def test_skips_bridge_route_tagged_event(self) -> None:
        event = {
            "id": "a" * 64,
            "pubkey": "b" * 64,
            "created_at": 1_775_000_000,
            "kind": 1,
            "tags": [["bridge-route", "lens-to-nostr"]],
            "content": "hello",
        }

        self.assertIsNone(source_post_from_nostr_event(event, expected_pubkey="b" * 64))


if __name__ == "__main__":
    unittest.main()
