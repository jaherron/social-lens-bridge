from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from time import time
from typing import Any


class AuthError(ValueError):
    pass


class UserIdMismatch(AuthError):
    pass


@dataclass(frozen=True)
class TokenSession:
    access_token: str | None = None
    refresh_token: str | None = None
    id_token: str | None = None
    account: str | None = None
    handle: str | None = None
    source: str | None = None
    expires_at: int | None = None
    created_at: int = 0


def decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        raise AuthError("JWT is missing a payload segment")
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode())
        data = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthError("JWT payload is not valid JSON") from exc
    if not isinstance(data, dict):
        raise AuthError("JWT payload is not an object")
    return data


def _unwrap_poll_response(response: dict[str, Any]) -> dict[str, Any]:
    nested = response.get("data")
    if isinstance(nested, dict) and "status" in nested:
        return nested
    return response


def session_from_poll_response(response: dict[str, Any]) -> TokenSession | None:
    payload = _unwrap_poll_response(response)
    status = payload.get("status")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

    if status == "FAILED":
        raise AuthError("QR sign-in failed")
    if status != "SUCCESS" or data.get("processed") is not True:
        return None

    access_token = data.get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        raise AuthError("QR sign-in completed without an access token")

    session = session_from_access_token(
        access_token,
        refresh_token=data.get("refreshToken") if isinstance(data.get("refreshToken"), str) else None,
        id_token=data.get("idToken") if isinstance(data.get("idToken"), str) else None,
    )
    user_id = data.get("user_id")
    if isinstance(user_id, str) and session.account and user_id != session.account:
        raise UserIdMismatch(f"user_id mismatch: {user_id} != {session.account}")

    handle = data.get("handle")
    if isinstance(handle, str) and handle and not handle.startswith("@"):
        handle = f"@{handle}"
    elif not isinstance(handle, str):
        handle = None

    return TokenSession(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        id_token=session.id_token,
        account=session.account,
        handle=handle,
        source=data.get("source") if isinstance(data.get("source"), str) else None,
        expires_at=session.expires_at,
        created_at=int(time()),
    )


def session_from_env_tokens(
    *,
    access_token: str | None,
    refresh_token: str | None,
    id_token: str | None,
) -> TokenSession:
    access_token = _clean_token(access_token)
    refresh_token = _clean_token(refresh_token)
    id_token = _clean_token(id_token)
    if id_token and not access_token and not refresh_token:
        raise AuthError(
            "LENS_ID_TOKEN alone cannot authenticate Lens API; set LENS_ACCESS_TOKEN or LENS_REFRESH_TOKEN."
        )
    if access_token:
        return session_from_access_token(
            access_token,
            refresh_token=refresh_token,
            id_token=id_token,
        )
    if refresh_token:
        return TokenSession(
            access_token=None,
            refresh_token=refresh_token,
            id_token=id_token,
            created_at=int(time()),
        )
    raise AuthError("Lens auth requires LENS_ACCESS_TOKEN or LENS_REFRESH_TOKEN.")


def session_from_access_token(
    access_token: str,
    *,
    refresh_token: str | None = None,
    id_token: str | None = None,
    handle: str | None = None,
    source: str | None = None,
) -> TokenSession:
    token_payload = decode_jwt_payload(access_token)
    actor = token_payload.get("act") if isinstance(token_payload.get("act"), dict) else {}
    account = actor.get("sub") if isinstance(actor.get("sub"), str) else None
    return TokenSession(
        access_token=access_token,
        refresh_token=refresh_token,
        id_token=id_token,
        account=account,
        handle=handle,
        source=source,
        expires_at=_jwt_expires_at(token_payload),
        created_at=int(time()),
    )


def access_token_needs_refresh(
    session: TokenSession,
    *,
    now: int | None = None,
    leeway_seconds: int = 30,
) -> bool:
    if not session.access_token:
        return True
    expires_at = session.expires_at
    if expires_at is None:
        try:
            expires_at = _jwt_expires_at(decode_jwt_payload(session.access_token))
        except AuthError:
            return False
    if expires_at is None:
        return False
    current = int(time()) if now is None else now
    return expires_at <= current + leeway_seconds


def _jwt_expires_at(payload: dict[str, Any]) -> int | None:
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        return int(exp)
    if isinstance(exp, str) and exp.isdigit():
        return int(exp)
    return None


def _clean_token(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
