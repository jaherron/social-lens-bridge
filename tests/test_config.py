import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from social_lens_bridge.config import BridgeConfig


class ConfigTests(unittest.TestCase):
    def test_loads_conservative_defaults_and_env_overrides(self) -> None:
        env = {
            "ORB_AUTH_BASE_URL": "https://new.orb.club/api",
            "BRIDGE_STATE_DB": "/tmp/bridge.sqlite3",
            "NOSTR_PUBLIC_KEY": "a" * 64,
            "NOSTR_NSEC": "nsec1example",
            "NOSTR_RELAYS": "wss://relay.example,wss://relay2.example",
            "LENS_ACCESS_TOKEN": "access",
            "LENS_REFRESH_TOKEN": "refresh",
            "LENS_ID_TOKEN": "id",
            "BLUESKY_DID": "did:plc:example",
            "BLUESKY_HANDLE": "bridge.bsky.social",
            "BLUESKY_APP_PASSWORD": "app-password",
            "BLUESKY_SERVICE_URL": "https://bsky.social",
            "BLUESKY_JETSTREAM_URL": "wss://jetstream.example/subscribe",
            "BLUESKY_JETSTREAM_READ_TIMEOUT_SECONDS": "4.5",
            "NOSTR_RELAY_READ_TIMEOUT_SECONDS": "3.5",
        }
        with patch.dict(os.environ, env, clear=True):
            config = BridgeConfig.from_env()

        self.assertEqual(config.orb_auth_base_url, "https://new.orb.club/api")
        self.assertEqual(config.orb_auth_origin, "https://social-lens-bridge.local")
        self.assertNotIn("orb.club", config.orb_auth_origin)
        self.assertEqual(config.state_db, "/tmp/bridge.sqlite3")
        self.assertEqual(config.nostr_public_key, "a" * 64)
        self.assertEqual(config.nostr_nsec, env["NOSTR_NSEC"])
        self.assertEqual(config.nostr_relays, ("wss://relay.example", "wss://relay2.example"))
        self.assertEqual(config.lens_api_url, "https://api.lens.xyz/graphql")
        self.assertEqual(config.lens_access_token, "access")
        self.assertEqual(config.lens_refresh_token, "refresh")
        self.assertEqual(config.lens_id_token, "id")
        self.assertEqual(config.bluesky_did, "did:plc:example")
        self.assertEqual(config.bluesky_handle, "bridge.bsky.social")
        self.assertEqual(config.bluesky_app_password, "app-password")
        self.assertEqual(config.bluesky_service_url, "https://bsky.social")
        self.assertEqual(config.bluesky_jetstream_url, "wss://jetstream.example/subscribe")
        self.assertEqual(config.bluesky_jetstream_read_timeout_seconds, 4.5)
        self.assertEqual(config.nostr_relay_read_timeout_seconds, 3.5)
        self.assertEqual(config.poll_interval_seconds, 30)

    def test_env_example_contains_required_values_and_placeholders(self) -> None:
        example = Path(".env.example").read_text()

        self.assertIn("LENS_STORAGE_URL=https://api.grove.storage/", example)
        self.assertIn("LENS_STORAGE_KEY_URL=https://api.grove.storage/link/new?amount=1", example)
        self.assertIn("LENS_ACCOUNT=", example)
        self.assertIn("LENS_ID_TOKEN=", example)
        self.assertIn("LENS_ACCESS_TOKEN=", example)
        self.assertIn("LENS_REFRESH_TOKEN=", example)
        self.assertNotIn("LENS_ACCOUNT=0x0000000000000000000000000000000000000000", example)
        self.assertIn("NOSTR_PUBLIC_KEY=", example)
        self.assertIn("NOSTR_NSEC=nsec1...", example)
        self.assertIn("NOSTR_RELAYS=wss://relay.damus.io,wss://nos.lol", example)
        self.assertIn("NOSTR_RELAY_READ_TIMEOUT_SECONDS=15", example)
        self.assertIn("BLUESKY_DID=did:plc:examplebridgeaccount", example)
        self.assertIn("BLUESKY_HANDLE=your-handle.bsky.social", example)
        self.assertIn("BLUESKY_APP_PASSWORD=", example)
        self.assertIn("BLUESKY_JETSTREAM_URL=wss://jetstream2.us-east.bsky.network/subscribe", example)
        self.assertIn("BLUESKY_JETSTREAM_READ_TIMEOUT_SECONDS=15", example)

    def test_readme_documents_setup_flow(self) -> None:
        readme = Path("README.md").read_text()

        self.assertIn("## Setup Walkthrough", readme)
        self.assertIn("Add the Nostr key and relays", readme)
        self.assertIn("Add the Bluesky account", readme)
        self.assertIn("may be `npub` or 64-char hex", readme)
        self.assertIn("the bridge derives the public", readme)
        self.assertIn("Run Orb QR sign-in", readme)
        self.assertIn("derives the Lens account", readme)
        self.assertIn("`LENS_ID_TOKEN` alone", readme)
        self.assertIn("about 10 minutes", readme)
        self.assertIn("bridge auth orb-qr", readme)
        self.assertIn("keeps listening until you stop it with Ctrl-C", readme)
        self.assertIn("Nostr live mode keeps the relay subscription open after `EOSE`", readme)
        self.assertIn("Visible markers like `Mirrored from Nostr:`", readme)

    def test_agents_documents_operational_contract(self) -> None:
        agents = Path("AGENTS.md").read_text()

        self.assertIn("bridge once --direction <inbound> --mode live", agents)
        self.assertIn("streams until Ctrl-C", agents)
        self.assertIn("stay open after `EOSE`", agents)
        self.assertIn("Never put bridge provenance in visible content", agents)
        self.assertIn("Do not prefix new route tags with `orb`", agents)
        self.assertIn("BlueNostr is GPL-3.0", agents)

    def test_python_requires_supports_local_python_311(self) -> None:
        pyproject = Path("pyproject.toml").read_text()

        self.assertRegex(pyproject, re.compile(r'requires-python = ">=3\.11"'))
        self.assertIn('target-version = "py311"', pyproject)
        self.assertIn('license = { file = "LICENSE" }', pyproject)

    def test_license_file_is_mit(self) -> None:
        license_text = Path("LICENSE").read_text()

        self.assertIn("MIT License", license_text)
        self.assertIn("social-lens-bridge contributors", license_text)


if __name__ == "__main__":
    unittest.main()
