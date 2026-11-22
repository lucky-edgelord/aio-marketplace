"""Vectoria in chat: ``!vec`` answers in text, ``!vectoria`` in a short talking video.

Replying to one of her answers carries on the conversation, in the same mode. Both modes share one memory per person.
Every answer gets 👍 and 👎; the votes are kept with the question and the answer.
"""

from __future__ import annotations

import asyncio
import logging
import time

import vector
from vector.ext import commands

from . import brain, video

log = logging.getLogger("vectiq.vectoria")
THUMBS = {"👍": 1, "👎": -1}
PROFILE_NAME = "Vectoria"
PROFILE_ABOUT = "Vector SDK and WebXDC expert. Ask me with !vec (text) or !vectoria (a short video)."
MAX_TEXT = 3800  # one chat message


class Vectoria(commands.Cog, name="Vectoria"):
    dashboard_page = {"label": "Vectoria", "icon": "▶", "scope": "bot", "owner_only": True}

    def __init__(self, bot):
        self.bot = bot
        self.data_dir = str(getattr(bot.config, "data_dir", None) or "data")
        self.store = brain.Store(f"{self.data_dir}/vectoria/vectoria.db")
        self.brain = brain.Brain(self.store)
        self.renders = asyncio.Semaphore(2)
        self.building: asyncio.Task | None = None
        self.last_error = ""

    async def cog_unload(self):
        await self.brain.drain()
        self.store.close()

    # -- settings and places -----------------------------------------------------------------------------------
    @property
    def cfg(self) -> dict:
        return self.bot.config.get("vectoria", {}) or {}

    @property
    def sam(self) -> str | None:
        return video.find_sam(str(self.cfg.get("sam_bin") or ""), self.data_dir)

    def allowed(self, message) -> bool:
        guild = getattr(message, "guild", None)
        if guild is None:
            return bool(self.cfg.get("allow_dms", False))
        if hasattr(self.bot, "serves") and not self.bot.serves(guild):
            return False
        wanted = [str(c).lower() for c in (self.cfg.get("channels") or []) if str(c).strip()]
        if not wanted:
            return True
        name = (getattr(message.channel, "name", "") or "").lower()
        cid = str(getattr(message.channel, "id", "")).lower()
        return any(w == cid or w in name for w in wanted)

    async def cog_check(self, ctx) -> bool:
        return self.allowed(ctx.message)

    # -- talking -------------------------------------------------------------------------------------------------
    async def talk(self, message, text: str, mode: str) -> None:
        text = text.strip()
        if not text:
            return
        s = brain.Settings.read(self.cfg)
        author = message.author
        name = getattr(author, "display_name", None) or getattr(author, "name", None) or "someone"
        guild = getattr(message, "guild", None)
        prefix = str(getattr(self.bot.config, "prefix", "!") or "!")
        if mode == "video":
            why = video.ready(self.sam)
            if why:  # she still answers, in text, and says why
                mode = "text"
                note = f"\n\n-# No video: {why}." + (" An owner can run `!vecvoice`." if "SAM" in why else "")
            else:
                note = ""
        else:
            note = ""
        async with message.channel.typing():
            try:
                answer = await self.brain.answer(s, user=str(author.id), name=name, text=text, mode=mode,
                                                 channel=str(message.channel.id),
                                                 community=getattr(guild, "name", "") or "", prefix=prefix)
            except brain.ChatError as e:
                self.last_error = str(e)
                log.warning("Vectoria: the model didn't answer: %s", e)
                await message.reply("My brain's offline right now (I can't reach the model). Try again in a bit.")
                return
            if not answer:
                return
            sent = None
            if mode == "video":
                await self.react(message)
                try:
                    async with self.renders:
                        clip = await asyncio.to_thread(
                            video.render, video.trim_spoken(answer, int(self.cfg.get("max_sentences", 3))),
                            sam=self.sam, data_dir=self.data_dir, opts=self.video_opts())
                    sent = await message.reply(file=vector.File(clip, filename="vectoria.mp4"))
                except video.RenderError as e:
                    self.last_error = str(e)
                    log.warning("Vectoria: no video for this reply: %s", e)
                    mode = "text"
            if sent is None:
                sent = await message.reply((answer + note)[:MAX_TEXT])
        if sent is not None and getattr(sent, "id", None):
            self.store.log_reply(str(sent.id), str(author.id), text, answer, mode, str(message.channel.id))
            for emoji in THUMBS:
                try:
                    await sent.add_reaction(emoji)
                except Exception as e:  # noqa: BLE001 - reactions are a nicety
                    log.debug("Vectoria couldn't add %s: %s", emoji, e)

    def video_opts(self) -> dict:
        c = self.cfg
        return {k: c.get(k) for k in ("pitch", "speed", "mouth", "throat", "video_size", "vhs", "vhs_strength",
                                      "max_kb", "subtitles") if c.get(k) is not None}

    async def react(self, message) -> None:
        try:
            await message.add_reaction("💻")  # "on it": the video takes a few seconds
        except Exception:  # noqa: BLE001
            pass

    # -- commands ------------------------------------------------------------------------------------------------
    @commands.command(name="vec", help="Ask Vectoria (answers in text)")
    async def vec(self, ctx, *, text: str = ""):
        if not text:
            return await ctx.reply("Ask me something! `!vec <question>` for text, `!vectoria <question>` for video.")
        await self.talk(ctx.message, text, "text")

    @commands.command(name="vectoria", help="Ask Vectoria (answers in a talking video)")
    async def vectoria(self, ctx, *, text: str = ""):
        if not text:
            return await ctx.reply("Say something! `!vectoria <question>` for video, `!vec <question>` for text.")
        await self.talk(ctx.message, text, "video")

    @commands.command(name="vecmemory", help="What Vectoria remembers about you")
    async def vecmemory(self, ctx):
        summary, turns = self.store.context(str(ctx.author.id))
        talks = sum(1 for t in turns if t["role"] == "user")
        if summary:
            text = f"What I remember about you:\n> {summary}"
            if talks:
                text += f"\n-# Plus our last {talks} exchange{'s' if talks != 1 else ''}, word for word."
        elif talks:
            last = next(t["content"] for t in reversed(turns) if t["role"] == "user")
            every = int(self.cfg.get("compact_after", 8))
            text = (f"We've talked {talks} time{'s' if talks != 1 else ''}; I remember all of it, most recently "
                    f"“{last[:120]}”. After {every} exchanges I write it down as notes about you. "
                    "`!vecforget` makes me forget.")
        else:
            text = "Nothing yet. Talk to me!"
        await ctx.reply(text)

    @commands.command(name="vecforget", help="Make Vectoria forget your conversation")
    async def vecforget(self, ctx):
        n = self.store.forget(str(ctx.author.id))
        await ctx.reply("Memory wiped. Hello, stranger." if n else "We haven't even talked yet.")

    @commands.command(name="vecface", help="Show Vectoria's sprite")
    async def vecface(self, ctx):
        await ctx.reply(file=vector.File(await asyncio.to_thread(video.still_png), filename="vectoria.png"))

    @commands.command(name="vecprofile", help="Owners: give the bot Vectoria's name, about text and picture")
    async def vecprofile(self, ctx):
        if not await self.is_owner(ctx):
            return await ctx.reply("Only the bot's owners can change its profile.")
        try:
            await self.become_vectoria(str(getattr(ctx.author, "npub", "") or ctx.author.id))
        except Exception as e:  # noqa: BLE001
            return await ctx.reply(f"❌ Couldn't change the profile: {e}")
        await ctx.reply("✅ I'm Vectoria now: name, about text and picture. It can take a minute to show everywhere.")

    def is_vectoria(self) -> bool:
        me = self.bot.user
        name = getattr(getattr(me, "_profile", None), "name", None) or getattr(me, "name", "")
        return name == PROFILE_NAME

    async def become_vectoria(self, by: str) -> None:
        """Her name, about text and picture on the bot's account. Through Vectiq's profile settings when it has
        them, so the profile stays the same after restarts and on other computers; directly otherwise."""
        picture = await asyncio.to_thread(video.avatar_png, self.data_dir)
        if hasattr(self.bot, "change_settings"):
            await self.bot.change_settings({"profile.name": PROFILE_NAME, "profile.about": PROFILE_ABOUT,
                                            "profile.avatar": picture}, by)
            if hasattr(self.bot, "apply_profile"):
                await self.bot.apply_profile()
        else:
            await self.bot.user.edit(username=PROFILE_NAME, about=PROFILE_ABOUT, avatar=picture)

    @commands.command(name="vecvoice", help="Owners: build Vectoria's voice (SAM) on this computer")
    async def vecvoice(self, ctx):
        if not await self.is_owner(ctx):
            return await ctx.reply("Only the bot's owners can build my voice.")
        if self.sam:
            return await ctx.reply(f"✅ My voice is ready ({self.sam}).")
        await ctx.reply("Building my voice: cloning SAM and compiling it. This takes a moment.")
        try:
            path = await self.build_voice()
        except video.RenderError as e:
            return await ctx.reply(f"❌ Couldn't build SAM: {e}")
        await ctx.reply(f"✅ Voice ready ({path}). Try `!vectoria hello`.")

    async def is_owner(self, ctx) -> bool:
        owners = [str(o).lower() for o in (getattr(self.bot.config, "owners", None) or [])]
        me = str(getattr(ctx.author, "npub", "") or ctx.author.id).lower()
        if owners:
            return me in owners
        guild = getattr(ctx, "guild", None)
        return guild is not None and str(getattr(guild, "owner_id", "")).lower() == me

    async def build_voice(self) -> str:
        if self.building is None or self.building.done():
            self.building = asyncio.ensure_future(asyncio.to_thread(video.build_sam, self.data_dir))
        return await self.building

    # -- replies to her, and votes -----------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message):
        if getattr(message.author, "bot", False) or message.author == self.bot.user:
            return
        ref = getattr(message, "reference", None)
        text = (message.content or "").strip()
        if ref is None or not text or not self.allowed(message):
            return
        prefix = str(getattr(self.bot.config, "prefix", "!") or "!")
        if text.startswith(prefix):
            return
        mode = self.store.reply_mode(str(getattr(ref, "message_id", "") or ""))
        if mode:
            await self.talk(message, text, mode)

    def _vote(self, payload):
        me = str(getattr(self.bot.user, "id", ""))
        emoji = str(getattr(payload, "emoji", ""))
        if emoji not in THUMBS or str(payload.user_id) == me:
            return None
        return THUMBS[emoji]

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        rating = self._vote(payload)
        if rating is not None:
            self.store.rate(str(payload.message_id), str(payload.user_id), rating)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        rating = self._vote(payload)
        if rating is not None:
            self.store.unrate(str(payload.message_id), str(payload.user_id), rating)

    # -- dashboard -----------------------------------------------------------------------------------------------
    async def dashboard_panel(self, guild, viewer):
        s = brain.Settings.read(self.cfg)
        st = await asyncio.to_thread(self.store.stats)
        why = video.ready(self.sam)
        items = [
            {"label": "Model", "value": s.model, "tone": "green" if s.key or "ollama.com" not in s.host else "red"},
            {"label": "API key", "value": "set" if s.key else "missing",
             "tone": "green" if s.key else ("amber" if "ollama.com" not in s.host else "red")},
            {"label": "Video", "value": "ready" if not why else "text only", "tone": "green" if not why else "amber"},
            {"label": "People", "value": st["people"]},
            {"label": "Answers", "value": f"{st['text']} text · {st['video']} video"},
            {"label": "Votes", "value": f"👍 {st['up']}  👎 {st['down']}"},
        ]
        sections = [{"type": "status", "items": items}]
        notes = []
        if why:
            notes.append(f"No videos yet: {why}." + (" Press “Build her voice” below." if "SAM" in why else ""))
        if not s.key and "ollama.com" in s.host:
            key_env = self.cfg.get("api_key_env") or "OLLAMA_API_KEY"
            notes.append(f"Put an Ollama API key in the bot's .env as {key_env} (ollama.com → Settings → Keys).")
        if self.last_error:
            notes.append(f"Last problem: {self.last_error}")
        if notes:
            sections.append({"type": "text", "text": "\n\n".join(notes)})
        recent = await asyncio.to_thread(self.store.recent)
        if recent:
            sections.append({"type": "list", "title": "Latest questions", "items": [
                {"title": r["prompt"][:120], "detail": time.strftime("%b %d %H:%M", time.localtime(r["at"])),
                 "tag": r["mode"] + (f" {'+' if r['score'] > 0 else ''}{r['score']}" if r["score"] else "")}
                for r in recent]})
        if not self.is_vectoria():
            sections.insert(1, {"type": "text", "text": "The bot isn't called Vectoria yet. “Make the bot Vectoria” "
                                "gives its Vector account her name, about text and picture."})
        sections.append({"type": "actions", "items": [
            *([{"id": "become", "label": "Make the bot Vectoria", "kind": "primary", "owner": True}]
              if not self.is_vectoria() else []),
            *([{"id": "build_voice", "label": "Build her voice", "owner": True}] if not self.sam else []),
            {"id": "forget_all", "label": "Forget everyone", "kind": "danger", "owner": True,
             "confirm": "Clear every conversation and memory? Votes are kept."},
        ]})
        return {"title": "Vectoria", "refresh": 15, "sections": sections}

    async def dashboard_action(self, action, guild, viewer, data):
        if action == "build_voice":
            try:
                return f"Voice ready: {await self.build_voice()}"
            except video.RenderError as e:
                raise RuntimeError(f"Couldn't build SAM: {e}") from e
        if action == "become":
            await self.become_vectoria(viewer or "dashboard")
            return "Done: the bot is Vectoria now. It can take a minute to show everywhere."
        if action == "forget_all":
            await asyncio.to_thread(self.store.forget_all)
            return "Every conversation and memory is cleared."
        raise RuntimeError(f"unknown action {action}")


async def setup(bot):
    await bot.add_cog(Vectoria(bot))
