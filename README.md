# Social Lens Bridge

Bridge Nostr, Bluesky, and Lens through one local CLI.

The bridge keeps a shared SQLite state DB for Lens auth tokens, per-route
cursors, and source-to-target mirror mappings. That shared state is what makes
reply/quote mapping, idempotency, and loop prevention work across all three
networks.

## What It Does

Supported routes:

```text
nostr-to-lens
lens-to-nostr
bluesky-to-lens
lens-to-bluesky
```

Supported commands:

```bash
bridge auth orb-qr
bridge once --direction nostr-to-lens
bridge once --direction lens-to-nostr
bridge once --direction bluesky-to-lens
bridge once --direction lens-to-bluesky
bridge once --direction nostr-to-lens --mode live
bridge once --direction bluesky-to-lens --mode live
bridge backfill --direction nostr-to-lens --limit 50
bridge backfill --direction bluesky-to-lens --limit 50
bridge run
```

Live posting requires real Lens, Grove, Nostr, and/or Bluesky credentials in
`.env`, depending on the route.

## Setup

```bash
cd social-lens-bridge
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.lock
python3 -m pip install -e .
cp .env.example .env
```

Load `.env` before running commands:

```bash
set -a
source .env
set +a
```

## Setup Walkthrough

1. Fill the shared Lens/Grove values in `.env`:

```bash
ORB_AUTH_BASE_URL=https://new.orb.club/api
ORB_AUTH_ORIGIN=https://social-lens-bridge.local
BRIDGE_STATE_DB=./data/bridge.sqlite3
LENS_API_URL=https://api.lens.xyz/graphql
LENS_STORAGE_URL=https://api.grove.storage/
LENS_STORAGE_KEY_URL=https://api.grove.storage/link/new?amount=1
LENS_CHAIN_ID=232
X_GROVE_CLIENT=social-lens-bridge
```

`ORB_AUTH_ORIGIN` should identify this bridge, not `orb.club`. The QR fallback
link is normalized to `https://orb.club/approve?...`, but the auth origin stays
bridge-specific.

Do not set `LENS_ACCOUNT` for normal use. The bridge derives the Lens account
from the Orb/Lens auth token saved by `bridge auth orb-qr`. `LENS_ACCOUNT` is
only an override if you intentionally need to force a different account.

Lens auth can come from the QR-created state DB or from `.env` tokens:

- `LENS_REFRESH_TOKEN` only: the bridge refreshes immediately to get an access token.
- `LENS_ACCESS_TOKEN` plus `LENS_REFRESH_TOKEN`: the bridge uses the access token and refreshes it when expired.
- `LENS_ACCESS_TOKEN` only: works until the access token expires, usually about 10 minutes, then fails.
- `LENS_ID_TOKEN` alone: rejected because it cannot authenticate Lens API calls.

2. Add the Nostr key and relays if you use Nostr routes:

```bash
NOSTR_PUBLIC_KEY=
NOSTR_NSEC=nsec1...
NOSTR_PRIVATE_KEY_HEX=
NOSTR_RELAYS=wss://relay.damus.io,wss://nos.lol
NOSTR_RELAY_READ_TIMEOUT_SECONDS=15
```

`NOSTR_PUBLIC_KEY` may be `npub` or 64-char hex. It is optional when
`NOSTR_NSEC` or `NOSTR_PRIVATE_KEY_HEX` is set; the bridge derives the public
key for inbound relay reads.

Use `NOSTR_NSEC` or `NOSTR_PRIVATE_KEY_HEX` only for routes that publish to
Nostr, such as `lens-to-nostr`.

3. Add the Bluesky account if you use Bluesky routes:

```bash
BLUESKY_DID=did:plc:examplebridgeaccount
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_APP_PASSWORD=
BLUESKY_SERVICE_URL=https://bsky.social
BLUESKY_JETSTREAM_URL=wss://jetstream2.us-east.bsky.network/subscribe
BLUESKY_JETSTREAM_READ_TIMEOUT_SECONDS=15
```

`BLUESKY_HANDLE` can be used instead of `BLUESKY_DID` for inbound
`bluesky-to-lens`; the bridge resolves the handle to a DID.

4. Run Orb QR sign-in for Lens:

```bash
bridge auth orb-qr
```

The command prints a terminal QR code plus a fallback `orb.club/approve` link,
stores Lens tokens in the SQLite DB, and prompts whether to save
`LENS_REFRESH_TOKEN` to `.env` when a refresh token is returned.

## Running

