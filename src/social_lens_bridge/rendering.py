from __future__ import annotations

import hashlib

from .models import SourcePost

SOURCE_LABELS = {
    "nostr": "Nostr",
    "bluesky": "Bluesky",
    "lens": "Lens",
}

BRIDGE_MARKERS = (
    "Mirrored from Nostr:",
    "Mirrored from Bluesky:",
    "Mirrored from Lens:",
)


def has_bridge_marker(text: str) -> bool:
    return any(marker in text for marker in BRIDGE_MARKERS)


def source_url(post: SourcePost) -> str:
    if post.uri.startswith("http://") or post.uri.startswith("https://"):
        return post.uri
    if post.platform == "nostr" and post.uri.startswith("nostr:"):
        return post.uri
    if post.platform == "bluesky" and post.uri.startswith("at://"):
        parts = post.uri.removeprefix("at://").split("/")
        if len(parts) >= 3 and parts[1] == "app.bsky.feed.post":
            return f"https://bsky.app/profile/{parts[0]}/post/{parts[2]}"
    return post.uri


def render_mirrored_text(
    post: SourcePost,
    target_platform: str,
    max_chars: int | None = None,
) -> str:
    lines: list[str] = []
    body = post.text.strip()

    if post.post_type == "repost" and post.repost_of_uri:
        lines.append(f"Reposted: {post.repost_of_uri}")
    if body:
        lines.append(body)
    if post.quote_uri:
        lines.append(f"Quoted: {post.quote_uri}")
    for link in post.external_links:
        if link and link not in body:
            lines.append(link)

    content = "\n".join(lines).strip()
    rendered = content

    if max_chars is not None and len(rendered) > max_chars:
        rendered = content[:max_chars].rstrip()
    return rendered


def content_hash(post: SourcePost) -> str:
    media_urls = "\n".join(item.url for item in post.media)
    raw = "\n".join(
        [
            post.platform,
            post.uri,
            post.text.strip(),
            post.reply_to_uri or "",
            post.quote_uri or "",
            post.repost_of_uri or "",
            media_urls,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
