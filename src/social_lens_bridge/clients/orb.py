from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..auth import AuthError, TokenSession, session_from_access_token, session_from_poll_response
from ..http import HttpJsonClient


@dataclass(frozen=True)
class QrInit:
    qr_code: str
    secret: str
    deep_link: str | None = None


class OrbQrClient:
    def __init__(
        self,
        base_url: str,
        *,
        origin: str,
        http: HttpJsonClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.origin = origin.rstrip("/")
        self.http = http or HttpJsonClient()

    def init_login(self) -> QrInit:
        response = self.http.request_json(
            "GET",
            f"{self.base_url}/qr/init",
            headers=self._origin_headers(),
        )
        data = _unwrap_orb_data(response)
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        qr_code = inner.get("qrCode")
        secret = inner.get("secret")
        if not isinstance(qr_code, str) or not isinstance(secret, str):
            raise AuthError("QR init response did not contain qrCode and secret")
        deep_link = inner.get("deepLink") if isinstance(inner.get("deepLink"), str) else None
        return QrInit(qr_code=qr_code, secret=secret, deep_link=deep_link)

    def poll_login(self, secret: str) -> TokenSession | None:
        response = self.http.request_json(
            "POST",
            f"{self.base_url}/qr/poll",
            body={"secret": secret},
            headers=self._origin_headers(),
        )
        return session_from_poll_response(response)

    def refresh(self, refresh_token: str) -> TokenSession:
        response = self.http.request_json(
            "POST",
            f"{self.base_url}/auth/refresh",
            body={"refreshToken": refresh_token},
            headers=self._origin_headers(),
        )
        access = response.get("accessToken")
        if not isinstance(access, str):
            raise AuthError("refresh response did not contain accessToken")
        return session_from_access_token(
            access,
            refresh_token=response.get("refreshToken")
            if isinstance(response.get("refreshToken"), str)
            else refresh_token,
            id_token=response.get("idToken") if isinstance(response.get("idToken"), str) else None,
        )

    def _origin_headers(self) -> dict[str, str]:
        return {"origin": self.origin, "referer": self.origin}


def _unwrap_orb_data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, dict):
        return data
    return response
