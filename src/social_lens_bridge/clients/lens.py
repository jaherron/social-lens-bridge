from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ..auth import AuthError, TokenSession
from ..http import HttpJsonClient
from ..models import PreparedPost, SourcePost
from ..rendering import has_bridge_marker

BRIDGE_ROUTE_TAGS = {
    "nostr-to-lens",
    "lens-to-nostr",
    "bluesky-to-lens",
    "lens-to-bluesky",
}


@dataclass(frozen=True)
class BridgeMirror:
    source_platform: str
    source_uri: str
    target_platform: str
    target_uri: str
    target_id: str | None = None

CREATE_POST_MUTATION = """
mutation CreatePost($request: CreatePostRequest!) {
  post(request: $request) {
    ... on PostResponse {
      hash
    }
    ... on SelfFundedTransactionRequest {
      raw {
        to
        data
        value
      }
    }
    ... on SponsoredTransactionRequest {
      raw {
        to
        data
        value
      }
    }
    ... on TransactionWillFail {
      reason
    }
  }
}
""".strip()

POSTS_QUERY = """
query Posts($request: PostsRequest!) {
  posts(request: $request) {
    items {
      ... on Post {
        id
        slug
        timestamp
        author {
          address
          username {
            localName
            namespace
          }
        }
        metadata {
          ... on TextOnlyMetadata {
            content
            tags
            attributes {
              key
              type
              value
            }
          }
          ... on ImageMetadata {
            content
            tags
            attributes {
              key
              type
              value
            }
          }
          ... on VideoMetadata {
            content
            tags
            attributes {
              key
              type
              value
            }
          }
          ... on AudioMetadata {
            content
            tags
            attributes {
              key
              type
              value
            }
          }
        }
      }
    }
    pageInfo {
      next
    }
  }
}
""".strip()


def build_lens_metadata(
    post: SourcePost,
    *,
    text: str,
    handle: str | None,
    app_id: str = "social-lens-bridge",
) -> dict[str, Any]:
    attributes = [
        {"key": "bridge.id", "type": "String", "value": app_id},
        {"key": "bridge.source", "type": "String", "value": post.platform},
        {"key": "bridge.source_uri", "type": "String", "value": post.uri},
        {"key": "bridge.author_id", "type": "String", "value": post.author_id},
        {
            "key": "bridge.marker",
            "type": "String",
            "value": f"Mirrored from {post.platform.capitalize()}:",
        },
    ]
    return {
        "$schema": "https://json-schemas.lens.dev/posts/text-only/3.0.0.json",
        "lens": {
            "id": str(uuid4()),
            "locale": "en",
            "content": text,
            "mainContentFocus": "TEXT_ONLY",
            "tags": [f"{post.platform}-to-lens"],
            "attributes": attributes,
        },
    }


