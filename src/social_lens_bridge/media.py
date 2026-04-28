from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

from .models import MediaItem


class UnsafeMediaError(ValueError):
    pass


@dataclass(frozen=True)
class MediaPolicy:
    max_items: int = 4
    max_bytes: int = 5_000_000
    allowed_mime_prefixes: tuple[str, ...] = ("image/", "video/", "audio/")
    require_https: bool = True


def validate_media_items(
    items: Iterable[MediaItem],
    policy: MediaPolicy,
) -> tuple[MediaItem, ...]:
    safe: list[MediaItem] = []
    for item in list(items)[: policy.max_items]:
        parsed = urlparse(item.url)
        if policy.require_https and parsed.scheme != "https":
            raise UnsafeMediaError(f"media URL must be https: {item.url}")
        if item.size_bytes is not None and item.size_bytes > policy.max_bytes:
            raise UnsafeMediaError(f"media item is larger than {policy.max_bytes} bytes")
        if item.mime_type and not item.mime_type.startswith(policy.allowed_mime_prefixes):
            raise UnsafeMediaError(f"media MIME type is not allowed: {item.mime_type}")
        safe.append(item)
    return tuple(safe)
