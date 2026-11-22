"""Anime reactions: the bot drops a reaction picture when a message hits one of your trigger words, or (general mode)
mentions the mood of a category. Everything is decided here, in Python, with no reaction API. The pictures are plain
files: from a folder on the bot's computer, or downloaded once from a static file host and cached.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path

import vector
from vector.ext import commands

from . import engine

log = logging.getLogger("vectiq.reactions")
IMAGE_EXT = (".gif", ".png", ".jpg", ".jpeg", ".webp")
DEFAULT_BASE = "https://raw.githubusercontent.com/lucky-edgelord/aio-marketplace/main/modules/media/reactions/pictures/"
EMOJI = {"angry": "😠", "calm-down": "😌", "confused": "😕", "dance": "💃", "embarrassed-nervous": "😅",
         "happy": "😄", "lunch-break-time": "🍱", "misc": "✨", "no": "🙅", "pre-exercise": "💪", "sad": "😢",
         "smug": "😏", "surprised": "😲", "thinking": "🤔", "yes": "👍"}
DEFAULT_RULES = (
    "happy: yay, hooray, good news\n"
    "sad: rip, f in chat\n"
    "yes: sounds good, will do\n"
    "no: absolutely not, nope\n"
    "dance: let's party\n"
)


class Reactions(commands.Cog, name="Reactions"):
    dashboard_page = {"label": "Reactions", "icon": "😺", "scope": "bot", "owner_only": True}

    def __init__(self, bot):
        self.bot = bot
        self.data_dir = Path(str(getattr(bot.config, "data_dir", None) or "data")) / "reactions"
        self.last_in: dict[str, float] = {}       # channel -> time of the last reaction
        self.recent: dict[str, list[str]] = {}    # category -> files used lately
        self.sent = 0
        self.last = ""
        self.last_error = ""
        self._matcher = None
        self._matcher_key = None

    # -- settings ------------------------------------------------------------------------------------------------
    @property
    def cfg(self) -> dict:
        return self.bot.config.get("reactions", {}) or {}

    def matcher(self) -> engine.Matcher:
        c = self.cfg
        key = (str(c.get("triggers", DEFAULT_RULES)), c.get("mode"), tuple(c.get("categories") or ()),
               bool(c.get("whole_words", True)), c.get("chance"), c.get("category_chance"))
        if key != self._matcher_key:
            self._matcher = engine.Matcher(
                key[0], mode=str(c.get("mode") or "both"), categories=c.get("categories") or [],
                whole_words=key[3], chance=float(c.get("chance", 30)),
                category_chance=float(c.get("category_chance", 15)))
            self._matcher_key = key
            for p in self._matcher.problems:
                log.warning("Reactions: %s", p)
        return self._matcher

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

    async def is_owner(self, ctx) -> bool:
        owners = [str(o).lower() for o in (getattr(self.bot.config, "owners", None) or [])]
        me = str(getattr(ctx.author, "npub", "") or ctx.author.id).lower()
        if owners:
            return me in owners
        guild = getattr(ctx, "guild", None)
        return guild is not None and str(getattr(guild, "owner_id", "")).lower() == me

    # -- pictures ------------------------------------------------------------------------------------------------
    def folder(self) -> Path:
        custom = str(self.cfg.get("images_dir") or "").strip()
        return Path(custom).expanduser() if custom else self.data_dir / "images"

    def local_files(self, category: str) -> list[Path]:
        d = self.folder() / category
        if not d.is_dir():
            return []
        return sorted(p for p in d.iterdir() if p.suffix.lower() in IMAGE_EXT and p.is_file())

    def fetch(self, category: str, name: str) -> Path:
        """Blocking: the picture on disk, downloaded once into the cache."""
        dest = self.data_dir / "cache" / category / name
        if dest.exists() and dest.stat().st_size:
            return dest
        base = str(self.cfg.get("base_url") or DEFAULT_BASE)
        url = base.rstrip("/") + "/" + urllib.parse.quote(category) + "/" + urllib.parse.quote(name)
        limit = int(float(self.cfg.get("max_mb", 8)) * 1024 * 1024)
        req = urllib.request.Request(url, headers={"User-Agent": "vectiq-reactions"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"{name} is bigger than {limit // 1048576} MB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return dest

    async def picture(self, category: str) -> Path | None:
        recent = self.recent.setdefault(category, [])
        local = self.local_files(category)
        source = str(self.cfg.get("source") or "auto")
        if local and source != "online":
            names = [p.name for p in local]
            pick = engine.choose_file(category, recent, names=names)
            path = next(p for p in local if p.name == pick)
        elif source == "local":
            return None
        else:
            limit = int(float(self.cfg.get("max_mb", 8)) * 1024 * 1024)
            for _ in range(3):          # a picture that is too big or missing is skipped, not fatal
                pick = engine.choose_file(category, recent)
                if pick is None:
                    return None
                try:
                    path = await asyncio.to_thread(self.fetch, category, pick)
                    if path.stat().st_size <= limit:
                        break
                except Exception as e:  # noqa: BLE001
                    self.last_error = f"{category}/{pick}: {e}"
                    log.warning("Reactions: couldn't get %s/%s: %s", category, pick, e)
                    recent.append(pick)
            else:
                return None
        recent.append(path.name)
        del recent[:-6]
        return path

    async def deliver(self, message, category: str, *, reply: bool | None = None, note: str = "") -> bool:
        """An embed: the category as the header, the picture in the middle, a footer underneath."""
        path = await self.picture(category)
        if path is None:
            return False
        reply = bool(self.cfg.get("reply", True)) if reply is None else reply
        name = getattr(message.author, "display_name", None) or getattr(message.author, "name", None) or "someone"
        card = vector.Embed(title=f"{EMOJI.get(category, '😺')} {category.replace('-', ' ').title()}",
                            description=str(self.cfg.get("header_text") or "").replace("{user}", name) or None)
        card.set_image(url=f"attachment://{path.name}")
        card.set_footer(text=" · ".join(p for p in ("Anime reactions", note) if p))
        file = vector.File(str(path), filename=path.name, compress=False)
        await (message.reply(embed=card, file=file) if reply else message.channel.send(embed=card, file=file))
        self.sent += 1
        self.last = f"{category} ({path.name})"
        return True

    # -- listening -------------------------------------------------------------------------------------------------
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
        if len(text) > int(self.cfg.get("max_length", 400)):
            return
        key = str(getattr(message.channel, "id", ""))
        now = time.monotonic()
        if now - self.last_in.get(key, -1e9) < float(self.cfg.get("cooldown", 20)):
            return
        pick = self.matcher().pick(text)
        if pick is None:
            return
        self.last_in[key] = now
        try:
            note = f"“{pick.why}” · {pick.chance:g}% chance" if pick.source == "words" else f"mood: {pick.why} · {pick.chance:g}% chance"
            if not await self.deliver(message, pick.category, note=note):
                self.last_in.pop(key, None)
        except Exception as e:  # noqa: BLE001 - a reaction must never break the chat
            self.last_error = str(e)
            log.warning("Reactions: couldn't send a %s picture: %s", pick.category, e)

    # -- commands ------------------------------------------------------------------------------------------------
    @commands.command(name="react", help="Post a reaction picture: !react [category]")
    async def react(self, ctx, *, category: str = ""):
        if not self.allowed(ctx.message):
            return
        cat = engine.resolve_category(category) if category else "any"
        if cat is None:
            return await ctx.reply("Categories: " + ", ".join(engine.CATEGORIES))
        if cat == "any":
            cat = random.choice(engine.CATEGORIES)
        if not await self.deliver(ctx.message, cat, reply=True, note=f"asked for by {getattr(ctx.author, 'display_name', None) or ctx.author.name}"):
            await ctx.reply(f"I couldn't get a {cat} picture. {self.last_error or 'Check the picture settings.'}")

    @commands.command(name="reactions", help="Show the reaction categories and the trigger settings")
    async def reactions(self, ctx):
        if not self.allowed(ctx.message):
            return
        c, m = self.cfg, self.matcher()
        lines = [f"**Reactions** — mode {m.mode}, words {m.chance:g}%, categories {m.category_chance:g}%, "
                 f"cooldown {c.get('cooldown', 20)}s",
                 "Categories: " + ", ".join(sorted(m.allowed))]
        for r in m.rules[:12]:
            lines.append(f"• {r.category}" + (f" @{r.chance:g}%" if r.chance is not None else "") + ": "
                         + ", ".join(r.phrases))
        await ctx.reply("\n".join(lines)[:3800])

    async def _edit_rules(self, ctx, change):
        if not await self.is_owner(ctx):
            return await ctx.reply("Only the bot's owners can change the triggers.")
        text = str(self.cfg.get("triggers", DEFAULT_RULES))
        new, ok = change(text)
        if not ok:
            return await ctx.reply("Nothing to change there.")
        if not hasattr(self.bot, "change_settings"):
            return await ctx.reply("This Vectiq can't save settings from a command. Use the dashboard.")
        await self.bot.change_settings({"reactions.triggers": new}, str(ctx.author.id))
        await ctx.reply("✅ Saved.")

    @commands.command(name="reactadd", help="Owners: !reactadd <category> <word or phrase>")
    async def reactadd(self, ctx, category: str = "", *, phrase: str = ""):
        cat = engine.resolve_category(category) if category else None
        if cat is None or not phrase.strip():
            return await ctx.reply("Use `!reactadd happy good news`. Categories: " + ", ".join(engine.CATEGORIES))
        await self._edit_rules(ctx, lambda t: (engine.add_phrase(t, cat, phrase), True))

    @commands.command(name="reactremove", help="Owners: !reactremove <category> <word or phrase>")
    async def reactremove(self, ctx, category: str = "", *, phrase: str = ""):
        cat = engine.resolve_category(category) if category else None
        if cat is None or not phrase.strip():
            return await ctx.reply("Use `!reactremove happy good news`.")
        await self._edit_rules(ctx, lambda t: engine.remove_phrase(t, cat, phrase))

    # -- dashboard -----------------------------------------------------------------------------------------------
    async def dashboard_panel(self, guild, viewer):
        m, c = self.matcher(), self.cfg
        have = sum(len(self.local_files(cat)) for cat in engine.CATEGORIES)
        items = [
            {"label": "Mode", "value": m.mode},
            {"label": "Chance", "value": f"{m.chance:g}% words · {m.category_chance:g}% categories"},
            {"label": "Pictures", "value": f"{have} on this computer" if have else "online, cached when used",
             "tone": "green"},
            {"label": "Sent", "value": self.sent},
            {"label": "Last", "value": self.last or "—"},
        ]
        sections = [{"type": "status", "items": items}]
        notes = [*m.problems]
        if self.last_error:
            notes.append(f"Last problem: {self.last_error}")
        if notes:
            sections.append({"type": "text", "text": "\n".join(notes)})
        sections.append({"type": "list", "title": "Trigger words", "items": [
            {"title": r.category, "detail": ", ".join(r.phrases)[:160],
             "tag": f"{r.chance:g}%" if r.chance is not None else f"{m.chance:g}%"} for r in m.rules]})
        return {"title": "Anime reactions", "refresh": 30, "sections": sections}


async def setup(bot):
    await bot.add_cog(Reactions(bot))
