import json
import unittest

from social_lens_bridge.storage import GroveStorageClient, build_acl, make_multipart_form


class StorageTests(unittest.TestCase):
    def test_acl_defaults_to_lens_account_only_when_account_is_available(self) -> None:
        acl = build_acl(chain_id=232, lens_account="0xabc")

        self.assertEqual(
            acl,
            {"template": "lens_account", "lens_account": "0xabc", "chain_id": 232},
        )

    def test_multipart_form_contains_metadata_and_acl_without_logging_secrets(self) -> None:
        body, content_type = make_multipart_form(
            {"content": "hello"},
            acl={"template": "immutable", "chain_id": 232},
            field_name="storage-key",
            boundary="test-boundary",
        )

        self.assertIn("multipart/form-data; boundary=test-boundary", content_type)
        self.assertIn(b'name="storage-key"; filename="metadata.json"', body)
        self.assertIn(json.dumps({"content": "hello"}).encode(), body)
        self.assertIn(b'name="lens-acl.json"; filename="lens-acl.json"', body)

    def test_grove_upload_posts_multipart_body_to_storage_key(self) -> None:
        class FakeHttp:
            def __init__(self) -> None:
                self.calls = []

            def request_json(self, method, url, *, body=None, headers=None):
                self.calls.append((method, url, body, headers))
                if url.endswith("/key"):
                    return [{"storage_key": "abc"}]
                return [{"uri": "lens://abc", "gatewayUrl": "https://example.com/abc"}]

        http = FakeHttp()
        client = GroveStorageClient(
            storage_url="https://storage.example.com",
            key_url="https://storage.example.com/key",
            chain_id=232,
            x_grove_client="client",
            http=http,
        )

        result = client.upload_json({"content": "hello"}, lens_account="0xabc")

        self.assertEqual(result["uri"], "lens://abc")
        self.assertEqual(http.calls[1][0], "POST")
        self.assertEqual(http.calls[1][1], "https://storage.example.com/abc")
        self.assertIsInstance(http.calls[1][2], bytes)
        self.assertEqual(http.calls[1][3]["X-GROVE-CLIENT"], "client")


if __name__ == "__main__":
    unittest.main()
