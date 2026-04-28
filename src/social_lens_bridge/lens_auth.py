from __future__ import annotations

from collections.abc import Callable

from .auth import AuthError, TokenSession, access_token_needs_refresh, session_from_env_tokens
from .clients.orb import OrbQrClient
from .config import BridgeConfig
from .state import BridgeState


OrbClientFactory = Callable[[], OrbQrClient]


class LensSessionManager:
    def __init__(
        self,
        config: BridgeConfig,
        state: BridgeState,
        *,
        orb_client_factory: OrbClientFactory | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self.orb_client_factory = orb_client_factory or (
            lambda: OrbQrClient(config.orb_auth_base_url, origin=config.orb_auth_origin)
        )
        self._cached_session: TokenSession | None = None

    def load(self) -> TokenSession:
        session = self._cached_session or self._load_configured_or_stored_session()
        if access_token_needs_refresh(session):
            session = self._refresh_session(session)
        if not session.access_token:
            raise AuthError(
                "Lens access token is required; set LENS_ACCESS_TOKEN or LENS_REFRESH_TOKEN."
            )
        self._cached_session = session
        return session

    def _load_configured_or_stored_session(self) -> TokenSession:
        if self._has_configured_tokens():
            return session_from_env_tokens(
                access_token=self.config.lens_access_token,
                refresh_token=self.config.lens_refresh_token,
                id_token=self.config.lens_id_token,
            )
        return self.state.load_token("lens")

    def _has_configured_tokens(self) -> bool:
        return any(
            (
                self.config.lens_access_token,
                self.config.lens_refresh_token,
                self.config.lens_id_token,
            )
        )

    def _refresh_session(self, session: TokenSession) -> TokenSession:
        if not session.refresh_token:
            raise AuthError(
                "Lens access token is expired and no LENS_REFRESH_TOKEN is available; "
                "set LENS_REFRESH_TOKEN or run `bridge auth orb-qr`."
            )
        refreshed = self.orb_client_factory().refresh(session.refresh_token)
        merged = TokenSession(
            access_token=refreshed.access_token,
            refresh_token=refreshed.refresh_token or session.refresh_token,
            id_token=refreshed.id_token or session.id_token,
            account=refreshed.account or session.account,
            handle=refreshed.handle or session.handle,
            source=refreshed.source or session.source,
            expires_at=refreshed.expires_at,
            created_at=refreshed.created_at,
        )
        if not merged.access_token:
            raise AuthError("Lens refresh did not return an access token")
        self.state.save_token(
            provider="lens",
            access_token=merged.access_token,
            refresh_token=merged.refresh_token,
            id_token=merged.id_token,
            expires_at=merged.expires_at,
            account=merged.account,
            handle=merged.handle,
            source=merged.source,
        )
        return merged


def lens_auth_warning(config: BridgeConfig) -> str | None:
    if config.lens_access_token and not config.lens_refresh_token:
        return (
            "LENS_ACCESS_TOKEN is set without LENS_REFRESH_TOKEN; this will only work until "
            "the access token expires, usually about 10 minutes."
        )
    return None
