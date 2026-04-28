from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BridgeConfig:
    orb_auth_base_url: str
    orb_auth_origin: str
    state_db: str
    lens_api_url: str
    lens_account: str | None
    lens_access_token: str | None
    lens_refresh_token: str | None
    lens_id_token: str | None
    bluesky_did: str | None
    bluesky_handle: str | None
    bluesky_app_password: str | None
    bluesky_service_url: str
    bluesky_jetstream_url: str
    bluesky_jetstream_read_timeout_seconds: float
    nostr_public_key: str | None
    nostr_nsec: str | None
    nostr_private_key_hex: str | None
    nostr_relays: tuple[str, ...]
    nostr_relay_read_timeout_seconds: float
    poll_interval_seconds: int
    max_media_items: int
    max_media_bytes: int

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        default_state = Path.home() / ".local" / "state" / "social-lens-bridge" / "bridge.sqlite3"
        return cls(
            orb_auth_base_url=os.environ.get("ORB_AUTH_BASE_URL", "https://new.orb.club/api"),
            orb_auth_origin=os.environ.get(
                "ORB_AUTH_ORIGIN",
                "https://social-lens-bridge.local",
            ),
            state_db=os.environ.get("BRIDGE_STATE_DB", str(default_state)),
            lens_api_url=os.environ.get("LENS_API_URL", "https://api.lens.xyz/graphql"),
            lens_account=os.environ.get("LENS_ACCOUNT"),
            lens_access_token=os.environ.get("LENS_ACCESS_TOKEN"),
            lens_refresh_token=os.environ.get("LENS_REFRESH_TOKEN"),
            lens_id_token=os.environ.get("LENS_ID_TOKEN"),
            bluesky_did=os.environ.get("BLUESKY_DID"),
            bluesky_handle=os.environ.get("BLUESKY_HANDLE"),
            bluesky_app_password=os.environ.get("BLUESKY_APP_PASSWORD"),
            bluesky_service_url=os.environ.get("BLUESKY_SERVICE_URL", "https://bsky.social"),
            bluesky_jetstream_url=os.environ.get(
                "BLUESKY_JETSTREAM_URL",
                "wss://jetstream2.us-east.bsky.network/subscribe",
            ),
            bluesky_jetstream_read_timeout_seconds=float(
                os.environ.get("BLUESKY_JETSTREAM_READ_TIMEOUT_SECONDS", "15")
            ),
            nostr_public_key=os.environ.get("NOSTR_PUBLIC_KEY"),
            nostr_nsec=os.environ.get("NOSTR_NSEC"),
            nostr_private_key_hex=os.environ.get("NOSTR_PRIVATE_KEY_HEX"),
            nostr_relays=tuple(
                relay.strip()
                for relay in os.environ.get(
                    "NOSTR_RELAYS",
                    "wss://relay.damus.io,wss://nos.lol",
                ).split(",")
                if relay.strip()
            ),
            nostr_relay_read_timeout_seconds=float(
                os.environ.get("NOSTR_RELAY_READ_TIMEOUT_SECONDS", "15")
            ),
            poll_interval_seconds=int(os.environ.get("BRIDGE_POLL_INTERVAL_SECONDS", "30")),
            max_media_items=int(os.environ.get("BRIDGE_MAX_MEDIA_ITEMS", "4")),
            max_media_bytes=int(os.environ.get("BRIDGE_MAX_MEDIA_BYTES", "5000000")),
        )
