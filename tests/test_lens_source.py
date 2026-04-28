import unittest

from social_lens_bridge.clients.lens import (
    bridge_mirrors_from_lens_response,
    source_posts_from_lens_response,
)


class LensSourceTests(unittest.TestCase):
    def test_normalizes_lens_posts_and_skips_bridge_metadata(self) -> None:
        response = {
            "data": {
                "posts": {
                    "items": [
                        {
                            "id": "1",
                            "slug": "post-one",
                            "timestamp": "2026-04-27T10:00:00Z",
                            "author": {"address": "0xabc"},
                            "metadata": {"content": "hello from lens"},
                        },
                        {
                            "id": "2",
                            "timestamp": "2026-04-27T10:01:00Z",
                            "author": {"address": "0xabc"},
                            "metadata": {
                                "content": "hello",
                                "tags": ["orb-nostr-lens", "bridge:source:nostr"],
                            },
                        },
                        {
                            "id": "3",
                            "timestamp": "2026-04-27T10:02:00Z",
                            "author": {"address": "0xabc"},
                            "metadata": {
                                "$schema": "https://json-schemas.lens.dev/posts/text-only/3.0.0.json",
                                "lens": {
                                    "content": "mirrored from nostr",
                                    "tags": ["nostr-to-lens"],
                                },
                            },
                        },
                        {
                            "id": "4",
                            "timestamp": "2026-04-27T10:03:00Z",
                            "author": {"address": "0xabc"},
                            "metadata": {
                                "$schema": "https://json-schemas.lens.dev/posts/text-only/3.0.0.json",
                                "lens": {
                                    "content": "mirrored from bluesky",
                                    "tags": ["bluesky-to-lens"],
                                },
                            },
                        },
                    ],
                    "pageInfo": {"next": "cursor-2"},
                }
            }
        }

        posts, cursor = source_posts_from_lens_response(response)

        self.assertEqual(cursor, "cursor-2")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].platform, "lens")
        self.assertEqual(posts[0].uri, "lens://post/1")
        self.assertEqual(posts[0].text, "hello from lens")

    def test_extracts_existing_bridge_source_mappings_from_lens_metadata(self) -> None:
        response = {
            "data": {
                "posts": {
                    "items": [
                        {
                            "id": "lens-post-1",
                            "metadata": {
                                "lens": {
                                    "tags": ["bluesky-to-lens"],
                                    "attributes": [
                                        {
                                            "key": "bridge.source",
                                            "type": "String",
                                            "value": "bluesky",
                                        },
                                        {
                                            "key": "bridge.source_uri",
                                            "type": "String",
                                            "value": "at://did/app.bsky.feed.post/abc",
                                        },
                                    ],
                                }
                            },
                        }
                    ],
                    "pageInfo": {"next": "cursor-2"},
                }
            }
        }

        mirrors, cursor = bridge_mirrors_from_lens_response(response)

        self.assertEqual(cursor, "cursor-2")
        self.assertEqual(len(mirrors), 1)
        self.assertEqual(mirrors[0].source_platform, "bluesky")
        self.assertEqual(mirrors[0].source_uri, "at://did/app.bsky.feed.post/abc")
        self.assertEqual(mirrors[0].target_uri, "lens://post/lens-post-1")


if __name__ == "__main__":
    unittest.main()
