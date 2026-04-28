from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

from ..http import HttpJsonClient
from ..models import MediaItem, PreparedPost, SourcePost

BRIDGE_ROUTE_TAGS = {
    "nostr-to-lens",
    "lens-to-nostr",
    "bluesky-to-lens",
    "lens-to-bluesky",
}
LEGACY_BRIDGE_TAGS = {
    "orb-bluesky-lens",
    "bridge-source-lens",
}


def source_post_from_jetstream_event(
    event: dict[str, Any],
    *,
    expected_did: str,
) -> SourcePost | None:
    did = event.get("did")
    if did != expected_did:
        return None

    commit = event.get("commit")
    if not isinstance(commit, dict) or commit.get("operation") != "create":
        return None

    collection = commit.get("collection")
    record = commit.get("record")
    rkey = commit.get("rkey")
    cid = commit.get("cid") if isinstance(commit.get("cid"), str) else None
    if not isinstance(collection, str) or not isinstance(record, dict) or not isinstance(rkey, str):
        return None
    if _has_bridge_tags(record.get("tags")):
        return None

    uri = f"at://{did}/{collection}/{rkey}"
    created_at = record.get("createdAt") if isinstance(record.get("createdAt"), str) else ""

    if collection == "app.bsky.feed.repost":
        subject = record.get("subject") if isinstance(record.get("subject"), dict) else {}
        subject_uri = subject.get("uri") if isinstance(subject.get("uri"), str) else None
        return SourcePost(
            platform="bluesky",
            uri=uri,
            author_id=did,
            created_at=created_at,
            cid=cid,
            post_type="repost",
            repost_of_uri=subject_uri,
        )

    if collection != "app.bsky.feed.post":
        return None

    reply = record.get("reply") if isinstance(record.get("reply"), dict) else {}
    parent = reply.get("parent") if isinstance(reply.get("parent"), dict) else {}
    reply_to_uri = parent.get("uri") if isinstance(parent.get("uri"), str) else None
    embed = record.get("embed") if isinstance(record.get("embed"), dict) else {}
    quote_uri, media, external_links = _extract_embed(embed)

    return SourcePost(
        platform="bluesky",
        uri=uri,
        author_id=did,
        created_at=created_at,
        cid=cid,
        text=record.get("text") if isinstance(record.get("text"), str) else "",
        reply_to_uri=reply_to_uri,
        quote_uri=quote_uri,
        media=media,
        external_links=external_links,
    )


def source_posts_from_records_response(
    response: dict[str, Any],
    *,
    expected_did: str,
    collection: str,
) -> tuple[tuple[SourcePost, ...], str | None]:
    records = response.get("records", [])
    next_cursor = response.get("cursor") if isinstance(response.get("cursor"), str) else None
    posts: list[SourcePost] = []
    if not isinstance(records, list):
        return (), next_cursor
    for item in records:
        if not isinstance(item, dict):
            continue
        event = _jetstream_event_from_record(item, collection=collection)
        if event is None:
            continue
        post = source_post_from_jetstream_event(event, expected_did=expected_did)
        if post is not None:
            posts.append(post)
    return tuple(posts), next_cursor


def _jetstream_event_from_record(item: dict[str, Any], *, collection: str) -> dict[str, Any] | None:
    uri = item.get("uri")
    value = item.get("value")
    if not isinstance(uri, str) or not isinstance(value, dict):
        return None
    parsed = _parse_at_uri(uri)
    if parsed is None:
        return None
    did, uri_collection, rkey = parsed
    if uri_collection != collection:
        return None
    return {
        "did": did,
        "commit": {
            "operation": "create",
            "collection": uri_collection,
            "rkey": rkey,
            "record": value,
            "cid": item.get("cid") if isinstance(item.get("cid"), str) else None,
        },
    }


def _parse_at_uri(uri: str) -> tuple[str, str, str] | None:
    parts = urlsplit(uri)
    if parts.scheme != "at" or not parts.netloc:
        return None
    path_parts = [part for part in parts.path.split("/") if part]
    if len(path_parts) != 2:
        return None
    return parts.netloc, path_parts[0], path_parts[1]


