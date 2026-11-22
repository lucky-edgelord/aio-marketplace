"""Visual Novel: chat with a character who answers as a visual-novel screen (her expression, where you both are,
her line in the dialogue box). Rewritten from atorsvn/visual_novel_chat_poc for Vectiq: one scene per person instead
of one for everyone, every place and expression used, pictures made in memory, and reactions in place of buttons."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import urllib.request
from pathlib import Path

import vector
from vector.ext import commands

from . import scene, story
from .store import Store

log = logging.getLogger("vectiq.visualnovel")
DEFAULT_ASSETS = "https://raw.githubusercontent.com/lucky-edgelord/aio-marketplace/main/modules/media/visualnovel/assets/"
ASSET_FILES = (["OpenSansEmoji.ttf", "ui/chat.webp"] + [f"backgrounds/{p}.webp" for p in scene.PLACES]
               + [f"sprites/{m}.webp" for m in scene.MOODS])
PREV, NEXT, MAP = "◀️", "▶️", "🗺️"
NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]
DEFAULT_PERSONA = ("Gwen is a sweet, playful girl with silver hair and red glasses. She has a soft spot for the person "
                   "she's talking with and calls them Senpai. She gets flustered easily, but she's clever and teases "
                   "back, loves autumn, books and quiet walks in the park.")


class VisualNovel(commands.Cog, name="Visual Novel"):
    dashboard_page = {"label": "Visual Novel", "icon": "🎀", "scope": "bot", "owner_only": True}

    def __init__(self, bot):
        self.bot = bot
        self.data = Path(str(getattr(bot.config, "data_dir", None) or "data")) / "visualnovel"
        self.store = Store(str(self.data / "vn.db"))
        self._art: scene.Art | None = None
        self.busy: set[str] = set()
        self.last_error = ""

    async def cog_unload(self):
        self.store.close()

    # -- settings ------------------------------------------------------------------------------------------------
    @property
    def cfg(self) -> dict:
        return self.bot.config.get("visualnovel", {}) or {}

    @property
    def name(self) -> str:
        return str(self.cfg.get("character_name") or "Gwen")

    @property
    def prefix(self) -> str:
        return str(getattr(self.bot.config, "prefix", "!") or "!")

    @property
    def start_place(self) -> str:
        p = str(self.cfg.get("start_place") or "bridge").lower()
        return p if p in scene.PLACES else "bridge"

    def allowed(self, message) -> bool:
        guild = getattr(message, "guild", None)
        if guild is None:
            return bool(self.cfg.get("allow_dms", True))
        if hasattr(self.bot, "serves") and not self.bot.serves(guild):
            return False
        return True

    def chat_channel(self, message) -> bool:
        wanted = [str(c).lower() for c in (self.cfg.get("channels") or []) if str(c).strip()]
        if not wanted or getattr(message, "guild", None) is None:
            return False
        name = (getattr(message.channel, "name", "") or "").lower()
        cid = str(getattr(message.channel, "id", "")).lower()
        return any(w == cid or w in name for w in wanted)

    async def cog_check(self, ctx) -> bool:
        return self.allowed(ctx.message)

    @staticmethod
    def key_of(message) -> str:
        g = getattr(message, "guild", None)
        return f"{getattr(g, 'id', None) or 'dm'}|{message.author.id}"

    # -- art -------------------------------------------------------------------------------------------------------
    def art(self) -> scene.Art:
        """Pictures from a local folder, or downloaded once from the marketplace into the data folder."""
        if self._art is None:
            src = str(self.cfg.get("assets_url") or DEFAULT_ASSETS)
            if not src.startswith("http"):
                self._art = scene.Art(Path(src))
            else:
                dest = self.data / "assets"
                for rel in ASSET_FILES:
                    path = dest / rel
                    if not path.is_file():
                        path.parent.mkdir(parents=True, exist_ok=True)
                        req = urllib.request.Request(src.rstrip("/") + "/" + rel, headers={"User-Agent": "vectiq-vn"})
                        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - owner-chosen host
                            path.write_bytes(r.read(3_000_000))
                self._art = scene.Art(dest)
        return self._art

    # -- the model -----------------------------------------------------------------------------------------------
    def ollama(self, messages: list[dict]) -> str:
        """Blocking chat call to Ollama (cloud or local)."""
        host = str(self.cfg.get("ollama_host") or "https://ollama.com").rstrip("/")
        key = os.environ.get(str(self.cfg.get("api_key_env") or "OLLAMA_API_KEY"), "")
        body = {"model": str(self.cfg.get("model") or "gpt-oss:120b"), "messages": messages, "stream": False,
                "options": {"temperature": float(self.cfg.get("temperature", 0.8))}}
        headers = {"Content-Type": "application/json", "User-Agent": "vectiq-visualnovel"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(host + "/api/chat", data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=int(self.cfg.get("timeout", 90))) as r:  # noqa: S310
            data = json.loads(r.read())
        return ((data.get("message") or {}).get("content") or "").strip()

    # -- showing screens --------------------------------------------------------------------------------------------
    def status(self, s: dict) -> str:
        return f"{self.name}  ♥  {s['place'].capitalize()}"

    async def show(self, channel, key: str, user: str, s: dict, reply_to=None):
        art = await asyncio.to_thread(self.art)
        pages = s["pages"] or ["…"]
        page = max(0, min(s["page"], len(pages) - 1))
        data = await asyncio.to_thread(scene.screen, art, s["place"], s["mood"], pages[page], self.status(s),
                                       page + 1, len(pages), self.name)
        name = f"vn-{s['place']}-{s['mood']}.jpg"
        file = vector.File(io.BytesIO(data), filename=name, compress=False)
        card = vector.Embed(title=f"🎀 {self.name} · {s['place'].capitalize()}", description=" ".join(pages).replace("\n", " "))
        card.set_image(url=f"attachment://{name}")
        hints = (["◀️ ▶️ pages"] if len(pages) > 1 else []) + ["🗺️ map", "reply to keep talking"]
        card.set_footer(text=" · ".join(["Visual Novel"] + hints))
        sent = await (reply_to.reply(embed=card, file=file) if reply_to is not None else channel.send(embed=card, file=file))
        if sent is not None and getattr(sent, "id", None):
            self.store.mark(str(sent.id), key, "chat", user)
            marks = ([PREV] if page > 0 else []) + ([NEXT] if page < len(pages) - 1 else []) + [MAP]
            for e in marks:
                try:
                    await sent.add_reaction(e)
                except Exception:  # noqa: BLE001
                    break
        return sent

    async def show_map(self, channel, key: str, user: str, s: dict, reply_to=None):
        art = await asyncio.to_thread(self.art)
        data = await asyncio.to_thread(scene.map_screen, art, s["place"], "Where to? React with a number")
        file = vector.File(io.BytesIO(data), filename="vn-map.jpg", compress=False)
        card = vector.Embed(title="🗺️ Where to?", description=f"You're at the {s['place']}.")
        card.set_image(url="attachment://vn-map.jpg")
        card.set_footer(text=f"Visual Novel · react 1️⃣-{len(scene.PLACES)}️⃣ to go · or {self.prefix}vngo <place>")
        sent = await (reply_to.reply(embed=card, file=file) if reply_to is not None else channel.send(embed=card, file=file))
        if sent is not None and getattr(sent, "id", None):
            self.store.mark(str(sent.id), key, "map", user)
            for e in NUMBERS[:len(scene.PLACES)]:
                try:
                    await sent.add_reaction(e)
                except Exception:  # noqa: BLE001
                    break

    # -- talking -----------------------------------------------------------------------------------------------
    async def talk(self, message, text: str, *, channel=None, user_name: str | None = None):
        key, user = self.key_of(message), str(message.author.id)
        if key in self.busy:
            return
        self.busy.add(key)
        try:
            s = self.store.scene(key, self.start_place)
            who = user_name or getattr(message.author, "display_name", None) or getattr(message.author, "name", "Senpai")
            msgs = [{"role": "system", "content": story.system_prompt(self.name, str(self.cfg.get("persona") or DEFAULT_PERSONA),
                                                                      s["place"], who)}]
            msgs += self.store.history(key) + [{"role": "user", "content": text[:1500]}]
            ch = channel or message.channel
            try:
                async with ch.typing():
                    reply = await asyncio.to_thread(self.ollama, msgs)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                log.warning("visual novel: model call failed: %s", self.last_error)
                return await message.reply(f"❌ {self.name} is lost in thought: I couldn't reach the AI model. "
                                           "An owner can check the Visual Novel settings.")
            mood, line = story.split_mood(reply)
            if not line:
                line = "…"
            keep = int(self.cfg.get("history_messages", 20))
            self.store.add(key, "user", text[:1500], keep)
            self.store.add(key, "assistant", f"[{mood}] {line}", keep)
            art = await asyncio.to_thread(self.art)
            s.update(mood=mood, pages=scene.paginate(line, art), page=0)
            self.store.save_scene(key, s)
            await self.show(ch, key, user, s, reply_to=message)
        finally:
            self.busy.discard(key)

    @commands.command(name="vn", aliases=["novel"], help="Talk to the visual-novel character: !vn <message>")
    async def vn(self, ctx, *, text: str = ""):
        if not text.strip():
            key = self.key_of(ctx.message)
            s = self.store.scene(key, self.start_place)
            if not s["pages"]:
                return await self.talk(ctx.message, "(You walk up and say hello.)")
            return await self.show(ctx.channel, key, str(ctx.author.id), s, reply_to=ctx.message)
        await self.talk(ctx.message, text)

    @commands.command(name="vnmap", help="Show the map to go somewhere else")
    async def vnmap(self, ctx):
        key = self.key_of(ctx.message)
        await self.show_map(ctx.channel, key, str(ctx.author.id), self.store.scene(key, self.start_place),
                            reply_to=ctx.message)

    @commands.command(name="vngo", help="Go somewhere: !vngo <place or number>")
    async def vngo(self, ctx, *, where: str = ""):
        place = story.place_from(where)
        if not place:
            names = ", ".join(f"{i + 1}. {p}" for i, p in enumerate(scene.PLACES))
            return await ctx.reply(f"❌ Where to? {names}")
        await self._travel(ctx.message, None, place, None)

    async def _travel(self, message, key, place, channel):
        key = key or self.key_of(message)
        s = self.store.scene(key, self.start_place)
        if s["place"] == place:
            return await (channel or message.channel).send(f"❌ You're already at the {place}.")
        s["place"] = place
        self.store.save_scene(key, s)
        await self.talk(message, f"(We walk together to the {place}: {scene.PLACES[place]}.)", channel=channel)

    @commands.command(name="vnreset", help="Start over: she forgets your conversation")
    async def vnreset(self, ctx):
        self.store.forget(self.key_of(ctx.message))
        await ctx.reply(f"✅ {self.name} has forgotten your conversation. `{self.prefix}vn` to meet again.")

    @commands.command(name="vnface", help="Preview an expression: !vnface <mood>")
    async def vnface(self, ctx, mood: str = ""):
        if mood.lower() not in scene.MOODS:
            return await ctx.reply("❌ Expressions: " + ", ".join(scene.MOODS))
        key = self.key_of(ctx.message)
        s = self.store.scene(key, self.start_place)
        s = {**s, "mood": mood.lower(), "pages": [f"(This is my {mood.lower()} face.)"], "page": 0}
        await self.show(ctx.channel, key, str(ctx.author.id), s, reply_to=ctx.message)

    # -- replies, chat channels and reactions ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message):
        if getattr(message.author, "bot", False) or not self.allowed(message):
            return
        text = (message.content or "").strip()
        if not text or text.startswith(self.prefix):
            return
        ref = getattr(message, "reference", None)
        mid = str(getattr(ref, "message_id", "") or "")
        shown = self.store.screen(mid) if mid else None
        if shown is None and mid and await self.is_our_screen(message):
            shown = {"user": str(message.author.id)}
        if shown and shown["user"] == str(message.author.id):
            return await self.talk(message, text)
        if self.chat_channel(message):
            await self.talk(message, text)

    async def is_our_screen(self, message) -> bool:
        """True when ``message`` replies to the header or picture of one of her screens (only the footer's id is
        stored, since a screen is three messages)."""
        ref = getattr(message, "reference", None)
        target = getattr(ref, "resolved", None)
        if target is None:
            try:
                target = await message.channel.fetch_message(str(ref.message_id))
            except Exception:  # noqa: BLE001
                return False
        if target is None or str(getattr(target.author, "id", "")) != str(getattr(self.bot.user, "id", "")):
            return False
        if any((getattr(a, "filename", "") or "").startswith("vn-") for a in (getattr(target, "attachments", None) or [])):
            return True
        return f"🎀 {self.name} · " in (getattr(target, "content", "") or "")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        user, mid = str(payload.user_id), str(payload.message_id)
        if user == str(getattr(self.bot.user, "id", "")):
            return
        shown = self.store.screen(mid)
        if not shown or shown["user"] != user:
            return
        emoji = str(getattr(payload, "emoji", ""))
        channel = self.bot.get_channel(str(payload.channel_id))
        if channel is None:
            return
        key = shown["key"]
        s = self.store.scene(key, self.start_place)
        if shown["kind"] == "map" and emoji in NUMBERS:
            place = list(scene.PLACES)[NUMBERS.index(emoji)]
            try:
                message = await channel.fetch_message(mid)
            except Exception:  # noqa: BLE001
                return
            fake = _Asker(message, user, key)
            return await self._travel(fake, key, place, channel)
        if shown["kind"] != "chat":
            return
        if emoji == MAP:
            return await self.show_map(channel, key, user, s)
        if emoji in (PREV, NEXT) and s["pages"]:
            s["page"] = max(0, min(len(s["pages"]) - 1, s["page"] + (1 if emoji == NEXT else -1)))
            self.store.save_scene(key, s)
            await self.show(channel, key, user, s)

    # -- dashboard -----------------------------------------------------------------------------------------------
    async def dashboard_panel(self, guild, viewer):
        c = await asyncio.to_thread(self.store.counts)
        items = [{"label": "Character", "value": self.name}, {"label": "People talking", "value": c["people"]},
                 {"label": "Lines spoken", "value": c["lines"]},
                 {"label": "Model", "value": str(self.cfg.get("model") or "gpt-oss:120b")}]
        sections = [{"type": "status", "items": items}]
        if self.last_error:
            sections.append({"type": "text", "text": f"Last problem: {self.last_error}"})
        return {"title": "Visual Novel", "refresh": 30, "sections": sections}


class _Asker:
    """Stands in for the person's message when they travel by reacting on the map: replies go to the map."""

    def __init__(self, message, user: str, key: str):
        self._m, self._key = message, key
        self.channel, self.guild = message.channel, getattr(message, "guild", None)
        self.author = type("Who", (), {"id": user, "display_name": None, "name": "Senpai", "bot": False})()

    async def reply(self, *a, **k):
        return await self._m.reply(*a, **k)


async def setup(bot):
    await bot.add_cog(VisualNovel(bot))
