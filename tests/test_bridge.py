import tempfile
import unittest
from pathlib import Path

from social_lens_bridge.bridge import BridgeService
from social_lens_bridge.daemon import _lens_target_uri
from social_lens_bridge.models import SourcePost
from social_lens_bridge.state import BridgeState


class BridgeTests(unittest.TestCase):
    def test_skips_existing_sources_and_visible_bridge_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = BridgeState(Path(tmp) / "bridge.sqlite3")
            service = BridgeService(state)
            post = SourcePost(
                platform="nostr",
                uri=f"nostr:{'a' * 64}",
                author_id="b" * 64,
                created_at="2026-04-27T10:00:00Z",
                text="hello",
            )
            self.assertFalse(service.should_skip(post, target_platform="lens"))

            state.record_mirror(
                direction="nostr-to-lens",
                source_platform="nostr",
                source_uri=post.uri,
                target_platform="lens",
                target_uri="lens://post/1",
                target_id="1",
                content_hash="hash",
            )

            self.assertTrue(service.should_skip(post, target_platform="lens"))
            marker_post = SourcePost(
                platform="lens",
                uri="lens://post/2",
                author_id="0xabc",
                created_at="2026-04-27T10:00:00Z",
                text=f"Mirrored from Nostr: nostr:{'c' * 64}",
            )
            # Legacy content markers are still skipped, but new mirrored posts do not render them.
            self.assertTrue(service.should_skip(marker_post, target_platform="nostr"))

    def test_uses_mapped_parent_when_preparing_replies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = BridgeState(Path(tmp) / "bridge.sqlite3")
            state.record_mirror(
                direction="nostr-to-lens",
                source_platform="nostr",
                source_uri=f"nostr:{'1' * 64}",
                target_platform="lens",
                target_uri="lens://post/root",
                target_id="root",
                content_hash="hash",
            )
            service = BridgeService(state)
            post = SourcePost(
                platform="nostr",
                uri=f"nostr:{'2' * 64}",
                author_id="b" * 64,
                created_at="2026-04-27T10:00:00Z",
                text="reply",
                reply_to_uri=f"nostr:{'1' * 64}",
            )

            prepared = service.prepare(post, target_platform="lens")

            self.assertEqual(prepared.reply_to_target_uri, "lens://post/root")
            self.assertEqual(prepared.text, "reply")

    def test_does_not_use_lens_tx_url_as_reply_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = BridgeState(Path(tmp) / "bridge.sqlite3")
            state.record_mirror(
                direction="nostr-to-lens",
                source_platform="nostr",
                source_uri=f"nostr:{'1' * 64}",
                target_platform="lens",
                target_uri="https://explorer.lens.xyz/tx/0xabc",
                target_id="0xabc",
                content_hash="hash",
            )
            service = BridgeService(state)
            post = SourcePost(
                platform="nostr",
                uri=f"nostr:{'2' * 64}",
                author_id="b" * 64,
                created_at="2026-04-27T10:00:00Z",
                text="reply",
                reply_to_uri=f"nostr:{'1' * 64}",
            )

            prepared = service.prepare(post, target_platform="lens")

            self.assertIsNone(prepared.reply_to_target_uri)

    def test_lens_target_uri_uses_explorer_transaction_url(self) -> None:
        self.assertEqual(
            _lens_target_uri({"data": {"post": {"hash": "0xabc"}}}),
            "https://explorer.lens.xyz/tx/0xabc",
        )


if __name__ == "__main__":
    unittest.main()
