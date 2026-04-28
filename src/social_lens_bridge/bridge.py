from __future__ import annotations

from .media import MediaPolicy, validate_media_items
from .models import Platform, PreparedPost, SourcePost
from .rendering import content_hash, has_bridge_marker, render_mirrored_text, source_url
from .state import BridgeState


def direction_for(source_platform: str, target_platform: str) -> str:
    return f"{source_platform}-to-{target_platform}"


class BridgeService:
    def __init__(self, state: BridgeState, media_policy: MediaPolicy | None = None) -> None:
        self.state = state
        self.media_policy = media_policy or MediaPolicy()

    def should_skip(self, post: SourcePost, *, target_platform: Platform) -> bool:
        if has_bridge_marker(post.text):
            return True
        return self.state.has_mirror(
            source_platform=post.platform,
            source_uri=post.uri,
            target_platform=target_platform,
        )

    def prepare(self, post: SourcePost, *, target_platform: Platform) -> PreparedPost:
        reply_to_target_uri = self._mapped_target(post.reply_to_uri, post.platform, target_platform)
        quote_target_uri = self._mapped_target(post.quote_uri, post.platform, target_platform)
        repost_target_uri = self._mapped_target(post.repost_of_uri, post.platform, target_platform)

        return PreparedPost(
            source=post,
            target_platform=target_platform,
            text=render_mirrored_text(post, target_platform=target_platform),
            source_url=source_url(post),
            reply_to_target_uri=reply_to_target_uri,
            quote_target_uri=quote_target_uri,
            repost_target_uri=repost_target_uri,
            media=validate_media_items(post.media, self.media_policy) if post.media else (),
        )

    def record_publish(self, prepared: PreparedPost, target_uri: str, target_id: str | None = None) -> None:
        self.state.record_mirror(
            direction=direction_for(prepared.source.platform, prepared.target_platform),
            source_platform=prepared.source.platform,
            source_uri=prepared.source.uri,
            target_platform=prepared.target_platform,
            target_uri=target_uri,
            target_id=target_id,
            content_hash=content_hash(prepared.source),
        )

    def _mapped_target(
        self,
        source_uri_value: str | None,
        source_platform: str,
        target_platform: str,
    ) -> str | None:
        if not source_uri_value:
            return None
        target_uri = self.state.find_target_uri(
            source_platform=source_platform,
            source_uri=source_uri_value,
            target_platform=target_platform,
        )
        if target_platform == "lens" and target_uri and not target_uri.startswith("lens://post/"):
            return None
        return target_uri
