import unittest

from social_lens_bridge.media import MediaPolicy, UnsafeMediaError, validate_media_items
from social_lens_bridge.models import MediaItem


class MediaTests(unittest.TestCase):
    def test_rejects_non_https_media_urls(self) -> None:
        with self.assertRaises(UnsafeMediaError):
            validate_media_items([MediaItem(url="http://example.com/a.png")], MediaPolicy())

    def test_rejects_oversized_declared_media(self) -> None:
        with self.assertRaises(UnsafeMediaError):
            validate_media_items(
                [MediaItem(url="https://example.com/a.png", size_bytes=11, mime_type="image/png")],
                MediaPolicy(max_bytes=10),
            )

    def test_caps_item_count_and_allows_safe_mimes(self) -> None:
        items = [
            MediaItem(url=f"https://example.com/{i}.png", mime_type="image/png", size_bytes=1)
            for i in range(4)
        ]

        safe = validate_media_items(items, MediaPolicy(max_items=2, max_bytes=10))

        self.assertEqual(len(safe), 2)


if __name__ == "__main__":
    unittest.main()
