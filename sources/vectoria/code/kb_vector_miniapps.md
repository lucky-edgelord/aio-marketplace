# Mini Apps in Vector
Vector runs WebXDC-compatible Mini Apps in isolated webviews, compatible with Delta Chat. Apps are .xdc files. Sandbox: no network access (no HTTP or WebSocket), strict CSP allowing only self, data and blob URLs, WebRTC disabled to prevent IP leaks, and a permission system for sensitive APIs. Apps are identified by the SHA-256 hash of the file, not by a name the author controls.

# Vector Nexus and the marketplace
The in-app Mini App store is Vector Nexus. It is a decentralized marketplace built on Nostr and Blossom: listings are Nostr events of kind 30078 (parameterized replaceable application-specific data) with metadata tags, the .xdc files are hosted on Blossom, and downloads are verified by SHA-256. A trusted publisher key (the Vector project) is shown first and users can add custom publishers. Listings can be edited only by their publisher.

# Permissions
Apps can request permissions such as camera, microphone, screen capture, speaker selection, geolocation, clipboard read and write, accelerometer, gyroscope, magnetometer, light sensor, Bluetooth, MIDI, fullscreen, autoplay, picture in picture and screen wake lock. Users see a prompt on first launch and can toggle each one in App Details. Enforcement is by Permissions-Policy headers plus JavaScript API wrapping, and permissions persist per file hash.

# Bridge API in Vector
webxdc.selfAddr is the user's npub, webxdc.selfName the display name. setUpdateListener and sendUpdate sync persisted state to chat participants. joinRealtimeChannel gives a low-latency peer to peer channel with messages up to 128 KB.

# Realtime multiplayer
Realtime uses Iroh gossip (QUIC). When a user taps start multiplayer the app calls joinRealtimeChannel, which advertises the peer over Nostr; others who open the same app in the same chat join. The topic is minted once when the .xdc is sent and carried on the file event as a webxdc-topic tag so every participant joins the same topic. Direct IPs are stripped from advertisements but Iroh relays see peer IPs, and players in a session can see each other's IPs. Compatible with Delta Chat's realtime implementation.

# Example: DOOM
VectorPrivacy/DOOM is a fork of Cloudflare's doom-wasm with networking rebuilt for WebXDC realtime channels: no server, host auto-elected by magic-byte election in about 3 seconds, position snapshots every 57 ms with interpolation, host-authoritative damage and NPCs, late join, touch controls, a 4.2 MB .xdc. Find it in Vector Nexus under Multiplayer.