For inbound routes, `bridge once` defaults to historical mode with a limit of 1.
That gives you a controlled smoke test against an existing source post:

```bash
bridge once --direction nostr-to-lens
bridge once --direction bluesky-to-lens
```

Outbound Lens routes run one Lens page/cursor cycle:

```bash
bridge once --direction lens-to-nostr
bridge once --direction lens-to-bluesky
```

Use live mode when you intentionally want to wait for new source events. It
keeps listening until you stop it with Ctrl-C:

```bash
bridge once --direction nostr-to-lens --mode live
bridge once --direction bluesky-to-lens --mode live
```

Nostr live mode keeps the relay subscription open after `EOSE`, because `EOSE`
only means the relay has finished sending stored backlog. Bluesky live mode
streams Jetstream events until cancelled.

Run historical inbound migrations with an explicit bound:

```bash
bridge backfill --direction bluesky-to-lens --limit 50
bridge backfill --direction bluesky-to-lens --since 2026-04-01
bridge backfill --direction bluesky-to-lens --until-exhausted
bridge backfill --direction nostr-to-lens --limit 50
bridge backfill --direction nostr-to-lens --since 2026-04-01
bridge backfill --direction nostr-to-lens --until-exhausted
```

Start the full daemon when smoke tests pass:

```bash
bridge run
```

The daemon runs inbound routes as live streams and polls Lens outbound routes on
`BRIDGE_POLL_INTERVAL_SECONDS`.

## Required Values By Direction

- Nostr to Lens: Lens tokens from QR state or `.env`, `NOSTR_PUBLIC_KEY` or a derivable private key, `NOSTR_RELAYS`, `LENS_STORAGE_URL`, and `LENS_STORAGE_KEY_URL`.
- Lens to Nostr: Lens tokens from QR state or `.env`, `NOSTR_NSEC` or `NOSTR_PRIVATE_KEY_HEX`, and `NOSTR_RELAYS`.
- Bluesky to Lens: Lens tokens from QR state or `.env`, `BLUESKY_HANDLE` or `BLUESKY_DID`, `LENS_STORAGE_URL`, and `LENS_STORAGE_KEY_URL`.
- Lens to Bluesky: Lens tokens from QR state or `.env`, `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`, and `BLUESKY_SERVICE_URL`.

## Mirroring Rules

- Lens-side mirrored posts carry route tags such as `nostr-to-lens` or `bluesky-to-lens` in Lens metadata, not visible content.
- Lens-side bridge provenance lives in metadata attributes such as `bridge.source`, `bridge.source_uri`, `bridge.author_id`, and `bridge.marker`.
- Visible markers like `Mirrored from Nostr:` or `Mirrored from Lens:` must not be added to post content.
- Nostr-side mirrored posts carry `bridge-route` and `bridge-source` event tags, not visible content markers.
- Bluesky-side mirrored posts carry record tags such as `lens-to-bluesky`, not visible content markers.
- The route tags are just the route names, for example `nostr-to-lens`; do not prefix them with `orb`.
- The bridge skips any post/event carrying known bridge route tags, including legacy tags from the earlier split bridge repos.
- The bridge skips source URIs already recorded in SQLite for the target platform.
- Before inbound backfills, the bridge scans Lens-side `bridge.source_uri` metadata into SQLite so existing mirrored Lens posts are not reposted from a fresh local state DB.
- Lens cursors are route-specific (`lens:nostr`, `lens:bluesky`) so one Lens post can be bridged to both targets.
- Replies and quotes use native target references only when the parent source URI is already mapped.
- Unsupported or unsafe media is not uploaded. The default policy allows up to 4 media items and 5 MB per item.

These rules prevent flows like `nostr -> lens -> bluesky -> lens` or
`bluesky -> lens -> nostr` from re-posting bridge output as fresh source
content.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/social-lens-bridge-pycache python3 -m compileall src tests
git diff --check
```

Use the installed venv binary when available:

```bash
.venv/bin/python -m unittest discover -s tests
```

## Security Notes

- `.env` and `data/` are ignored by git. Do not commit real tokens, nsecs, app passwords, Grove keys, or SQLite state DBs.
- The SQLite state DB is created with mode `0600`.
- Prefer Orb QR auth plus a refresh token over copying short-lived access tokens.
- Inbound Nostr events are revalidated against the configured pubkey; inbound Bluesky events are revalidated against the expected DID.

## License

MIT. This repo does not vendor BlueNostr source. BlueNostr is GPL-3.0, so do
not copy GPL source into this repo without revisiting the license.
