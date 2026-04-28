import unittest

from social_lens_bridge.clients.bluesky import (
    BlueskyClient,
    build_bluesky_record,
    source_post_from_jetstream_event,
    source_posts_from_records_response,
)
from social_lens_bridge.models import PreparedPost, SourcePost


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request_json(self, method, url, *, body=None, headers=None):
        self.calls.append((method, url, body, headers))
        return self.response


class BlueskyTests(unittest.TestCase):
    def test_revalidates_event_did_before_normalizing_post(self) -> None:
        event = {
            "did": "did:plc:source",
            "commit": {
                "operation": "create",
                "collection": "app.bsky.feed.post",
                "rkey": "abc",
                "record": {"text": "hello", "createdAt": "2026-04-27T10:00:00Z"},
            },
        }

        self.assertIsNone(source_post_from_jetstream_event(event, expected_did="did:plc:other"))

    def test_normalizes_reply_quote_media_and_links(self) -> None:
        event = {
            "did": "did:plc:source",
            "commit": {
                "operation": "create",
                "collection": "app.bsky.feed.post",
                "rkey": "abc",
                "record": {
                    "text": "hello",
                    "createdAt": "2026-04-27T10:00:00Z",
                    "reply": {"parent": {"uri": "at://did:plc:p/app.bsky.feed.post/p1"}},
                    "embed": {
                        "$type": "app.bsky.embed.recordWithMedia",
                        "record": {"record": {"uri": "at://did:plc:q/app.bsky.feed.post/q1"}},
                        "media": {
                            "$type": "app.bsky.embed.images",
                            "images": [
                                {
                                    "alt": "alt",
                                    "image": {"ref": {"$link": "blob"}, "mimeType": "image/png"},
                                }
                            ],
                        },
                    },
                },
            },
        }

        post = source_post_from_jetstream_event(event, expected_did="did:plc:source")

        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post.uri, "at://did:plc:source/app.bsky.feed.post/abc")
        self.assertEqual(post.reply_to_uri, "at://did:plc:p/app.bsky.feed.post/p1")
        self.assertEqual(post.quote_uri, "at://did:plc:q/app.bsky.feed.post/q1")
        self.assertEqual(post.media[0].mime_type, "image/png")

    def test_lens_to_bluesky_record_uses_tags_for_bridge_markers(self) -> None:
        post = SourcePost(
            platform="lens",
            uri="lens://post/1",
            author_id="0xabc",
            created_at="2026-04-27T10:00:00Z",
            text="hello",
        )
        prepared = PreparedPost(
            source=post,
            target_platform="bluesky",
            text="hello",
            source_url="lens://post/1",
        )

        record = build_bluesky_record(prepared, created_at="2026-04-27T10:00:00Z")

        self.assertEqual(record["text"], "hello")
        self.assertNotIn("Mirrored from Lens:", record["text"])
        self.assertEqual(record["tags"], ["lens-to-bluesky"])
        self.assertFalse(any("orb" in tag for tag in record["tags"]))

    def test_skips_bluesky_records_with_lens_bridge_tags(self) -> None:
        event = {
            "did": "did:plc:source",
            "commit": {
                "operation": "create",
                "collection": "app.bsky.feed.post",
                "rkey": "abc",
                "record": {
                    "text": "hello",
                    "createdAt": "2026-04-27T10:00:00Z",
                    "tags": ["lens-to-bluesky"],
                },
            },
        }

        self.assertIsNone(source_post_from_jetstream_event(event, expected_did="did:plc:source"))

    def test_normalizes_historical_list_records_response(self) -> None:
        response = {
            "cursor": "cursor-2",
            "records": [
                {
                    "uri": "at://did:plc:source/app.bsky.feed.post/abc",
                    "cid": "cid-1",
                    "value": {
                        "text": "historical",
                        "createdAt": "2026-04-27T10:00:00Z",
                    },
                },
                {
                    "uri": "at://did:plc:other/app.bsky.feed.post/skip",
                    "value": {"text": "wrong actor"},
                },
            ],
        }

        posts, cursor = source_posts_from_records_response(
            response,
            expected_did="did:plc:source",
            collection="app.bsky.feed.post",
        )

        self.assertEqual(cursor, "cursor-2")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].uri, "at://did:plc:source/app.bsky.feed.post/abc")
        self.assertEqual(posts[0].cid, "cid-1")
        self.assertEqual(posts[0].text, "historical")

    def test_list_records_uses_reverse_newest_first_pagination(self) -> None:
        http = FakeHttp({"records": []})
        client = BlueskyClient("https://bsky.social", http=http)

        client.list_records(
            repo="did:plc:source",
            collection="app.bsky.feed.post",
            cursor="cursor-1",
            limit=25,
        )

        self.assertEqual(http.calls[0][0], "GET")
        self.assertIn("/xrpc/com.atproto.repo.listRecords?", http.calls[0][1])
        self.assertIn("repo=did%3Aplc%3Asource", http.calls[0][1])
        self.assertIn("collection=app.bsky.feed.post", http.calls[0][1])
        self.assertIn("cursor=cursor-1", http.calls[0][1])
        self.assertIn("limit=25", http.calls[0][1])
        self.assertIn("reverse=true", http.calls[0][1])


if __name__ == "__main__":
    unittest.main()
