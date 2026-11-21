# vector_sdk (Rust)
vector_sdk is the official ergonomic Rust library for bots on Vector, a private encrypted messenger built on Nostr. It is a thin layer over the vector-core engine used by the desktop and mobile apps. SDK v0.3 targets Vector v0.4.0 and later. Crate: vector_sdk on crates.io, docs at docs.rs/vector_sdk.

# Quick start
let bot = VectorBot::builder().nsec("nsec1...").build().await?; bot.on_message(|_bot, msg| async move { if msg.is_mine() { return; } let _ = msg.reply("hi").await; }).await?; Handles DMs and communities with one API: a Channel works the same for both. Auto-reconnects and catches up on missed messages. One bot per process.

# Channel API
channel.send, reply(msg_id, text), react(msg_id, emoji), react_custom, typing(), edit, delete, send_file(path); bot.download_attachment, save_attachment. Get channels with bot.channel(id), bot.dm(npub) or msg.channel(). Incoming message: msg.reply, msg.react, msg.is_mine(), msg.text(), msg.member(), msg.community(), attachments on msg.message.attachments.

# Communities
member.kick/ban/unban/grant_admin/revoke_admin/is_admin; bot.community(id).invite(npub), create_invite(), members(), edit(name, description), leave(), dissolve() (owner only). Accept invites with builder .public() (anyone) or .whitelist([npubs]); otherwise handle bot.pending_invites() and bot.accept_invite(id).

# Events and profiles
bot.on_event handles BotEvent: Message, MessageUpdate (reaction or edit), deletes, MemberJoin, member leave, typing, invites, removed from community. Profiles: fetch_profile, cached_profile, update_profile, set_status, block, unblock, set_nickname, upload_image. Bots are tagged as bots automatically.

# Accounts
No key: build() creates an identity on first run and reuses it (give each bot its own .data_dir). .nsec(), .mnemonic(), .password() for encrypted keys, VectorBot::generate_nsec(). Optional Tor with the tor feature plus .tor(); I2P as well. Escape hatch: bot.core() for the full VectorCore.

# Mini Apps in the Rust SDK (xdc module)
A bot can join a Mini App's realtime channel: bot.xdc("app-id").run(|bot, mut session| async move { while let Some(event) = session.next().await { if let XdcEvent::Data(frame) = event { let msg: Value = frame.json().unwrap_or_default(); session.send_json(&json!({...})).await; } } }). Match by manifest id, by hash, or "*" (no download). Matching reads the app manifest by downloading it once, up to download_limit (default 32 MiB). XdcFrame::from says who sent; verified_sender is the one to act on. The bot's selfAddr is its npub. Messages are up to 128000 bytes, nothing is stored, so greet newcomers with state and resend whole state after changes. Sessions started by run end when the handler returns, after 3 minutes without anyone connected (idle_timeout) or 15 minutes with no message (quiet_timeout); Xdc::join sessions last until dropped. Players see each other's IPs, and a bot on Tor or I2P stays out unless allow_outside_transport. Use cases: opponent, referee, or the server behind an app that needs more than a phone (an LLM, a database).
