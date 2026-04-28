import unittest
import uuid

from social_lens_bridge.clients.lens import POSTS_QUERY, build_create_post_request, build_lens_metadata
from social_lens_bridge.models import SourcePost


class LensTests(unittest.TestCase):
    def test_metadata_contains_visible_content_and_bridge_attributes(self) -> None:
        post = SourcePost(
            platform="nostr",
            uri=f"nostr:{'a' * 64}",
            author_id="b" * 64,
            created_at="2026-04-27T10:00:00Z",
            text="hello",
        )

        metadata = build_lens_metadata(post, text="hello", handle="@orb")

        self.assertEqual(
            metadata["$schema"],
            "https://json-schemas.lens.dev/posts/text-only/3.0.0.json",
        )
        self.assertNotIn("content", metadata)
        self.assertNotIn("appId", metadata)
        lens = metadata["lens"]
        uuid.UUID(lens["id"])
        self.assertEqual(lens["locale"], "en")
        self.assertEqual(lens["mainContentFocus"], "TEXT_ONLY")
        self.assertEqual(lens["content"], "hello")
        self.assertNotIn("Mirrored from Nostr:", lens["content"])
        self.assertEqual(lens["tags"], ["nostr-to-lens"])
        self.assertFalse(any("orb" in tag for tag in lens["tags"]))
        self.assertIn(
            {"key": "bridge.source_uri", "type": "String", "value": post.uri},
            lens["attributes"],
        )
        self.assertIn(
            {"key": "bridge.id", "type": "String", "value": "social-lens-bridge"},
            lens["attributes"],
        )
        self.assertIn(
            {"key": "bridge.marker", "type": "String", "value": "Mirrored from Nostr:"},
            lens["attributes"],
        )

    def test_posts_query_requests_bridge_markers_from_lens_metadata(self) -> None:
        self.assertIn("tags", POSTS_QUERY)
        self.assertIn("attributes", POSTS_QUERY)
        self.assertIn("key", POSTS_QUERY)
        self.assertIn("value", POSTS_QUERY)
        self.assertIn("type", POSTS_QUERY)

    def test_create_post_request_preserves_reply_and_quote_shape(self) -> None:
        request = build_create_post_request(
            content_uri="lens://metadata/1",
            comment_on="lens://post/comment",
            quote_on="lens://post/quote",
        )

        self.assertEqual(request["variables"]["request"]["contentUri"], "lens://metadata/1")
        self.assertEqual(
            request["variables"]["request"]["commentOn"],
            {"post": "lens://post/comment"},
        )
        self.assertNotIn("quoteOf", request["variables"]["request"])


if __name__ == "__main__":
    unittest.main()
