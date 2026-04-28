import unittest
import sys
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from social_lens_bridge.cli import (
    build_parser,
    main,
    normalize_orb_approve_link,
    render_qr_terminal,
    upsert_env_value,
)


class CliTests(unittest.TestCase):
    def test_parser_exposes_auth_run_and_once_commands(self) -> None:
        parser = build_parser()

        self.assertEqual(parser.parse_args(["auth", "orb-qr"]).command, "auth")
        self.assertEqual(parser.parse_args(["run"]).command, "run")
        args = parser.parse_args(["once", "--direction", "lens-to-nostr"])
        bluesky_args = parser.parse_args(["once", "--direction", "lens-to-bluesky"])
        inbound_args = parser.parse_args(
            ["once", "--direction", "bluesky-to-lens", "--mode", "live"]
        )
        backfill_args = parser.parse_args(
            ["backfill", "--direction", "bluesky-to-lens", "--limit", "50"]
        )

        self.assertEqual(args.command, "once")
        self.assertEqual(args.direction, "lens-to-nostr")
        self.assertEqual(bluesky_args.direction, "lens-to-bluesky")
        self.assertEqual(inbound_args.mode, "live")
        self.assertEqual(backfill_args.command, "backfill")
        self.assertEqual(backfill_args.direction, "bluesky-to-lens")
        self.assertEqual(backfill_args.limit, 50)

    def test_state_db_can_be_passed_after_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["once", "--direction", "lens-to-nostr", "--state-db", "/tmp/bridge.sqlite3"]
        )

        self.assertEqual(args.state_db, "/tmp/bridge.sqlite3")

    def test_state_db_can_be_passed_before_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["--state-db", "/tmp/bridge.sqlite3", "once", "--direction", "lens-to-nostr"]
        )

        self.assertEqual(args.state_db, "/tmp/bridge.sqlite3")

    def test_missing_auth_is_reported_without_traceback(self) -> None:
        with TemporaryDirectory() as tmp, patch("sys.stderr") as stderr:
            code = main(
                [
                    "--state-db",
                    str(Path(tmp) / "bridge.sqlite3"),
                    "once",
                    "--direction",
                    "lens-to-nostr",
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("no token stored", "".join(call.args[0] for call in stderr.write.call_args_list))

    def test_terminal_qr_renders_blocks_for_payload(self) -> None:
        class FakeQRCode:
            def __init__(self, border: int) -> None:
                self.border = border

            def add_data(self, payload: str) -> None:
                self.payload = payload

            def make(self, fit: bool) -> None:
                self.fit = fit

            def get_matrix(self) -> list[list[bool]]:
                return [
                    [True for _ in range(12)],
                    [True for _ in range(12)],
                    [True for _ in range(12)],
                    [False for _ in range(12)],
                    [False for _ in range(12)],
                    [True for _ in range(12)],
                    *[[False for _ in range(12)] for _ in range(6)],
                ]

        fake_qrcode = SimpleNamespace(QRCode=FakeQRCode)
        with patch.dict(sys.modules, {"qrcode": fake_qrcode}):
            rendered = render_qr_terminal("orb://sign-in?secret=test")

        self.assertIn("██", rendered)
        self.assertEqual(len(rendered.splitlines()), 6)
        self.assertIn("▀", rendered)
        self.assertIn("▄", rendered)

    def test_normalizes_deep_link_to_orb_approve(self) -> None:
        self.assertEqual(
            normalize_orb_approve_link("orb://sign-in?secret=abc&client=bridge"),
            "https://orb.club/approve?secret=abc&client=bridge",
        )
        self.assertEqual(
            normalize_orb_approve_link("https://new.orb.club/foo?secret=abc"),
            "https://orb.club/approve?secret=abc",
        )

    def test_upserts_refresh_token_in_env_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("LENS_ACCESS_TOKEN=access\nLENS_REFRESH_TOKEN=old\n", encoding="utf-8")

            upsert_env_value(path, "LENS_REFRESH_TOKEN", "new-refresh")

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "LENS_ACCESS_TOKEN=access\nLENS_REFRESH_TOKEN=new-refresh\n",
            )


if __name__ == "__main__":
    unittest.main()
