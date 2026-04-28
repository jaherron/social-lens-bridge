from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from ..models import PreparedPost, SourcePost

BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
StatusLogger = Callable[[str], None]
BRIDGE_ROUTE_TAGS = {
    "nostr-to-lens",
    "lens-to-nostr",
    "bluesky-to-lens",
    "lens-to-bluesky",
}


class NostrKeyError(ValueError):
    pass


def secret_bytes_from_nsec_or_hex(value: str) -> bytes:
    stripped = value.strip()
    if stripped.startswith("nsec1"):
        hrp, data = _bech32_decode(stripped)
        if hrp != "nsec":
            raise NostrKeyError(f"expected nsec key, got {hrp}")
        decoded = bytes(_convert_bits(data, 5, 8, False))
    else:
        hex_value = stripped.removeprefix("0x")
        decoded = bytes.fromhex(hex_value)
    if len(decoded) != 32:
        raise NostrKeyError("Nostr private key must be 32 bytes")
    return decoded


def public_key_from_nsec_or_hex(value: str) -> str:
    secret = secret_bytes_from_nsec_or_hex(value)
    try:
        from coincurve import PrivateKey
    except ImportError as exc:
        raise RuntimeError("Install coincurve to derive Nostr public keys") from exc

    return PrivateKey(secret).public_key.format(compressed=True)[1:].hex()


