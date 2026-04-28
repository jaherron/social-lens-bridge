# AGENTS.md

This repo is a Python CLI bridge for Nostr, Bluesky, and Lens. Keep changes
small, testable, and aligned with the existing clients in `src/social_lens_bridge`.

## Core Contract

- The CLI entrypoint is `bridge = social_lens_bridge.cli:main`.
- Shared local state lives in SQLite through `BridgeState`.
- Do not commit `.env`, `data/`, private keys, app passwords, access tokens,
  refresh tokens, or Grove credentials.
- Lens auth is loaded through `LensSessionManager`; do not bypass its refresh
  handling.
- `ORB_AUTH_ORIGIN` must identify the bridge, for example
  `https://social-lens-bridge.local`. Do not change it to `orb.club`.
- QR fallback links may normalize to `https://orb.club/approve?...`.
- The repo is MIT licensed. BlueNostr is GPL-3.0; use it as behavioral
  reference only, and do not copy GPL source into this repo without revisiting
  the license.

## Route Semantics

Supported directions are:

- `nostr-to-lens`
- `lens-to-nostr`
- `bluesky-to-lens`
- `lens-to-bluesky`

Inbound routes are `nostr-to-lens` and `bluesky-to-lens`.

- `bridge once --direction <inbound>` defaults to backfill mode with `limit=1`.
- `bridge once --direction <inbound> --mode live` streams until Ctrl-C.
- `bridge backfill --direction <inbound>` is historical migration and requires
  `--limit`, `--since`, or `--until-exhausted`.
- `bridge run` starts inbound live streams and polls Lens outbound routes.

Nostr live subscriptions must stay open after `EOSE`; `EOSE` only says the relay
finished sending stored backlog. Bluesky live reads from Jetstream until
cancelled.

## Loop Prevention

Never put bridge provenance in visible content.

- Lens provenance belongs in Lens metadata tags and attributes.
- Lens metadata tags are route names such as `nostr-to-lens` or
  `bluesky-to-lens`.
- Lens metadata attributes include `bridge.source`, `bridge.source_uri`,
  `bridge.author_id`, and `bridge.marker`.
- Nostr bridge provenance belongs in event tags such as `bridge-route` and
  `bridge-source`.
- Bluesky bridge provenance belongs in record `tags`.
- Do not prefix new route tags with `orb`.

The bridge also records source-to-target mappings in SQLite. Before inbound
backfills, it hydrates existing Lens-side `bridge.source_uri` metadata into that
local state so a fresh DB does not repost already mirrored Lens posts.

## Important Files

- `src/social_lens_bridge/cli.py`: command parsing, QR auth UX, backfill args.
- `src/social_lens_bridge/daemon.py`: route orchestration and live/backfill modes.
- `src/social_lens_bridge/bridge.py`: shared prepare/skip/record logic.
- `src/social_lens_bridge/lens_auth.py`: Lens access/refresh token handling.
- `src/social_lens_bridge/clients/lens.py`: Lens metadata schema and Lens API calls.
- `src/social_lens_bridge/clients/nostr.py`: Nostr key handling, relay reads, publishing.
- `src/social_lens_bridge/clients/bluesky.py`: Bluesky Jetstream/listRecords parsing and posting.
- `src/social_lens_bridge/state.py`: SQLite schema, cursors, tokens, mirrors.
- `tests/`: unittest suite.

## Local Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.lock
python3 -m pip install -e .
```

Run verification:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/social-lens-bridge-pycache python3 -m compileall src tests
git diff --check
```

Use the repo venv if present:

```bash
.venv/bin/python -m unittest discover -s tests
```

## Editing Guidance

- Prefer repo-native helpers over adding compatibility layers.
- Keep network calls inside the small client classes.
- Keep visible post content clean; bridge provenance goes to tags/attributes.
- Add or update focused tests for behavior changes.
- If touching auth, run the auth and Lens-session tests.
- If touching live mode, test cancellation and burst handling.
