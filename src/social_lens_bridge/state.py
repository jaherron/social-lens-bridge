from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from time import time

from .auth import TokenSession


class BridgeState:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_owner_only_file()
        self._init_schema()

    def _ensure_owner_only_file(self) -> None:
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mirrors (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  direction TEXT NOT NULL,
                  source_platform TEXT NOT NULL,
                  source_uri TEXT NOT NULL,
                  target_platform TEXT NOT NULL,
                  target_uri TEXT NOT NULL,
                  target_id TEXT,
                  content_hash TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  UNIQUE(source_platform, source_uri, target_platform)
                );

                CREATE TABLE IF NOT EXISTS cursors (
                  source TEXT PRIMARY KEY,
                  cursor TEXT NOT NULL,
                  updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tokens (
                  provider TEXT PRIMARY KEY,
                  access_token TEXT NOT NULL,
                  refresh_token TEXT,
                  id_token TEXT,
                  expires_at INTEGER,
                  account TEXT,
                  handle TEXT,
                  source TEXT,
                  updated_at INTEGER NOT NULL
                );
                """
            )

    def record_mirror(
        self,
        *,
        direction: str,
        source_platform: str,
        source_uri: str,
        target_platform: str,
        target_uri: str,
        target_id: str | None,
        content_hash: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO mirrors (
                  direction, source_platform, source_uri, target_platform,
                  target_uri, target_id, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    direction,
                    source_platform,
                    source_uri,
                    target_platform,
                    target_uri,
                    target_id,
                    content_hash,
                    int(time()),
                ),
            )

    def has_mirror(self, *, source_platform: str, source_uri: str, target_platform: str) -> bool:
        return self.find_target_uri(
            source_platform=source_platform,
            source_uri=source_uri,
            target_platform=target_platform,
        ) is not None

    def find_target_uri(
        self,
        *,
        source_platform: str,
        source_uri: str,
        target_platform: str,
    ) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT target_uri FROM mirrors
                WHERE source_platform = ? AND source_uri = ? AND target_platform = ?
                """,
                (source_platform, source_uri, target_platform),
            ).fetchone()
        return str(row["target_uri"]) if row else None

    def set_cursor(self, source: str, cursor: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cursors (source, cursor, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                  cursor = excluded.cursor,
                  updated_at = excluded.updated_at
                """,
                (source, cursor, int(time())),
            )

    def get_cursor(self, source: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT cursor FROM cursors WHERE source = ?", (source,)).fetchone()
        return str(row["cursor"]) if row else None

    def save_token(
        self,
        *,
        provider: str,
        access_token: str,
        refresh_token: str | None = None,
        id_token: str | None = None,
        expires_at: int | None = None,
        account: str | None = None,
        handle: str | None = None,
        source: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tokens (
                  provider, access_token, refresh_token, id_token, expires_at,
                  account, handle, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                  access_token = excluded.access_token,
                  refresh_token = excluded.refresh_token,
                  id_token = excluded.id_token,
                  expires_at = excluded.expires_at,
                  account = excluded.account,
                  handle = excluded.handle,
                  source = excluded.source,
                  updated_at = excluded.updated_at
                """,
                (
                    provider,
                    access_token,
                    refresh_token,
                    id_token,
                    expires_at,
                    account,
                    handle,
                    source,
                    int(time()),
                ),
            )

    def load_token(self, provider: str) -> TokenSession:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tokens WHERE provider = ?", (provider,)).fetchone()
        if not row:
            raise KeyError(f"no token stored for provider {provider}")
        return TokenSession(
            access_token=str(row["access_token"]),
            refresh_token=row["refresh_token"],
            id_token=row["id_token"],
            expires_at=row["expires_at"],
            account=row["account"],
            handle=row["handle"],
            source=row["source"],
        )
