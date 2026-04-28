from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class HttpJsonError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class HttpJsonClient:
    def __init__(
        self,
        *,
        timeout: float = 15.0,
        user_agent: str = "social-lens-bridge/0.1",
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8") if body is not None else None
        request_headers = {
            "accept": "application/json",
            "user-agent": self.user_agent,
            **(headers or {}),
        }
        if body is not None and not isinstance(body, bytes):
            request_headers["content-type"] = "application/json"
        req = Request(url, data=data, headers=request_headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return self._decode_response(resp.read())
        except HTTPError as exc:
            error_body = self._decode_response(exc.read(), allow_empty=True)
            raise HttpJsonError(
                f"HTTP {exc.code} from {url}",
                status=exc.code,
                body=error_body,
            ) from exc

    @staticmethod
    def _decode_response(raw: bytes, *, allow_empty: bool = False) -> Any:
        if allow_empty and not raw:
            return {}
        text = raw.decode("utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if allow_empty:
                return text
            raise
