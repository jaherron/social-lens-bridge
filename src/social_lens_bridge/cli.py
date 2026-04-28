from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .auth import AuthError
from .clients.orb import OrbQrClient
from .config import BridgeConfig
from .daemon import BackfillOptions, BridgeDaemon
from .lens_auth import lens_auth_warning
from .state import BridgeState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bridge")
    parser.add_argument("--state-db", help="Path to the SQLite bridge state DB")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth = subparsers.add_parser("auth", help="Authentication helpers")
    auth.add_argument("--state-db", help=argparse.SUPPRESS, default=argparse.SUPPRESS)
    auth_subparsers = auth.add_subparsers(dest="auth_command", required=True)
    auth_qr = auth_subparsers.add_parser("orb-qr", help="Sign in to Lens through Orb QR flow")
    auth_qr.add_argument("--state-db", help=argparse.SUPPRESS, default=argparse.SUPPRESS)

    run = subparsers.add_parser("run", help="Run the bidirectional daemon")
    run.add_argument("--state-db", help=argparse.SUPPRESS, default=argparse.SUPPRESS)
    run.add_argument("--poll-interval-seconds", type=int, default=None)

    once = subparsers.add_parser("once", help="Run one bridge cycle")
    once.add_argument(
        "--direction",
        choices=("nostr-to-lens", "lens-to-nostr", "bluesky-to-lens", "lens-to-bluesky"),
        required=True,
    )
    once.add_argument("--mode", choices=("live", "backfill"), default=None)
    once.add_argument("--state-db", help=argparse.SUPPRESS, default=argparse.SUPPRESS)

    backfill = subparsers.add_parser("backfill", help="Run historical inbound migration")
    backfill.add_argument(
        "--direction",
        choices=("nostr-to-lens", "bluesky-to-lens"),
        required=True,
    )
    backfill.add_argument("--limit", type=int, default=None)
    backfill.add_argument("--since", type=parse_since, default=None)
    backfill.add_argument("--until-exhausted", action="store_true")
    backfill.add_argument("--state-db", help=argparse.SUPPRESS, default=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = BridgeConfig.from_env()
    state = BridgeState(Path(args.state_db or config.state_db))

    try:
        if args.command == "auth":
            if args.auth_command == "orb-qr":
                return _auth_orb_qr(config, state)
        if args.command == "run":
            _print_lens_auth_warning(config)
            interval = args.poll_interval_seconds or config.poll_interval_seconds
            if args.poll_interval_seconds:
                config = BridgeConfig(
                    **{**config.__dict__, "poll_interval_seconds": interval},
                )
            BridgeDaemon(config, state, status=_print_status).run_forever()
            return 0
        if args.command == "once":
            _print_lens_auth_warning(config)
            count = BridgeDaemon(config, state, status=_print_status).run_once(
                args.direction,
                mode=args.mode,
            )
            print(f"Mirrored {count} posts for {args.direction}.")
            return 0
        if args.command == "backfill":
            _print_lens_auth_warning(config)
            options = _backfill_options(args)
            count = BridgeDaemon(config, state, status=_print_status).run_once(
                args.direction,
                mode="backfill",
                backfill_options=options,
            )
            print(f"Backfilled {count} posts for {args.direction}.")
            return 0
    except (AuthError, KeyError, RuntimeError, ValueError) as exc:
        message = str(exc.args[0]) if exc.args else str(exc)
        print(message, file=sys.stderr)
        return 1

    parser.error("unknown command")
    return 2


def parse_since(value: str) -> int:
    stripped = value.strip()
    if stripped.isdigit():
        return int(stripped)
    try:
        normalized = stripped.replace("Z", "+00:00")
        if len(normalized) == 10:
            dt = datetime.fromisoformat(normalized).replace(tzinfo=UTC)
        else:
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--since must be a unix timestamp, YYYY-MM-DD, or ISO datetime"
        ) from exc


def _backfill_options(args: argparse.Namespace) -> BackfillOptions:
    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be greater than 0")
    if args.limit is None and args.since is None and not args.until_exhausted:
        raise ValueError("backfill requires --limit, --since, or --until-exhausted")
    return BackfillOptions(
        limit=args.limit,
        since=args.since,
        until_exhausted=bool(args.until_exhausted),
    )


def _auth_orb_qr(config: BridgeConfig, state: BridgeState) -> int:
    client = OrbQrClient(config.orb_auth_base_url, origin=config.orb_auth_origin)
    init = client.init_login()
    qr_payload = normalize_orb_approve_link(init.deep_link or init.qr_code)
    print("Scan this Orb sign-in QR:")
    print(render_qr_terminal(qr_payload))
    print("Fallback sign-in payload:")
    print(qr_payload)
    print("Waiting for QR sign-in...")

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        session = client.poll_login(init.secret)
        if session is not None:
            state.save_token(
                provider="lens",
                access_token=session.access_token,
                refresh_token=session.refresh_token,
                id_token=session.id_token,
                expires_at=session.expires_at,
                account=session.account,
                handle=session.handle,
                source=session.source,
            )
            maybe_prompt_save_refresh_token(session.refresh_token)
            print(f"Saved Lens session for {session.handle or session.account or 'account'}")
            return 0
        time.sleep(2)

    print("Timed out waiting for QR sign-in", file=sys.stderr)
    return 1


def render_qr_terminal(payload: str) -> str:
    try:
        import qrcode
    except ImportError:
        return "QR rendering requires the qrcode package. Use the fallback payload below."

    qr = qrcode.QRCode(border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    return _render_matrix(matrix)


def normalize_orb_approve_link(payload: str) -> str:
    parts = urlsplit(payload)
    if parts.query:
        return urlunsplit(("https", "orb.club", "/approve", parts.query, ""))
    return payload


def maybe_prompt_save_refresh_token(
    refresh_token: str | None,
    *,
    env_path: Path = Path(".env"),
    input_fn=input,
    is_tty: bool | None = None,
) -> bool:
    if not refresh_token:
        return False
    if is_tty is None:
        is_tty = sys.stdin.isatty()
    if not is_tty:
        return False
    answer = input_fn("Save Lens refresh token to .env for longer-lived auth? [y/N] ")
    if answer.strip().lower() not in {"y", "yes"}:
        return False
    upsert_env_value(env_path, "LENS_REFRESH_TOKEN", refresh_token)
    print(f"Saved LENS_REFRESH_TOKEN to {env_path}")
    return True


def upsert_env_value(path: Path, key: str, value: str) -> None:
    line = f"{key}={value}"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replaced = False
    next_lines = []
    for existing in lines:
        if existing.startswith(f"{key}="):
            next_lines.append(line)
            replaced = True
        else:
            next_lines.append(existing)
    if not replaced:
        next_lines.append(line)
    path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _print_lens_auth_warning(config: BridgeConfig) -> None:
    warning = lens_auth_warning(config)
    if warning:
        print(warning, file=sys.stderr)


def _print_status(message: str) -> None:
    print(f"[bridge] {message}", file=sys.stderr, flush=True)


def _render_matrix(matrix: list[list[bool]]) -> str:
    lines: list[str] = []
    for y in range(0, len(matrix), 2):
        top = matrix[y]
        bottom = matrix[y + 1] if y + 1 < len(matrix) else [False] * len(top)
        line = []
        for upper, lower in zip(top, bottom):
            if upper and lower:
                line.append("██")
            elif upper:
                line.append("▀▀")
            elif lower:
                line.append("▄▄")
            else:
                line.append("  ")
        lines.append("".join(line))
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
