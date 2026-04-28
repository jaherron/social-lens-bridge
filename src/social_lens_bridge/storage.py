from __future__ import annotations

import json
import uuid
from typing import Any

from .http import HttpJsonClient, HttpJsonError


def build_acl(*, chain_id: int, lens_account: str | None = None) -> dict[str, Any]:
    if lens_account:
        return {"template": "lens_account", "lens_account": lens_account, "chain_id": chain_id}
    return {"template": "immutable", "chain_id": chain_id}


def make_multipart_form(
    metadata: dict[str, Any],
    *,
    acl: dict[str, Any],
    field_name: str,
    boundary: str | None = None,
) -> tuple[bytes, str]:
    boundary = boundary or f"----orb-bridge-{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def add_file(name: str, filename: str, content_type: str, body: bytes) -> None:
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                body,
                b"\r\n",
            ]
        )

    add_file(
        field_name,
        "metadata.json",
        "application/json",
        json.dumps(metadata).encode("utf-8"),
    )
    add_file(
        "lens-acl.json",
        "lens-acl.json",
        "application/json",
        json.dumps(acl).encode("utf-8"),
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class GroveStorageClient:
    def __init__(
        self,
        *,
        storage_url: str,
        key_url: str,
        chain_id: int,
        x_grove_client: str | None = None,
        http: HttpJsonClient | None = None,
    ) -> None:
        self.storage_url = storage_url
        self.key_url = key_url
        self.chain_id = chain_id
        self.x_grove_client = x_grove_client
        self.http = http or HttpJsonClient()

    def get_storage_key(self) -> str:
        headers = self._headers()
        response = self.http.request_json("POST", self.key_url, headers=headers)
        if isinstance(response, list):
            first = response[0] if response else None
            if isinstance(first, dict) and isinstance(first.get("storage_key"), str):
                return first["storage_key"]
        if isinstance(response, dict) and isinstance(response.get("storage_key"), str):
            return response["storage_key"]
        items = response.get("data") if isinstance(response, dict) and isinstance(response.get("data"), list) else None
        if items and isinstance(items[0], dict) and isinstance(items[0].get("storage_key"), str):
            return items[0]["storage_key"]
        raise HttpJsonError("Grove storage key response did not include storage_key", body=response)

    def upload_json(self, metadata: dict[str, Any], *, lens_account: str | None = None) -> dict[str, Any]:
        storage_key = self.get_storage_key()
        acl = build_acl(chain_id=self.chain_id, lens_account=lens_account)
        body, content_type = make_multipart_form(metadata, acl=acl, field_name=storage_key)
        headers = {"content-type": content_type, **self._headers()}
        response = self.http.request_json(
            "POST",
            f"{self.storage_url.rstrip('/')}/{storage_key}",
            body=body,
            headers=headers,
        )
        return _single_grove_item(response, "Grove upload response did not include an item")

    def _headers(self) -> dict[str, str]:
        return {"X-GROVE-CLIENT": self.x_grove_client} if self.x_grove_client else {}


def _single_grove_item(response: Any, message: str) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if isinstance(response, list) and response and isinstance(response[0], dict):
        return response[0]
    items = response.get("data") if isinstance(response, dict) and isinstance(response.get("data"), list) else None
    if items and isinstance(items[0], dict):
        return items[0]
    raise HttpJsonError(message, body=response)
