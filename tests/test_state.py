import os
import tempfile
import unittest
from pathlib import Path

from social_lens_bridge.state import BridgeState


class StateTests(unittest.TestCase):
    def test_state_db_is_owner_only_and_mirror_records_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bridge.sqlite3"
            state = BridgeState(path)

            for _ in range(2):
                state.record_mirror(
                    direction="nostr-to-lens",
                    source_platform="nostr",
                    source_uri=f"nostr:{'a' * 64}",
                    target_platform="lens",
                    target_uri="lens://post/1",
                    target_id="1",
                    content_hash="hash",
                )

            self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
            self.assertTrue(
                state.has_mirror(
                    source_platform="nostr",
                    source_uri=f"nostr:{'a' * 64}",
                    target_platform="lens",
                )
            )
            self.assertEqual(
                state.find_target_uri(
                    source_platform="nostr",
                    source_uri=f"nostr:{'a' * 64}",
                    target_platform="lens",
                ),
                "lens://post/1",
            )

    def test_cursors_and_tokens_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = BridgeState(Path(tmp) / "bridge.sqlite3")

            state.set_cursor("lens", "cursor-1")
            state.save_token(
                provider="lens",
                access_token="access",
                refresh_token="refresh",
                id_token="id",
                account="0xabc",
                handle="@orb",
                source="orb",
            )

            self.assertEqual(state.get_cursor("lens"), "cursor-1")
            self.assertEqual(state.load_token("lens").refresh_token, "refresh")


if __name__ == "__main__":
    unittest.main()