def normalize_public_key(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("npub1"):
        hrp, data = _bech32_decode(stripped)
        if hrp != "npub":
            raise NostrKeyError(f"expected npub key, got {hrp}")
        decoded = bytes(_convert_bits(data, 5, 8, False))
        if len(decoded) != 32:
            raise NostrKeyError("Nostr public key must be 32 bytes")
        return decoded.hex()

    hex_value = stripped.removeprefix("0x").lower()
    if not _is_hex_32(hex_value):
        raise NostrKeyError("Nostr public key must be npub or 64-char hex")
    return hex_value


def source_post_from_nostr_event(
    event: dict[str, Any],
    *,
    expected_pubkey: str | None,
) -> SourcePost | None:
    event_id = event.get("id")
    pubkey = event.get("pubkey")
    kind = event.get("kind")
    if not isinstance(event_id, str) or not _is_hex_32(event_id):
        return None
    if not isinstance(pubkey, str) or not _is_hex_32(pubkey):
        return None
    if expected_pubkey and pubkey.lower() != expected_pubkey.lower():
        return None
    if kind != 1:
        return None

    tags = event.get("tags") if isinstance(event.get("tags"), list) else []
    if _has_bridge_tag(tags):
        return None

    reply_id = _last_tag_value(tags, "e", marker="reply") or _last_tag_value(tags, "e")
    quote_id = _last_tag_value(tags, "q")
    external_links = tuple(
        tag[1]
        for tag in tags
        if isinstance(tag, list)
        and len(tag) >= 2
        and tag[0] == "r"
        and isinstance(tag[1], str)
        and tag[1].startswith("https://")
    )
    created_at = event.get("created_at")

    return SourcePost(
        platform="nostr",
        uri=f"nostr:{event_id.lower()}",
        author_id=pubkey.lower(),
        created_at=str(created_at) if isinstance(created_at, int) else "",
        text=event.get("content") if isinstance(event.get("content"), str) else "",
        reply_to_uri=f"nostr:{reply_id.lower()}" if reply_id else None,
        quote_uri=f"nostr:{quote_id.lower()}" if quote_id else None,
        external_links=external_links,
    )


def build_unsigned_nostr_event(
    prepared: PreparedPost,
    *,
    pubkey: str,
    created_at: int | None = None,
) -> dict[str, Any]:
    tags: list[list[str]] = [
        ["bridge-route", f"{prepared.source.platform}-to-nostr"],
        ["bridge-source", prepared.source.uri],
    ]
    if prepared.reply_to_target_uri:
        event_id = _nostr_uri_id(prepared.reply_to_target_uri)
        if event_id:
            tags.append(["e", event_id, "", "reply"])
    if prepared.quote_target_uri:
        event_id = _nostr_uri_id(prepared.quote_target_uri)
        if event_id:
            tags.append(["q", event_id])
    return {
        "pubkey": pubkey.lower(),
        "created_at": int(created_at if created_at is not None else time.time()),
        "kind": 1,
        "tags": tags,
        "content": prepared.text,
    }


def finalize_event(unsigned: dict[str, Any], *, private_key: str) -> dict[str, Any]:
    secret = secret_bytes_from_nsec_or_hex(private_key)
    try:
        from coincurve import PrivateKey
    except ImportError as exc:
        raise RuntimeError("Install coincurve to sign Nostr events") from exc

    key = PrivateKey(secret)
    pubkey = key.public_key.format(compressed=True)[1:].hex()
    event = {**unsigned, "pubkey": pubkey}
    event_id = nostr_event_id(event)
    sig = key.sign_schnorr(bytes.fromhex(event_id), aux_randomness=b"\x00" * 32).hex()
    return {**event, "id": event_id, "sig": sig}


def nostr_event_id(event: dict[str, Any]) -> str:
    payload = [
        0,
        event["pubkey"],
        event["created_at"],
        event["kind"],
        event["tags"],
        event["content"],
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class NostrClient:
    def __init__(
        self,
        relays: tuple[str, ...],
        *,
        connect: Callable[..., Any] | None = None,
        status: StatusLogger | None = None,
        read_timeout_seconds: float = 15.0,
    ) -> None:
        self.relays = relays
        self._connect = connect
        self._status = status
        self.read_timeout_seconds = read_timeout_seconds

    async def read_one_text_note(self, *, pubkey: str | None, since: int | None = None) -> dict[str, Any]:
        events = await self.read_text_notes(
            pubkey=pubkey,
            since=since,
            limit=1,
            raise_on_empty=True,
        )
        return events[0]

    async def read_text_notes(
        self,
        *,
        pubkey: str | None,
        since: int | None = None,
        until: int | None = None,
        limit: int = 1,
        raise_on_empty: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install websockets to consume Nostr relays") from exc
        if not self.relays:
            raise RuntimeError("At least one Nostr relay is required")
        connect = self._connect or websockets.connect

        filters: dict[str, Any] = {"kinds": [1], "limit": max(1, limit)}
        if pubkey:
            filters["authors"] = [normalize_public_key(pubkey)]
        if since:
            filters["since"] = since
        if until:
            filters["until"] = until
        errors: list[str] = []
        events: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for relay in self.relays:
            try:
                self._log(f"Connecting to Nostr relay {relay}")
                async with connect(relay, ping_interval=20) as websocket:
                    self._log(f"Connected to Nostr relay {relay}")
                    await websocket.send(json.dumps(["REQ", "orb-bridge", filters]))
                    self._log(
                        f"Waiting up to {self.read_timeout_seconds:g}s for Nostr event from {relay}"
                    )
                    while True:
                        try:
                            raw = await asyncio.wait_for(
                                websocket.recv(),
                                timeout=self.read_timeout_seconds,
                            )
                        except TimeoutError as exc:
                            message = (
                                f"{relay}: timed out after "
                                f"{self.read_timeout_seconds:g}s waiting for a matching event"
                            )
                            errors.append(message)
                            self._log(f"No matching Nostr event from {relay} before timeout")
                            raise _RelayReadFailed(message) from exc
                        data = json.loads(raw)
                        if isinstance(data, list) and len(data) >= 3 and data[0] == "EVENT":
                            event = data[2]
                            if isinstance(event, dict):
                                event_id = event.get("id")
                                if isinstance(event_id, str) and event_id in seen_ids:
                                    continue
                                if isinstance(event_id, str):
                                    seen_ids.add(event_id)
                                events.append(event)
                                suffix = f" {str(event_id)[:12]}" if isinstance(event_id, str) else ""
                                self._log(f"Received Nostr event{suffix} from {relay}")
                                if len(events) >= limit:
                                    return tuple(events)
                        if isinstance(data, list) and len(data) >= 2 and data[0] == "EOSE":
                            message = f"{relay}: no matching event before EOSE"
                            errors.append(message)
                            self._log(f"Relay {relay} returned no matching event")
                            break
                        if isinstance(data, list) and len(data) >= 2 and data[0] == "NOTICE":
                            self._log(f"Relay {relay} notice: {data[1]}")
                            if isinstance(data[1], str) and data[1].upper().startswith("ERROR"):
                                message = f"{relay}: {data[1]}"
                                errors.append(message)
                                raise _RelayReadFailed(message)
            except _RelayReadFailed:
                continue
            except Exception as exc:
                errors.append(f"{relay}: {exc}")
                self._log(f"Relay {relay} failed: {exc}")
        if events:
            return tuple(events)
        if raise_on_empty:
            raise RuntimeError("Could not read from Nostr relays: " + "; ".join(errors))
        return ()

    async def stream_text_notes(
        self,
        *,
        pubkey: str | None,
        since: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install websockets to consume Nostr relays") from exc
        if not self.relays:
            raise RuntimeError("At least one Nostr relay is required")
        connect = self._connect or websockets.connect

        filters: dict[str, Any] = {"kinds": [1]}
        if pubkey:
            filters["authors"] = [normalize_public_key(pubkey)]
        if since:
            filters["since"] = since

        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        reconnect_delay = max(1.0, min(self.read_timeout_seconds, 15.0))

        async def pump_relay(relay: str) -> None:
            while True:
                try:
                    self._log(f"Connecting to Nostr relay {relay}")
                    async with connect(relay, ping_interval=20) as websocket:
                        self._log(f"Connected to Nostr relay {relay}")
                        await websocket.send(json.dumps(["REQ", "orb-bridge-live", filters]))
                        self._log(
                            f"Listening for live Nostr events from {relay}; press Ctrl-C to stop"
                        )
                        while True:
                            raw = await websocket.recv()
                            data = json.loads(raw)
                            if isinstance(data, list) and len(data) >= 3 and data[0] == "EVENT":
                                event = data[2]
                                if not isinstance(event, dict):
                                    continue
                                await queue.put((relay, event))
                            if isinstance(data, list) and len(data) >= 2 and data[0] == "EOSE":
                                self._log(
                                    f"Relay {relay} sent EOSE; keeping live subscription open"
                                )
                            if isinstance(data, list) and len(data) >= 2 and data[0] == "NOTICE":
                                self._log(f"Relay {relay} notice: {data[1]}")
                                if (
                                    isinstance(data[1], str)
                                    and data[1].upper().startswith("ERROR")
                                ):
                                    raise _RelayReadFailed(f"{relay}: {data[1]}")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._log(
                        f"Relay {relay} live stream failed: {exc}; "
                        f"reconnecting in {reconnect_delay:g}s"
                    )
                    await asyncio.sleep(reconnect_delay)

        tasks = [asyncio.create_task(pump_relay(relay)) for relay in self.relays]
        seen_ids: set[str] = set()
        try:
            while True:
                relay, event = await queue.get()
                event_id = event.get("id")
                if isinstance(event_id, str) and event_id in seen_ids:
                    continue
                if isinstance(event_id, str):
                    seen_ids.add(event_id)
                suffix = f" {str(event_id)[:12]}" if isinstance(event_id, str) else ""
                self._log(f"Received Nostr event{suffix} from {relay}")
                yield event
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def publish(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install websockets to publish Nostr events") from exc
        responses: list[dict[str, Any]] = []
        for relay in self.relays:
            self._log(f"Publishing Nostr event to {relay}")
            async with websockets.connect(relay, ping_interval=20) as websocket:
                await websocket.send(json.dumps(["EVENT", event]))
                raw = await websocket.recv()
                responses.append({"relay": relay, "response": json.loads(raw)})
                self._log(f"Received publish response from {relay}")
        return responses

    def _log(self, message: str) -> None:
        if self._status:
            self._status(message)


class _RelayReadFailed(RuntimeError):
    pass


def _bech32_decode(value: str) -> tuple[str, list[int]]:
    if any(ord(x) < 33 or ord(x) > 126 for x in value):
        raise NostrKeyError("invalid bech32 characters")
    value = value.lower()
    pos = value.rfind("1")
    if pos < 1 or pos + 7 > len(value):
        raise NostrKeyError("invalid bech32 separator")
    hrp = value[:pos]
    data = [BECH32_CHARSET.find(x) for x in value[pos + 1 :]]
    if any(x == -1 for x in data):
        raise NostrKeyError("invalid bech32 data")
    if not _bech32_verify_checksum(hrp, data):
        raise NostrKeyError("invalid bech32 checksum")
    return hrp, data[:-6]


def _bech32_verify_checksum(hrp: str, data: list[int]) -> bool:
    return _bech32_polymod(_bech32_hrp_expand(hrp) + data) == 1


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
        if value < 0 or value >> from_bits:
            raise NostrKeyError("invalid bech32 bit group")
        acc = ((acc << from_bits) | value) & max_acc
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (to_bits - bits)) & maxv)
    elif bits >= from_bits or ((acc << (to_bits - bits)) & maxv):
        raise NostrKeyError("invalid bech32 padding")
    return ret


def _last_tag_value(tags: list[Any], tag_name: str, marker: str | None = None) -> str | None:
    value = None
    for tag in tags:
        if not isinstance(tag, list) or len(tag) < 2 or tag[0] != tag_name:
            continue
        if marker and (len(tag) < 4 or tag[3] != marker):
            continue
        if isinstance(tag[1], str) and _is_hex_32(tag[1]):
            value = tag[1]
    return value


def _has_bridge_tag(tags: list[Any]) -> bool:
    for tag in tags:
        if not isinstance(tag, list) or len(tag) < 2:
            continue
        if tag[0] == "bridge-route" and tag[1] in BRIDGE_ROUTE_TAGS:
            return True
        if tag[0] in {"bridge", "bridge-source"}:
            return True
        if tag[0] == "client" and tag[1] in {
            "orb-nostr-lens-bridge",
            "orb-social-lens-bridge",
        }:
            return True
    return False


def _nostr_uri_id(uri: str) -> str | None:
    value = uri.removeprefix("nostr:")
    return value.lower() if _is_hex_32(value) else None


def _is_hex_32(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
