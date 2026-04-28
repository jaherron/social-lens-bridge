from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .bridge import BridgeService
from .clients.bluesky import (
    BlueskyClient,
    build_bluesky_record,
    source_post_from_jetstream_event,
    source_posts_from_records_response,
)
from .clients.nostr import (
    NostrClient,
    build_unsigned_nostr_event,
    finalize_event,
    normalize_public_key,
    public_key_from_nsec_or_hex,
    source_post_from_nostr_event,
)
from .clients.lens import (
    LensClient,
    bridge_mirrors_from_lens_response,
    build_lens_metadata,
    source_posts_from_lens_response,
)
from .config import BridgeConfig
from .lens_auth import LensSessionManager
from .media import MediaPolicy
from .models import SourcePost
from .state import BridgeState
from .storage import GroveStorageClient

INBOUND_DIRECTIONS = {"nostr-to-lens", "bluesky-to-lens"}


@dataclass(frozen=True)
class BackfillOptions:
    limit: int | None = None
    since: int | None = None
    until_exhausted: bool = False


class BridgeDaemon:
    def __init__(
        self,
        config: BridgeConfig,
        state: BridgeState,
        *,
        status: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self.status = status
        self.service = BridgeService(
            state,
            media_policy=MediaPolicy(
                max_items=config.max_media_items,
                max_bytes=config.max_media_bytes,
            ),
        )
        self.lens_auth = LensSessionManager(config, state)

    def run_forever(self) -> None:
        asyncio.run(self._run_forever())

    async def _run_forever(self) -> None:
        live_tasks = [
            asyncio.create_task(self._run_nostr_to_lens_live_once()),
            asyncio.create_task(self._run_bluesky_to_lens_live_once()),
        ]
        try:
            while True:
                await asyncio.to_thread(self._run_lens_to_nostr_once)
                await asyncio.to_thread(self._run_lens_to_bluesky_once)
                for task in live_tasks:
                    if task.done():
                        task.result()
                await asyncio.sleep(self.config.poll_interval_seconds)
        except asyncio.CancelledError:
            self._log("Stopping bridge daemon")
        finally:
            for task in live_tasks:
                task.cancel()
            await asyncio.gather(*live_tasks, return_exceptions=True)

    def run_once(
        self,
        direction: str,
        *,
        mode: str | None = None,
        backfill_options: BackfillOptions | None = None,
    ) -> int:
        if mode not in {None, "live", "backfill"}:
            raise ValueError("mode must be live or backfill")
        if direction not in INBOUND_DIRECTIONS and mode is not None:
            raise ValueError("--mode is only supported for inbound directions")
        resolved_mode = mode or ("backfill" if direction in INBOUND_DIRECTIONS else None)
        self._log(f"Starting bridge cycle: {direction}")
        if direction == "lens-to-nostr":
            return self._run_lens_to_nostr_once()
        if direction == "nostr-to-lens":
            options = backfill_options or BackfillOptions(limit=1)
            if resolved_mode == "live":
                return asyncio.run(self._run_nostr_to_lens_live_once())
            return asyncio.run(self._run_nostr_to_lens_backfill_once(options))
        if direction == "lens-to-bluesky":
            return self._run_lens_to_bluesky_once()
        if direction == "bluesky-to-lens":
            options = backfill_options or BackfillOptions(limit=1)
            if resolved_mode == "live":
                return asyncio.run(self._run_bluesky_to_lens_live_once())
            return asyncio.run(self._run_bluesky_to_lens_backfill_once(options))
        raise ValueError(f"unknown direction: {direction}")

    def _run_lens_to_nostr_once(self) -> int:
        lens_session = self.lens_auth.load()
        nostr_private_key = self._nostr_private_key()
        account = self.config.lens_account or lens_session.account
        if not account:
            raise RuntimeError("Lens account is required; run `bridge auth orb-qr` first")

        lens = LensClient(self.config.lens_api_url)
        self._log(f"Reading Lens posts for {account}")
        response = lens.list_account_posts(
            lens_session,
            account=account,
            cursor=self.state.get_cursor("lens:nostr"),
        )
        posts, next_cursor = source_posts_from_lens_response(response)
        count = 0
        for post in posts:
            if self.service.should_skip(post, target_platform="nostr"):
                self._log(f"Skipping already mirrored or bridge-tagged Lens post {post.uri}")
                continue
            prepared = self.service.prepare(post, target_platform="nostr")
            unsigned = build_unsigned_nostr_event(
                prepared,
                pubkey=self.config.nostr_public_key or "0" * 64,
            )
            event = finalize_event(unsigned, private_key=nostr_private_key)
            asyncio.run(
                NostrClient(self.config.nostr_relays, status=self._log).publish(event)
            )
            self.service.record_publish(prepared, f"nostr:{event['id']}", event["id"])
            self._log(f"Published Nostr event {event['id'][:12]}")
            count += 1
        if next_cursor:
            self.state.set_cursor("lens:nostr", next_cursor)
        return count

    def _run_lens_to_bluesky_once(self) -> int:
        lens_session = self.lens_auth.load()
        bluesky_session = self._create_bluesky_session()
        account = self.config.lens_account or lens_session.account
        if not account:
            raise RuntimeError("Lens account is required; run `bridge auth orb-qr` first")

        lens = LensClient(self.config.lens_api_url)
        self._log(f"Reading Lens posts for {account}")
        response = lens.list_account_posts(
            lens_session,
            account=account,
            cursor=self.state.get_cursor("lens:bluesky"),
        )
        posts, next_cursor = source_posts_from_lens_response(response)
        bsky = BlueskyClient(self.config.bluesky_service_url)
        count = 0
        for post in posts:
            if self.service.should_skip(post, target_platform="bluesky"):
                self._log(f"Skipping already mirrored or bridge-tagged Lens post {post.uri}")
                continue
            prepared = self.service.prepare(post, target_platform="bluesky")
            record = build_bluesky_record(prepared)
            result = bsky.create_post(
                access_jwt=bluesky_session["accessJwt"],
                repo=bluesky_session["did"],
                record=record,
            )
            target_uri = result.get("uri")
            if isinstance(target_uri, str):
                self.service.record_publish(prepared, target_uri, result.get("cid"))
                self._log(f"Published Bluesky record {target_uri}")
                count += 1
        if next_cursor:
            self.state.set_cursor("lens:bluesky", next_cursor)
        return count

    async def _run_nostr_to_lens_live_once(self) -> int:
        public_key = self._nostr_public_key()
        since = _cursor_as_int(self.state.get_cursor("nostr:live"))
        if since is None:
            since = int(time.time())
            self.state.set_cursor("nostr:live", str(since))
        self._log(f"Reading live Nostr notes for pubkey {public_key[:12]}")
        count = 0
        try:
            async for event in self._stream_nostr_events(public_key=public_key, since=since):
                count += self._publish_nostr_events_to_lens((event,), public_key)
                created_at = _nostr_event_created_at(event)
                if created_at:
                    self.state.set_cursor("nostr:live", str(created_at + 1))
        except asyncio.CancelledError:
            self._log(f"Stopped live Nostr listener after mirroring {count} posts")
            return count
        return count

    async def _run_nostr_to_lens_backfill_once(self, options: BackfillOptions) -> int:
        public_key = self._nostr_public_key()
        self._hydrate_lens_bridge_mirrors()
        self._log(f"Backfilling Nostr notes for pubkey {public_key[:12]}")
        count = 0
        until: int | None = None
        seen_ids: set[str] = set()
        while True:
            remaining = _remaining_limit(options.limit, count)
            if remaining == 0:
                return count
            page_limit = min(remaining or 50, 50)
            events = await NostrClient(
                self.config.nostr_relays,
                status=self._log,
                read_timeout_seconds=self.config.nostr_relay_read_timeout_seconds,
            ).read_text_notes(
                pubkey=public_key,
                since=options.since,
                until=until,
                limit=page_limit,
            )
            events = tuple(event for event in events if str(event.get("id")) not in seen_ids)
            if not events:
                return count
            seen_ids.update(str(event.get("id")) for event in events)
            events = tuple(sorted(events, key=_nostr_event_created_at, reverse=True))
            count += self._publish_nostr_events_to_lens(events, public_key)
            oldest = _oldest_nostr_created_at(events)
            if oldest is None or _page_crossed_since(events, options.since):
                return count
            until = oldest - 1

    def _publish_nostr_events_to_lens(
        self,
        events: tuple[dict[str, Any], ...],
        public_key: str,
    ) -> int:
        count = 0
        for event in events:
            post = source_post_from_nostr_event(event, expected_pubkey=public_key)
            if self._publish_source_post_to_lens(post, label="Nostr note"):
                count += 1
        return count

    async def _run_bluesky_to_lens_live_once(self) -> int:
        did = self._bluesky_did()
        self._log(f"Reading live Bluesky events for DID {did}")
        count = 0
        try:
            async for event in self._stream_jetstream_events(did):
                post = source_post_from_jetstream_event(event, expected_did=did)
                if self._publish_source_post_to_lens(post, label="Bluesky post"):
                    count += 1
        except asyncio.CancelledError:
            self._log(f"Stopped live Bluesky listener after mirroring {count} posts")
            return count
        return count

    async def _run_bluesky_to_lens_backfill_once(self, options: BackfillOptions) -> int:
        did = self._bluesky_did()
        self._hydrate_lens_bridge_mirrors()
        self._log(f"Backfilling Bluesky records for DID {did}")
        client = BlueskyClient(self.config.bluesky_service_url)
        count = 0
        cursor: str | None = None
        while True:
            remaining = _remaining_limit(options.limit, count)
            if remaining == 0:
                return count
            page_limit = min(remaining or 100, 100)
            response = client.list_records(
                repo=did,
                collection="app.bsky.feed.post",
                cursor=cursor,
                limit=page_limit,
            )
            posts, next_cursor = source_posts_from_records_response(
                response,
                expected_did=did,
                collection="app.bsky.feed.post",
            )
            if not posts:
                if not next_cursor:
                    return count
                cursor = next_cursor
                continue
            for post in posts:
                if options.since is not None and not _post_is_after_since(post, options.since):
                    continue
                if self._publish_source_post_to_lens(post, label="Bluesky post"):
                    count += 1
                    if _remaining_limit(options.limit, count) == 0:
                        return count
            if _posts_crossed_since(posts, options.since) or not next_cursor:
                return count
            cursor = next_cursor

    def _publish_source_post_to_lens(self, post: SourcePost | None, *, label: str) -> bool:
        if post is None or self.service.should_skip(post, target_platform="lens"):
            self._log(f"No usable {label} found after validation")
            return False

        self._log(f"Preparing Lens metadata for {label} {post.uri}")
        self._log("Loading Lens session")
        lens_session = self.lens_auth.load()
        prepared = self.service.prepare(post, target_platform="lens")
        metadata = build_lens_metadata(
            post,
            text=prepared.text,
            handle=lens_session.handle,
        )
        storage = self._storage_client()
        self._log("Uploading Lens metadata to Grove")
        uploaded = storage.upload_json(metadata, lens_account=lens_session.account)
        content_uri = uploaded.get("uri")
        if not isinstance(content_uri, str):
            raise RuntimeError("storage upload did not return uri")
        self._log("Creating Lens post")
        result = LensClient(self.config.lens_api_url).create_post(
            lens_session,
            content_uri=content_uri,
            prepared=prepared,
        )
        target_uri = _lens_target_uri(result)
        if target_uri:
            self.service.record_publish(prepared, target_uri, target_uri)
            self._log(f"Published Lens target {target_uri}")
            return True
        self._log("Lens create post response did not include a target URI")
        return False

    def _hydrate_lens_bridge_mirrors(self) -> int:
        self._log("Loading Lens session")
        lens_session = self.lens_auth.load()
        account = self.config.lens_account or lens_session.account
        if not account:
            raise RuntimeError("Lens account is required; run `bridge auth orb-qr` first")
        lens = LensClient(self.config.lens_api_url)
        cursor: str | None = None
        count = 0
        while True:
            self._log(f"Scanning existing Lens bridge metadata for {account}")
            response = lens.list_account_posts(
                lens_session,
                account=account,
                cursor=cursor,
            )
            mirrors, next_cursor = bridge_mirrors_from_lens_response(response)
            for mirror in mirrors:
                if self.state.has_mirror(
                    source_platform=mirror.source_platform,
                    source_uri=mirror.source_uri,
                    target_platform=mirror.target_platform,
                ):
                    continue
                self.state.record_mirror(
                    direction=f"{mirror.source_platform}-to-{mirror.target_platform}",
                    source_platform=mirror.source_platform,
                    source_uri=mirror.source_uri,
                    target_platform=mirror.target_platform,
                    target_uri=mirror.target_uri,
                    target_id=mirror.target_id,
                    content_hash="hydrated",
                )
                count += 1
            if not next_cursor:
                if count:
                    self._log(f"Hydrated {count} existing Lens bridge mappings")
                return count
            cursor = next_cursor

    def _bluesky_did(self) -> str:
        actor = self.config.bluesky_handle
        if not actor and self.config.bluesky_did and self.config.bluesky_did.startswith("did:"):
            return self.config.bluesky_did
        actor = actor or self.config.bluesky_did
        if not actor:
            raise RuntimeError("BLUESKY_DID or BLUESKY_HANDLE is required for Bluesky to Lens")
        did = BlueskyClient(self.config.bluesky_service_url).resolve_handle(actor)
        self._log(f"Resolved Bluesky actor {actor} to {did}")
        return did

    def _create_bluesky_session(self) -> dict[str, Any]:
        if not self.config.bluesky_handle or not self.config.bluesky_app_password:
            raise RuntimeError("BLUESKY_HANDLE and BLUESKY_APP_PASSWORD are required")
        session = BlueskyClient(self.config.bluesky_service_url).create_session(
            identifier=self.config.bluesky_handle,
            password=self.config.bluesky_app_password,
        )
        if not isinstance(session.get("accessJwt"), str) or not isinstance(session.get("did"), str):
            raise RuntimeError("Bluesky session response did not include accessJwt and did")
        return session

    def _nostr_private_key(self) -> str:
        private_key = self.config.nostr_nsec or self.config.nostr_private_key_hex
        if not private_key:
            raise RuntimeError("NOSTR_NSEC or NOSTR_PRIVATE_KEY_HEX is required for Lens to Nostr")
        return private_key

    def _nostr_public_key(self) -> str:
        if self.config.nostr_public_key:
            public_key = normalize_public_key(self.config.nostr_public_key)
            self._log(f"Using configured Nostr public key {public_key[:12]}")
            return public_key
        private_key = self.config.nostr_nsec or self.config.nostr_private_key_hex
        if private_key:
            public_key = public_key_from_nsec_or_hex(private_key)
            self._log(f"Derived Nostr public key {public_key[:12]} from private key")
            return public_key
        raise RuntimeError("NOSTR_PUBLIC_KEY or NOSTR_NSEC is required for Nostr to Lens")

    def _storage_client(self) -> GroveStorageClient:
        storage_url = os.environ.get("LENS_STORAGE_URL")
        key_url = os.environ.get("LENS_STORAGE_KEY_URL")
        if not storage_url or not key_url:
            raise RuntimeError("LENS_STORAGE_URL and LENS_STORAGE_KEY_URL are required")
        return GroveStorageClient(
            storage_url=storage_url,
            key_url=key_url,
            chain_id=int(os.environ.get("LENS_CHAIN_ID", "232")),
            x_grove_client=os.environ.get("X_GROVE_CLIENT"),
        )

    async def _stream_nostr_events(self, *, public_key: str, since: int | None):
        async for event in NostrClient(
            self.config.nostr_relays,
            status=self._log,
            read_timeout_seconds=self.config.nostr_relay_read_timeout_seconds,
        ).stream_text_notes(pubkey=public_key, since=since):
            yield event

    async def _stream_jetstream_events(self, did: str):
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install websockets to consume Bluesky Jetstream") from exc

        endpoint = self.config.bluesky_jetstream_url
        timeout = self.config.bluesky_jetstream_read_timeout_seconds
        url = f"{endpoint}?wantedDids={did}"
        reconnect_delay = max(1.0, min(timeout, 15.0))
        while True:
            try:
                self._log(f"Connecting to Bluesky Jetstream {endpoint}")
                async with websockets.connect(url, ping_interval=20) as websocket:
                    self._log("Listening for live Bluesky events; press Ctrl-C to stop")
                    while True:
                        raw = await websocket.recv()
                        data = json.loads(raw)
                        if not isinstance(data, dict):
                            raise RuntimeError("Jetstream event was not a JSON object")
                        yield data
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log(
                    f"Bluesky Jetstream failed: {exc}; reconnecting in {reconnect_delay:g}s"
                )
                await asyncio.sleep(reconnect_delay)

    def _log(self, message: str) -> None:
        if self.status:
            self.status(message)


def _lens_target_uri(response: dict[str, Any]) -> str | None:
    post_result = response.get("data", {}).get("post")
    if not isinstance(post_result, dict):
        return None
    value = post_result.get("hash")
    return f"https://explorer.lens.xyz/tx/{value}" if isinstance(value, str) else None


def _remaining_limit(limit: int | None, count: int) -> int | None:
    if limit is None:
        return None
    return max(0, limit - count)


def _newest_nostr_created_at(events: tuple[dict[str, Any], ...]) -> int | None:
    values = [
        _nostr_event_created_at(event)
        for event in events
        if isinstance(event.get("created_at"), int)
    ]
    return max(values) if values else None


def _oldest_nostr_created_at(events: tuple[dict[str, Any], ...]) -> int | None:
    values = [
        _nostr_event_created_at(event)
        for event in events
        if isinstance(event.get("created_at"), int)
    ]
    return min(values) if values else None


def _nostr_event_created_at(event: dict[str, Any]) -> int:
    value = event.get("created_at")
    return int(value) if isinstance(value, int) else 0


def _page_crossed_since(events: tuple[dict[str, Any], ...], since: int | None) -> bool:
    if since is None:
        return False
    oldest = _oldest_nostr_created_at(events)
    return oldest is not None and oldest <= since


def _posts_crossed_since(posts: tuple[SourcePost, ...], since: int | None) -> bool:
    if since is None:
        return False
    timestamps = [_post_timestamp(post) for post in posts]
    timestamps = [value for value in timestamps if value is not None]
    return bool(timestamps) and min(timestamps) <= since


def _post_is_after_since(post: SourcePost, since: int) -> bool:
    timestamp = _post_timestamp(post)
    return timestamp is None or timestamp >= since


def _post_timestamp(post: SourcePost) -> int | None:
    value = post.created_at.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _cursor_as_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None
