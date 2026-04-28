import unittest

from social_lens_bridge.models import SourcePost
from social_lens_bridge.rendering import has_bridge_marker, render_mirrored_text


class RenderingTests(unittest.TestCase):
    def test_rendered_text_adds_visible_source_link(self) -> None:
        post = SourcePost(
            platform="nostr",
            uri=f"nostr:{'a' * 64}",
            author_id="b" * 64,
            created_at="2026-04-27T10:00:00Z",
            text="hello",
        )

        rendered = render_mirrored_text(post, target_platform="lens")

        self.assertEqual(rendered, "hello")
        self.assertNotIn("Mirrored from Nostr:", rendered)
        self.assertFalse(has_bridge_marker(rendered))

    def test_truncation_preserves_source_marker(self) -> None:
        post = SourcePost(
            platform="lens",
            uri="https://orb.club/post/abc",
            author_id="0xabc",
            created_at="2026-04-27T10:00:00Z",
            text="x" * 500,
        )

        rendered = render_mirrored_text(post, target_platform="nostr", max_chars=180)

        self.assertLessEqual(len(rendered), 180)
        self.assertNotIn("Mirrored from Lens:", rendered)


if __name__ == "__main__":
    unittest.main()
