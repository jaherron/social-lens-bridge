# Social Lens Bridge Security Review

BlueNostr and the split bridge repos are safe enough to use as functional references, but not safe to operate unchanged for a multi-network bridge.

## Main Findings

- Source trust is too broad in the original reference. The bridge should still verify incoming Nostr pubkeys and Bluesky DIDs before publishing anything to Lens.
- Media handling is unbounded. Remote images are downloaded into memory without size, MIME, or item-count caps.
- URL and config validation is mostly implicit. Relay, Jetstream, Grove, and service URLs are accepted from config and used directly.
- Long-lived secrets are plaintext env/YAML values. The new bridge avoids wallet/private-key Lens auth and creates local SQLite state with mode `0600`.
- Supply chain inputs are loose. BlueNostr has unpinned Python deps and a floating Docker base image.

## Hardening Applied In This Repo

- Local pubkey revalidation for inbound Nostr relay events and DID revalidation for inbound Bluesky events.
- Route-tag loop prevention across Nostr, Bluesky, and Lens.
- SQLite source-to-target mappings for idempotency and reply/quote mapping.
- Owner-only state DB permissions.
- Orb QR sign-in for Lens access/refresh tokens.
- Explicit media policy with HTTPS, MIME, item-count, and byte caps.
- Dependency and live network calls are isolated behind small clients.
