# Vector in short
Vector is a private, encrypted messenger built on Nostr, with desktop and mobile apps built on the vector-core engine (Tauri). Website vectorapp.io, source github.com/VectorPrivacy/Vector. Default relays include wss://jskitty.cat/nostr, wss://asia.vectorapp.io/nostr, wss://nostr.computingcache.com and wss://relay.damus.io; relay settings are customizable with live metrics. DMs use NIP-17 gift wraps.

# Communities
Vector v0.4.0 is the Communities release. Communities have channels, roles, permission overwrites, modes and invite links (vectorapp.io/invite/... links hold an naddr plus a key). Communities are built on the Concord protocol. Bots join with invite links via client.join(url) in vector-sdk-py.

# Invites
A Community invite link looks like https://vectorapp.io/invite/naddr1...#<key>. The part after # is the key. Anyone with the full link can join, so treat it as a secret for private communities.

# Where to look
Docs: vector-privacy.gitbook.io/vector-privacy (SDK page, Communities, Concord protocol). Rust SDK: docs.rs/vector_sdk and github.com/VectorPrivacy/Vector-SDK. Python SDK: github.com/lucky-edgelord/vector-sdk-py. WebXDC spec: webxdc.org/docs/spec.
