# WebXDC basics
WebXDC is a format for mini apps shared in a chat. An app is a ZIP file with the extension .xdc. The ZIP must use Deflate or Store compression and must contain index.html. It may contain manifest.toml, icon.png or icon.jpg. Each device runs its own copy of the app when the recipient taps Start. Apps are network-isolated, so no HTTP requests or WebSockets; they share state only through the webxdc API.

# WebXDC manifest and icon
manifest.toml sits in the zip root. Fields: name (the app name; if missing the file name is used) and source_code_url (optional link to the source). Vector's SDK also reads an id field in the manifest (for example id = "vector-counter") so a bot can match apps by id. The icon should be square, 128 to 512 pixels; do not add rounded corners, the messenger does that.

# webxdc.js
Add <script src="webxdc.js"></script> to index.html. Do not put webxdc.js in the .xdc file: the messenger provides it. To test in a browser use the webxdc-dev tool or the webxdc.js from the Hello example app.

# sendUpdate
window.webxdc.sendUpdate(update, descr). The update is sent to all peers and the sender also receives it in the listener. update.payload can be any JSON value (not undefined; binary must be base64). Optional fields: info (short chat message, about 50 chars, use sparingly), href (relative URL to open when someone taps the info message), document (document name, about 20 chars, only for apps that edit documents), summary (short text beside the icon like "8 votes", about 20 chars), notify (map of address to notification text, "*" is a catch-all). descr is deprecated, pass an empty string. If you call it too often updates get delayed: default sendUpdateInterval is 10000 ms and sendUpdateMaxSize is 128000 bytes. Batch changes and chunk big data.

# setUpdateListener
let promise = window.webxdc.setUpdateListener((update) => {}, serial). The callback runs for updates sent by you and by peers. serial is the last serial you already know (default 0). The promise resolves when all known updates were processed. Each update has payload, serial, max_serial (when serial equals max_serial this is the newest update), info, href, document, summary, notify. Call it once only: calling it several times is undefined behavior and only the last one works. Keep state derivable from the sequence of updates, since every peer replays them.

# selfAddr and selfName
webxdc.selfAddr is the user's address (in Vector it is their npub) and webxdc.selfName their display name.

# sendToChat
window.webxdc.sendToChat({file:{name, blob|base64|plainText}, text}) prepares a message the user can send to a chat; the user may edit or cancel and the app is not told. It may exit the app. Use plainText for text files rather than btoa, which breaks on emoji. Errors reject the promise.

# importFiles
let files = await window.webxdc.importFiles({extensions:[".ics"], mimeTypes:["text/calendar"], multiple:false}). Returns an array of File objects. Extensions start with a dot. Specifying a mimeType means you should also list the extensions.

# Realtime channel
const ch = window.webxdc.joinRealtimeChannel(); ch.setListener((data) => {}) receives Uint8Array items; ch.send(uint8array) sends up to 128000 bytes; ch.leave() leaves. It is experimental: check window.webxdc.joinRealtimeChannel !== undefined. Channels are private to the chat, isolated per app, and ephemeral: data only reaches peers connected right now, nothing is stored and delivery is not guaranteed, so send whole state after changes and greet newcomers with the current state. Joining twice without leaving throws.

# Packaging a .xdc
Zip the files with index.html at the root: zip -9 -r app.xdc index.html manifest.toml icon.png *.js *.css. Keep it small; chat messages carry the file. Test with webxdc-dev before sharing.

# State patterns
Because updates are replayed by every peer, treat the update list as an event log. Use serial to catch up, keep your own state in memory built from updates, and use info messages sparingly. For games with fast input use the realtime channel for movement and sendUpdate for results that must persist.