def build_create_post_request(
    *,
    content_uri: str,
    comment_on: str | None = None,
    quote_on: str | None = None,
    feed: str | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {"contentUri": content_uri}
    if comment_on:
        request["commentOn"] = {"post": comment_on}
    elif quote_on:
        request["quoteOf"] = {"post": quote_on}
    if feed:
        request["feed"] = feed
    return {"query": CREATE_POST_MUTATION, "variables": {"request": request}}


class LensClient:
    def __init__(self, api_url: str, *, http: HttpJsonClient | None = None) -> None:
        self.api_url = api_url
        self.http = http or HttpJsonClient()

    def create_post(self, session: TokenSession, *, content_uri: str, prepared: PreparedPost) -> dict[str, Any]:
        request = build_create_post_request(
            content_uri=content_uri,
            comment_on=prepared.reply_to_target_uri,
            quote_on=prepared.quote_target_uri,
        )
        return self.http.request_json(
            "POST",
            self.api_url,
            body=request,
            headers=_auth_headers(session),
        )

    def list_account_posts(
        self,
        session: TokenSession,
        *,
        account: str,
        cursor: str | None = None,
        page_size: str = "TEN",
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "pageSize": page_size,
            "filter": {"authors": [account]},
        }
        if cursor:
            request["cursor"] = cursor
        return self.http.request_json(
            "POST",
            self.api_url,
            body={"query": POSTS_QUERY, "variables": {"request": request}},
            headers=_auth_headers(session),
        )


def source_posts_from_lens_response(response: dict[str, Any]) -> tuple[tuple[SourcePost, ...], str | None]:
    posts_container = response.get("data", {}).get("posts", {})
    items = posts_container.get("items", []) if isinstance(posts_container, dict) else []
    page_info = posts_container.get("pageInfo", {}) if isinstance(posts_container, dict) else {}
    next_cursor = page_info.get("next") if isinstance(page_info.get("next"), str) else None
    posts: list[SourcePost] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        post_id = item.get("id")
        if not isinstance(post_id, str):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        content = _metadata_content(metadata)
        tags = _metadata_list(metadata, "tags")
        attributes = _metadata_list(metadata, "attributes")
        if has_bridge_marker(content) or _has_bridge_metadata(tags, attributes):
            continue
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        author_id = author.get("address") if isinstance(author.get("address"), str) else ""
        timestamp = item.get("timestamp") if isinstance(item.get("timestamp"), str) else ""
        posts.append(
            SourcePost(
                platform="lens",
                uri=f"lens://post/{post_id}",
                author_id=author_id,
                created_at=timestamp,
                text=content,
            )
        )
    return tuple(posts), next_cursor


def bridge_mirrors_from_lens_response(
    response: dict[str, Any],
) -> tuple[tuple[BridgeMirror, ...], str | None]:
    posts_container = response.get("data", {}).get("posts", {})
    items = posts_container.get("items", []) if isinstance(posts_container, dict) else []
    page_info = posts_container.get("pageInfo", {}) if isinstance(posts_container, dict) else {}
    next_cursor = page_info.get("next") if isinstance(page_info.get("next"), str) else None
    mirrors: list[BridgeMirror] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        post_id = item.get("id")
        if not isinstance(post_id, str):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        tags = _metadata_list(metadata, "tags")
        attributes = _metadata_list(metadata, "attributes")
        source_uri = _attribute_value(attributes, "bridge.source_uri")
        source_platform = _attribute_value(attributes, "bridge.source")
        if not source_uri:
            continue
        if not source_platform:
            source_platform = _source_platform_from_tags(tags)
        if not source_platform:
            continue
        mirrors.append(
            BridgeMirror(
                source_platform=source_platform,
                source_uri=source_uri,
                target_platform="lens",
                target_uri=f"lens://post/{post_id}",
                target_id=post_id,
            )
        )
    return tuple(mirrors), next_cursor


def _metadata_content(metadata: dict[str, Any]) -> str:
    for payload in _metadata_payloads(metadata):
        content = payload.get("content")
        if isinstance(content, str):
            return content
    return ""


def _metadata_list(metadata: dict[str, Any], key: str) -> list[Any]:
    for payload in _metadata_payloads(metadata):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _metadata_payloads(metadata: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    payloads = [metadata]
    lens = metadata.get("lens")
    if isinstance(lens, dict):
        payloads.append(lens)
    raw = metadata.get("raw")
    if isinstance(raw, dict):
        raw_lens = raw.get("lens")
        if isinstance(raw_lens, dict):
            payloads.append(raw_lens)
    return tuple(payloads)


def _has_bridge_metadata(tags: list[Any], attributes: list[Any]) -> bool:
    if any(
        isinstance(tag, str)
        and (tag in BRIDGE_ROUTE_TAGS or tag.startswith("bridge:source:"))
        for tag in tags
    ):
        return True
    for attr in attributes:
        if isinstance(attr, dict) and str(attr.get("key", "")).startswith("bridge."):
            return True
    return False


def _attribute_value(attributes: list[Any], key: str) -> str | None:
    for attr in attributes:
        if not isinstance(attr, dict):
            continue
        if attr.get("key") == key and isinstance(attr.get("value"), str):
            return attr["value"]
    return None


def _source_platform_from_tags(tags: list[Any]) -> str | None:
    for tag in tags:
        if not isinstance(tag, str):
            continue
        if tag.endswith("-to-lens"):
            return tag[: -len("-to-lens")]
    return None


def _auth_headers(session: TokenSession) -> dict[str, str]:
    if not session.access_token:
        raise AuthError("Lens access token is required")
    return {"authorization": f"Bearer {session.access_token}"}
