from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Platform = Literal["nostr", "bluesky", "lens"]


@dataclass(frozen=True)
class MediaItem:
    url: str
    mime_type: str | None = None
    alt: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True)
class SourcePost:
    platform: Platform
    uri: str
    author_id: str
    created_at: str
    text: str = ""
    cid: str | None = None
    post_type: str = "post"
    reply_to_uri: str | None = None
    quote_uri: str | None = None
    repost_of_uri: str | None = None
    media: tuple[MediaItem, ...] = field(default_factory=tuple)
    external_links: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PreparedPost:
    source: SourcePost
    target_platform: Platform
    text: str
    source_url: str
    reply_to_target_uri: str | None = None
    quote_target_uri: str | None = None
    repost_target_uri: str | None = None
    media: tuple[MediaItem, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PublishResult:
    uri: str
    id: str | None = None
    raw: dict | None = None
