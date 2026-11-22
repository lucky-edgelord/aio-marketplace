"""Kitsune in chat: ``!kit`` answers in text, ``!kitsune`` in a short lip-synced video of her avatar.

This is the Kitsune bot's own pipeline (Ollama chat, per-person memory with compaction, NovelAI voice, mood, the
lip-sync and subtitle renderer), bundled next to this file and driven from a Vectiq cog. The one addition is the text
mode. Replies to her answers carry on in the same mode, every answer gets 👍/👎, and in the channels listed under
"Chat in these channels" she answers every message, like she does in the Kitsune bot's chat channel.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import sqlite3
import time
import urllib.request
from pathlib import Path

import vector
from vector.ext import commands

log = logging.getLogger("vectiq.kitsune")
HERE = Path(__file__).resolve().parent
THUMBS = {"👍": 1, "👎": -1}
MOODS = ("happy", "mad", "neutral", "sad", "shy")
FRAMES = ("open_closed", "open_talk", "blink_closed", "blink_talk")
DEFAULT_SPRITES = "https://raw.githubusercontent.com/lucky-edgelord/aio-marketplace/main/modules/media/kitsune/sprites/"
MOOD_EMOJI = {"happy": "😄", "mad": "😠", "neutral": "😐", "sad": "😢", "shy": "😳"}
PROFILE_NAME = "Kitsune"
PROFILE_ABOUT = "🦊 The Fox Mafia's anime fox-girl. Talk to me with !kit (text) or !kitsune (a short video)."
MAX_TEXT = 3800
TEXT_STYLE = (
    "How you answer now: your reply is posted as a chat message, so talk the way you would in a chat: a few "
    "sentences, at most about 100 words unless they ask for more. Light markdown is fine. No stage directions and "
    "no *actions*. Stay in character."
)


def missing_packages() -> list[str]:
    """What the avatar pipeline needs that this Python doesn't have (the bot's own install: ``pip install ...``)."""
    out = []
    for name in ("httpx", "numpy"):
        try:
            __import__(name)
        except ImportError:
            out.append(name)
    return out


class Modes:
    """Which mode (text or video) each of her answers was, so a reply to it carries on the same way."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS reply_modes (message_id TEXT PRIMARY KEY, mode TEXT NOT NULL)")
        self._db.commit()

    def set(self, message_id: str, mode: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO reply_modes VALUES (?, ?)", (message_id, mode))
        self._db.commit()

    def get(self, message_id: str) -> str | None:
        row = self._db.execute("SELECT mode FROM reply_modes WHERE message_id=?", (message_id,)).fetchone()
        return row[0] if row else None

    def stats(self) -> dict:
        one = lambda q: (self._db.execute(q).fetchone() or [0])[0] or 0  # noqa: E731
        try:
            return {
                "people": one("SELECT COUNT(DISTINCT user) FROM turns"),
                "text": one("SELECT COUNT(*) FROM reply_modes WHERE mode='text'"),
                "video": one("SELECT COUNT(*) FROM reply_modes WHERE mode='video'"),
                "up": one("SELECT COUNT(*) FROM feedback WHERE rating>0"),
                "down": one("SELECT COUNT(*) FROM feedback WHERE rating<0"),
            }
        except sqlite3.Error:
            return {"people": 0, "text": 0, "video": 0, "up": 0, "down": 0}

    def recent(self, n: int = 8) -> list:
        try:
            rows = self._db.execute(
                "SELECT r.prompt, r.mood, r.at, m.mode, COALESCE((SELECT SUM(rating) FROM feedback f "
                "WHERE f.message_id=r.message_id), 0) FROM replies r JOIN reply_modes m USING (message_id) "
                "ORDER BY r.at DESC LIMIT ?", (n,)).fetchall()
        except sqlite3.Error:
            return []
        return [{"prompt": p, "mood": mood, "at": at, "mode": mode, "score": int(score)}
                for p, mood, at, mode, score in rows]

    def close(self) -> None:
        self._db.close()


class Kitsune(commands.Cog, name="Kitsune"):
    dashboard_page = {"label": "Kitsune", "icon": "🦊", "scope": "bot", "owner_only": True}

    def __init__(self, bot):
        self.bot = bot
        self.data = Path(str(getattr(bot.config, "data_dir", None) or "data")) / "kitsune"
        self.pipe = None
        self.pipe_key = None
        self.sprites = None
        self.modes: Modes | None = None
        self.last_error = ""

    async def cog_unload(self):
        if self.pipe is not None:
            await self.pipe.drain()
            self.pipe.store.close()
            for svc in (self.pipe.chat, self.pipe.speech):
                close = getattr(svc, "aclose", None)
                if close:
                    await close()
        if self.modes is not None:
            self.modes.close()

    # -- settings ------------------------------------------------------------------------------------------------
    @property
    def cfg(self) -> dict:
        return self.bot.config.get("kitsune", {}) or {}

    def env(self, key_setting: str, default: str) -> str:
        return os.environ.get(str(self.cfg.get(key_setting) or default), "")

    def listed(self, key: str) -> list[str]:
        return [str(c).lower() for c in (self.cfg.get(key) or []) if str(c).strip()]

    @staticmethod
    def in_channels(message, wanted: list[str]) -> bool:
        name = (getattr(message.channel, "name", "") or "").lower()
        cid = str(getattr(message.channel, "id", "")).lower()
        return any(w == cid or w in name for w in wanted)

    def allowed(self, message) -> bool:
        guild = getattr(message, "guild", None)
        if guild is None:
            return bool(self.cfg.get("allow_dms", False))
        if hasattr(self.bot, "serves") and not self.bot.serves(guild):
            return False
        wanted = self.listed("channels")
        return not wanted or self.in_channels(message, wanted)

    async def is_owner(self, ctx) -> bool:
        owners = [str(o).lower() for o in (getattr(self.bot.config, "owners", None) or [])]
        me = str(getattr(ctx.author, "npub", "") or ctx.author.id).lower()
        if owners:
            return me in owners
        guild = getattr(ctx, "guild", None)
        return guild is not None and str(getattr(guild, "owner_id", "")).lower() == me

    async def cog_check(self, ctx) -> bool:
        return self.allowed(ctx.message)

    # -- her parts, built on first use -----------------------------------------------------------------------------
    def sprite_dir(self) -> Path:
        """Her sprites as files in the data folder. Fetched once from the sprite host in the settings (this
        marketplace by default; a folder path works too) and kept, so the module itself stays small."""
        root = self.data / "sprites"
        base = str(self.cfg.get("sprites_url") or DEFAULT_SPRITES).strip()
        for mood in MOODS:
            for name in FRAMES:
                dest = root / mood / f"{name}.webp"
                if dest.is_file() and dest.stat().st_size:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if base.startswith(("http://", "https://")):
                        req = urllib.request.Request(f"{base.rstrip('/')}/{mood}/{name}.webp",
                                                     headers={"User-Agent": "vectiq-kitsune"})
                        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - the owner sets the address
                            data = r.read(5_000_000)
                    else:
                        data = (Path(base).expanduser() / mood / f"{name}.webp").read_bytes()
                except OSError as e:
                    raise RuntimeError(f"couldn't get her sprites from {base} ({mood}/{name}: {e})") from e
                tmp = dest.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(dest)
        return root

    def avatar_png(self) -> str:
        path = self.data / "avatar.png"
        if not path.is_file():
            from PIL import Image
            self.data.mkdir(parents=True, exist_ok=True)
            pic = json.loads((HERE / "assets.json").read_text("utf-8"))["avatar"]
            Image.open(io.BytesIO(base64.b64decode(pic))).convert("RGB").save(path, format="PNG")
        return str(path.resolve())

    def parts(self):
        """The pipeline, built once and rebuilt when the settings behind it change."""
        c = self.cfg
        key = (c.get("ollama_host"), c.get("model"), c.get("api_key_env"), c.get("novelai_token_env"),
               c.get("voice"), c.get("emotion"), c.get("video_size"), c.get("lipsync"), c.get("subtitles"),
               c.get("compact_after"), c.get("keep_recent"), self.env("novelai_token_env", "NOVELAI_TOKEN"),
               self.env("api_key_env", "OLLAMA_API_KEY"))
        if self.pipe is not None and key == self.pipe_key:
            return self.pipe
        if missing_packages():
            raise RuntimeError("needs " + " and ".join(missing_packages()) + " installed in the bot's Python")
        from .avatar import AvatarRenderer, SpriteBank
        from .pipeline import ReplyPipeline
        from .providers.emotion import DistilBertEmotion, KeywordEmotion
        from .providers.llm import OllamaChat
        from .providers.speech import NovelAISpeech
        from .storage import ConversationStore

        token = self.env("novelai_token_env", "NOVELAI_TOKEN")
        store = self.pipe.store if self.pipe is not None else ConversationStore(str(self.data / "kitsune.db"))
        size = max(128, min(int(c.get("video_size", 512)), 512)) // 2 * 2
        speech = NovelAISpeech(token, voice_seed=str(c.get("voice") or "Aurae")) if token else None
        self.sprites = SpriteBank(str(self.sprite_dir()), size=size)
        emotion = DistilBertEmotion() if c.get("emotion") == "distilbert" else KeywordEmotion()
        self.pipe = ReplyPipeline(
            persona=(HERE / "persona" / "kitsune.md").read_text("utf-8").strip(),
            chat=OllamaChat(str(c.get("ollama_host") or "https://ollama.com").rstrip("/"),
                            str(c.get("model") or "gpt-oss:120b"), api_key=self.env("api_key_env", "OLLAMA_API_KEY")),
            emotion=emotion, store=store, speech=speech,
            avatar=AvatarRenderer(self.sprites, lipsync=str(c.get("lipsync") or "smooth")) if speech else None,
            compact_after=max(1, int(c.get("compact_after", 8))), keep_recent=max(0, int(c.get("keep_recent", 2))),
            subtitles=bool(c.get("subtitles", True)))
        self.pipe_key = key
        if self.modes is None:
            self.modes = Modes(str(self.data / "kitsune.db"))
        return self.pipe

    async def ready_parts(self):
        """``parts()`` off the event loop: the first call may download her sprites."""
        return await asyncio.to_thread(self.parts)

    def video_problem(self) -> str:
        """Why a video can't be made right now ("" when it can)."""
        import shutil
        if missing_packages():
            return "needs " + " and ".join(missing_packages()) + " installed in the bot's Python"
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            return "ffmpeg isn't installed on the bot's computer"
        if not self.env("novelai_token_env", "NOVELAI_TOKEN"):
            return "no NovelAI token for her voice"
        return ""

    # -- talking -------------------------------------------------------------------------------------------------
    def said_before(self, message) -> str | None:
        """What she said in the message this one replies to ('' when it was hers but is unknown)."""
        ref = getattr(message, "reference", None)
        if ref is None or not getattr(ref, "message_id", None) or self.pipe is None:
            return None
        return self.pipe.store.reply_text(str(ref.message_id))

    async def talk(self, message, text: str, mode: str) -> None:
        text = text.strip()
        if not text:
            return
        try:
            pipe = await self.ready_parts()
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            log.warning("Kitsune isn't ready: %s", e)
            await message.reply(f"🦊 I'm not ready yet: {e}.")
            return
        said = self.said_before(message)
        if said:
            text = f'(Replying to what you said: "{said[:300]}")\n{text}'
        author = message.author
        name = getattr(author, "display_name", None) or getattr(author, "name", None) or "someone"
        note = ""
        if mode == "video":
            why = self.video_problem()
            if why:  # she still answers, in text, and says why
                mode, note = "text", f"\n\n-# No video: {why}."
        react = bool(self.cfg.get("react_mood", True))

        async def on_mood(mood) -> None:  # her mood, as a reaction on the message she's answering
            if react:
                await message.add_reaction(mood.emoji)

        async with message.channel.typing():
            try:
                if mode == "video":
                    reply = await pipe.reply(str(author.id), name, text, channel=str(message.channel.id), video=True,
                                             on_mood=on_mood)
                    answer, mood, clip, warning = reply.text, reply.mood, reply.video, reply.warning
                else:
                    answer = await pipe.think(str(author.id), name, text, channel=str(message.channel.id),
                                              style=TEXT_STYLE)
                    mood, clip, warning = await pipe.emotion.detect(answer) if answer else None, None, None
                    if answer and mood is not None:
                        try:
                            await on_mood(mood)
                        except Exception as e:  # noqa: BLE001 - a reaction is a nicety
                            log.debug("couldn't react: %s", e)
            except Exception as e:  # noqa: BLE001 - ChatError and friends
                self.last_error = str(e)
                log.warning("Kitsune: the model didn't answer: %s", e)
                await message.reply("🦊 My brain's offline right now (I can't reach the model). Try again in a bit.")
                return
            if not answer:
                return
            if warning:
                self.last_error = warning
                note = f"\n\n-# No video: {warning[:160]}."
            if clip:  # the words are in the subtitles, so the video goes alone
                sent = await message.reply(file=vector.File(clip, filename="kitsune.mp4"))
            else:
                sent = await message.reply((answer + note)[:MAX_TEXT])
                mode = "text"
        if sent is not None and getattr(sent, "id", None):
            pipe.store.log_reply(str(sent.id), str(author.id), text, answer, getattr(mood, "value", "neutral"),
                                 channel=str(message.channel.id))
            self.modes.set(str(sent.id), mode)
            for emoji in THUMBS:
                try:
                    await sent.add_reaction(emoji)
                except Exception as e:  # noqa: BLE001
                    log.debug("couldn't add %s: %s", emoji, e)

    # -- listeners -----------------------------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message):
        if getattr(message.author, "bot", False) or message.author == self.bot.user:
            return
        text = (message.content or "").strip()
        if not text or not self.allowed(message):
            return
        prefix = str(getattr(self.bot.config, "prefix", "!") or "!")
        if text.startswith(prefix):
            return
        ref = getattr(message, "reference", None)
        if ref is not None and getattr(ref, "message_id", None) and self.modes is not None:
            mode = self.modes.get(str(ref.message_id))
            if mode:  # a reply to one of her answers carries on the same way
                return await self.talk(message, text, mode)
        chat = self.listed("chat_channels")
        if chat and self.in_channels(message, chat):
            await self.talk(message, text, str(self.cfg.get("chat_mode") or "video"))

    def _vote(self, payload):
        me = str(getattr(self.bot.user, "id", ""))
        emoji = str(getattr(payload, "emoji", ""))
        if emoji not in THUMBS or str(payload.user_id) == me:
            return None
        return THUMBS[emoji]

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        rating = self._vote(payload)
        if rating is not None and self.pipe is not None:
            self.pipe.store.rate(str(payload.message_id), str(payload.user_id), rating)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        rating = self._vote(payload)
        if rating is not None and self.pipe is not None:
            self.pipe.store.unrate(str(payload.message_id), str(payload.user_id), rating)

    # -- commands ------------------------------------------------------------------------------------------------
    @commands.command(name="kit", help="Talk to Kitsune (she answers in text)")
    async def kit(self, ctx, *, text: str = ""):
        if not text:
            return await ctx.reply("🦊 Hm? Say something, kit. `!kit <message>` for text, `!kitsune <message>` for video.")
        await self.talk(ctx.message, text, "text")

    @commands.command(name="kitsune", help="Talk to Kitsune (she answers in a talking video)")
    async def kitsune(self, ctx, *, text: str = ""):
        if not text:
            return await ctx.reply("🦊 Hm? Say something, kit. `!kitsune <message>` for video, `!kit <message>` for text.")
        await self.talk(ctx.message, text, "video")

    @commands.command(name="kitmemory", help="What Kitsune remembers about you")
    async def kitmemory(self, ctx):
        try:
            pipe = await self.ready_parts()
        except Exception as e:  # noqa: BLE001
            return await ctx.reply(f"🦊 I'm not ready yet: {e}.")
        summary = pipe.store.memory(str(ctx.author.id))
        if summary:
            return await ctx.reply(f"🦊 What I remember about you:\n> {summary}"[:MAX_TEXT])
        n = pipe.store.context(str(ctx.author.id)).exchanges
        await ctx.reply(f"🦊 I've kept our last {n} exchange(s) in mind, but haven't written them into my notes yet."
                        if n else "🦊 Nothing yet, kit. Talk to me!")

    @commands.command(name="kitforget", help="Make Kitsune forget you")
    async def kitforget(self, ctx):
        try:
            pipe = await self.ready_parts()
        except Exception as e:  # noqa: BLE001
            return await ctx.reply(f"🦊 I'm not ready yet: {e}.")
        n = pipe.store.forget(str(ctx.author.id))
        await ctx.reply("🦊 Forgotten. Who are you again?" if n else "🦊 We haven't even talked yet, kit.")

    @commands.command(name="kitface", help="Show one of Kitsune's expressions: !kitface [happy|mad|neutral|sad|shy]")
    async def kitface(self, ctx, mood: str = "happy"):
        try:
            await self.ready_parts()
        except Exception as e:  # noqa: BLE001
            return await ctx.reply(f"🦊 I'm not ready yet: {e}.")
        from .moods import Mood
        m = Mood.parse(mood, Mood.HAPPY)
        png = await asyncio.to_thread(self.sprites.still_png, m)
        await ctx.reply(f"-# {m.value}", file=vector.File(png, filename=f"{m.value}.png"))

    def is_kitsune(self) -> bool:
        name = str(self.bot.config.get("profile.name", "") or "")
        return name.strip().lower() == PROFILE_NAME.lower()

    async def become_kitsune(self, by: str) -> None:
        """Her name, about text and picture on the bot's account, through Vectiq's profile settings so they stick."""
        picture = await asyncio.to_thread(self.avatar_png)
        if hasattr(self.bot, "change_settings"):
            await self.bot.change_settings({"profile.name": PROFILE_NAME, "profile.about": PROFILE_ABOUT,
                                            "profile.avatar": picture}, by)
            if hasattr(self.bot, "apply_profile"):
                await self.bot.apply_profile()
        else:
            await self.bot.user.edit(username=PROFILE_NAME, about=PROFILE_ABOUT, avatar=picture)

    @commands.command(name="kitprofile", help="Owners: give the bot Kitsune's name, about text and picture")
    async def kitprofile(self, ctx):
        if not await self.is_owner(ctx):
            return await ctx.reply("Only the bot's owners can change the bot's profile.")
        try:
            await self.become_kitsune(str(ctx.author.id))
        except Exception as e:  # noqa: BLE001
            return await ctx.reply(f"❌ Couldn't change the profile: {e}")
        await ctx.reply("🦊 Done, I'm Kitsune now. It can take a minute to show everywhere.")

    # -- dashboard -----------------------------------------------------------------------------------------------
    async def dashboard_panel(self, guild, viewer):
        c = self.cfg
        key = self.env("api_key_env", "OLLAMA_API_KEY")
        host = str(c.get("ollama_host") or "https://ollama.com")
        why = self.video_problem()
        if self.modes is None:
            self.data.mkdir(parents=True, exist_ok=True)
            self.modes = Modes(str(self.data / "kitsune.db"))
        st = await asyncio.to_thread(self.modes.stats)
        items = [
            {"label": "Model", "value": str(c.get("model") or "gpt-oss:120b"),
             "tone": "green" if key or "ollama.com" not in host else "red"},
            {"label": "API key", "value": "set" if key else "missing",
             "tone": "green" if key else ("amber" if "ollama.com" not in host else "red")},
            {"label": "Video", "value": "ready" if not why else "text only", "tone": "green" if not why else "amber"},
            {"label": "People", "value": st["people"]},
            {"label": "Answers", "value": f"{st['text']} text · {st['video']} video"},
            {"label": "Votes", "value": f"👍 {st['up']}  👎 {st['down']}"},
        ]
        sections = [{"type": "status", "items": items}]
        notes = []
        if why:
            notes.append(f"No videos yet: {why}.")
        if not key and "ollama.com" in host:
            notes.append(f"Put an Ollama API key in the bot's .env as {c.get('api_key_env') or 'OLLAMA_API_KEY'}.")
        if self.last_error:
            notes.append(f"Last problem: {self.last_error}")
        if notes:
            sections.append({"type": "text", "text": "\n\n".join(notes)})
        recent = await asyncio.to_thread(self.modes.recent)
        if recent:
            sections.append({"type": "list", "title": "Latest chats", "items": [
                {"title": r["prompt"][:120], "detail": time.strftime("%b %d %H:%M", time.localtime(r["at"])),
                 "tag": f"{r['mode']} · {r['mood']}" + (f" {'+' if r['score'] > 0 else ''}{r['score']}" if r["score"] else "")}
                for r in recent]})
        if not self.is_kitsune():
            sections.insert(1, {"type": "text", "text": "The bot isn't called Kitsune yet. “Make the bot Kitsune” gives "
                                "its Vector account her name, about text and picture."})
        sections.append({"type": "actions", "items": [
            *([{"id": "become", "label": "Make the bot Kitsune", "kind": "primary", "owner": True}]
              if not self.is_kitsune() else []),
            {"id": "forget_all", "label": "Forget everyone", "kind": "danger", "owner": True,
             "confirm": "Clear every conversation and memory? Votes are kept."}]})
        return {"title": "Kitsune", "refresh": 15, "sections": sections}

    async def dashboard_action(self, action, guild, viewer, data):
        if action == "become":
            await self.become_kitsune(viewer or "dashboard")
            return "Done: the bot is Kitsune now. It can take a minute to show everywhere."
        if action == "forget_all":
            pipe = await self.ready_parts()
            await asyncio.to_thread(pipe.store._db.executescript, "DELETE FROM turns; DELETE FROM memories;")
            return "Every conversation and memory is cleared."
        raise RuntimeError(f"unknown action {action}")


async def setup(bot):
    await bot.add_cog(Kitsune(bot))