def _extract_embed(embed: dict[str, Any]) -> tuple[str | None, tuple[MediaItem, ...], tuple[str, ...]]:
    embed_type = embed.get("$type")
    quote_uri: str | None = None
    media: tuple[MediaItem, ...] = ()
    links: tuple[str, ...] = ()

    if embed_type == "app.bsky.embed.recordWithMedia":
        record_embed = embed.get("record") if isinstance(embed.get("record"), dict) else {}
        media_embed = embed.get("media") if isinstance(embed.get("media"), dict) else {}
        quote_uri = _extract_quote_uri(record_embed)
        _, media, links = _extract_embed(media_embed)
    elif embed_type == "app.bsky.embed.record":
        quote_uri = _extract_quote_uri(embed)
    elif embed_type == "app.bsky.embed.images":
        image_items = []
        for image in embed.get("images", []):
            if not isinstance(image, dict):
                continue
            blob = image.get("image") if isinstance(image.get("image"), dict) else {}
            ref = blob.get("ref") if isinstance(blob.get("ref"), dict) else {}
            link = ref.get("$link") if isinstance(ref.get("$link"), str) else "unknown"
            image_items.append(
                MediaItem(
                    url=f"atproto://blob/{link}",
                    mime_type=blob.get("mimeType") if isinstance(blob.get("mimeType"), str) else None,
                    alt=image.get("alt") if isinstance(image.get("alt"), str) else None,
                    size_bytes=blob.get("size") if isinstance(blob.get("size"), int) else None,
                )
            )
        media = tuple(image_items)
    elif embed_type == "app.bsky.embed.external":
        external = embed.get("external") if isinstance(embed.get("external"), dict) else {}
        uri = external.get("uri") if isinstance(external.get("uri"), str) else None
        links = (uri,) if uri else ()
    return quote_uri, media, links


def _extract_quote_uri(embed: dict[str, Any]) -> str | None:
    record = embed.get("record") if isinstance(embed.get("record"), dict) else {}
    value = record.get("uri")
    return value if isinstance(value, str) else None


def build_bluesky_record(prepared: PreparedPost, *, created_at: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "$type": "app.bsky.feed.post",
        "text": prepared.text,
        "createdAt": created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if prepared.reply_to_target_uri:
        record["reply"] = {
            "root": {"uri": prepared.reply_to_target_uri, "cid": ""},
            "parent": {"uri": prepared.reply_to_target_uri, "cid": ""},
        }
    elif prepared.quote_target_uri:
        record["embed"] = {
            "$type": "app.bsky.embed.record",
            "record": {"uri": prepared.quote_target_uri, "cid": ""},
        }
    tags = _bridge_tags_for_source(prepared.source.platform)
    if tags:
        record["tags"] = list(tags)
    return record


def _bridge_tags_for_source(source_platform: str) -> tuple[str, ...]:
    if source_platform == "lens":
        return (f"{source_platform}-to-bluesky",)
    return ()


def _has_bridge_tags(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    tags = {tag for tag in value if isinstance(tag, str)}
    return bool(tags.intersection(BRIDGE_ROUTE_TAGS) or LEGACY_BRIDGE_TAGS.issubset(tags))


class BlueskyClient:
    def __init__(self, service_url: str = "https://bsky.social", *, http: HttpJsonClient | None = None) -> None:
        self.service_url = service_url.rstrip("/")
        self.http = http or HttpJsonClient()

    def create_session(self, *, identifier: str, password: str) -> dict[str, Any]:
        return self.http.request_json(
            "POST",
            f"{self.service_url}/xrpc/com.atproto.server.createSession",
            body={"identifier": identifier, "password": password},
        )

    def resolve_handle(self, handle: str) -> str:
        normalized = handle.strip().removeprefix("@")
        response = self.http.request_json(
            "GET",
            f"{self.service_url}/xrpc/com.atproto.identity.resolveHandle?"
            f"{urlencode({'handle': normalized})}",
        )
        did = response.get("did") if isinstance(response, dict) else None
        if not isinstance(did, str):
            raise RuntimeError("Bluesky handle resolution response did not include did")
        return did

    def list_records(
        self,
        *,
        repo: str,
        collection: str,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, str] = {
            "repo": repo,
            "collection": collection,
            "limit": str(limit),
            "reverse": "true",
        }
        if cursor:
            params["cursor"] = cursor
        return self.http.request_json(
            "GET",
            f"{self.service_url}/xrpc/com.atproto.repo.listRecords?{urlencode(params)}",
        )

    def create_post(self, *, access_jwt: str, repo: str, record: dict[str, Any]) -> dict[str, Any]:
        return self.http.request_json(
            "POST",
            f"{self.service_url}/xrpc/com.atproto.repo.createRecord",
            body={"repo": repo, "collection": "app.bsky.feed.post", "record": record},
            headers={"authorization": f"Bearer {access_jwt}"},
        )
