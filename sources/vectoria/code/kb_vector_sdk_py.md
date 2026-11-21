# vector-sdk-py overview
vector-sdk-py is an unofficial community discord.py-style Python library for Vector messenger bots, powered by the official Rust vector_sdk compiled in with PyO3. Same decorators, cogs, ctx, checks, cooldowns, converters, wait_for, tasks.loop, embeds and views as discord.py. Install: pip install git+https://github.com/lucky-edgelord/vector-sdk-py. It compiles Rust, so you need rustup and cmake (for the Opus voice codec). Python 3.9+ with an abi3 wheel. Optional features: whisper (speech to text), tor, i2p via --config-settings=build-args="--features whisper,tor". Voice and Mini Apps are built by default.

# Minimal bot
import vector
from vector.ext import commands
bot = commands.Bot(command_prefix="!")
@bot.event
async def on_ready(): print(f"Logged in as {bot.user}")
@bot.command()
async def ping(ctx): await ctx.reply("pong")
bot.run(os.environ.get("VECTOR_NSEC"))
Commands also appear in Vector's / picker with typed args. Default prefix is "/", set "!" to accept text commands too. Load cogs in setup_hook so they are in the manifest published at startup.

# Keys
A Vector identity is a Nostr key; bot.run(nsec) works like a Discord token. vector.generate_nsec() makes one. bot.run() with no key reuses the key stored in data_dir (default ./vector-bot-data) and creates one on first run. bot.run(mnemonic="...") takes a seed phrase.

# discord.py mapping
Guild is Community (Guild is an alias). user.id is user.npub (id is an alias); ids are strings (npub or 64-char hex), so use TEXT columns not INTEGER. Intents are accepted and ignored. hybrid_command, group, Cog.listener, load_extension (async def setup(bot)), checks, has_permissions, cooldown, is_owner (owner_id takes an npub), converters, vector.Embed (rendered as coloured markdown), vector.ui View/Button/Select/Modal (built from reactions), app_commands CommandTree (sync is a no-op), tasks.loop, VoiceChannel.connect and vc.play(FFmpegPCMAudio). message.delete deletes your own, hides others. delete_after sets a NIP-40 expiry. ephemeral=True sends a DM. Discord-only classes are stubs raising vector.NotSupportedOnVector.

# Events
on_ready, on_message, on_message_edit, on_message_delete, on_reaction_add/remove, on_raw_reaction_add/remove, on_typing, on_member_join/remove/update, on_member_ban/unban, on_guild_join/remove, on_command_error and more. Vector extras: on_community_invite (await invite.accept() with invite_policy="manual"), on_community_change, on_member_kick, on_member_timeout, on_channel_keyed, on_community_dissolve, on_xdc_presence, on_xdc_session, on_slash_command.

# Communities and messages
Communities: create_community, join(invite_url), fetch_invite, guild.create_invite(max_age, label), roles, channels (text, voice, forum, category), permission overwrites, pins, audit_logs, bans, timeouts, nicknames, relay management. Messages: history() pulls older pages from relays, edit, replies, custom emoji packs via bot.subscribe_emoji_pack(naddr), attachments via await attachment.read(), typing, expires_in. Account: bot.user.edit(username=, avatar=, about=), block/unblock, change_presence. Anything unwrapped is at bot.native (the raw Rust bot).

# Mini Apps from Python
@bot.xdc_app("vector-counter") (or "*" for any app) async def handler(session): async for event in session: if event.type == "data": await session.send_json({...}). Event types: data, peer_join, peer_leave. event.verified_sender is the one to trust. await channel.send_xdc("app.xdc") shares an app; message.xdc.join() and .manifest() work on shared ones.

# Known issues
One bot per process (the Rust SDK is process-global; a second Client raises ClientException). Reply ordering: Vector sorts by whole-second timestamps, so replies wait briefly until the clock passes the incoming message second; disable with Client(reply_ordering=False). Also included: BDScript engine (vector-bdscript), aoi.js-style interface, Discord-compatible webhooks server (vector-webhooks).
