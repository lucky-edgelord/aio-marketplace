"""Fable as a Mudae-style gacha: roll characters, react to claim them, collect, trade, steal, merge.

``!roll`` shows a random anime character with a star rating. The first person to react with the claim emoji (or type
``!claim``) takes it, once per claim cooldown. Everyone gets an hourly allowance of rolls. Characters belong to one
person per community. Fable's own rules are kept: 1-5 stars with the odds 50/30/15/4/1, stealing by rating, and
five characters of one rating merging into one of the next. The characters were collected from AniList when the
module was built; nothing here calls an API except for downloading the picture files.
"""

from __future__ import annotations

import asyncio
import io
import logging
import random
import time
import urllib.request
from pathlib import Path

import vector
from vector.ext import commands

from . import engine
from .store import Store

log = logging.getLogger("vectiq.fable")
CONFIRM = "✅"
MAX_PICTURE = 900_000


class Fable(commands.Cog, name="Fable"):
    dashboard_page = {"label": "Fable", "icon": "🎴", "scope": "bot", "owner_only": True}

    def __init__(self, bot):
        self.bot = bot
        self.data = Path(str(getattr(bot.config, "data_dir", None) or "data")) / "fable"
        self.catalog = engine.Catalog()
        self.store = Store(str(self.data / "fable.db"))
        self.rng = random.Random()
        self.pending: dict[str, dict] = {}       # message id -> a confirmation waiting for ✅
        self.cooldown_notice: dict[tuple, float] = {}
        self.last_error = ""

    async def cog_unload(self):
        self.store.close()

    # -- settings and places -----------------------------------------------------------------------------------
    @property
    def cfg(self) -> dict:
        return self.bot.config.get("fable", {}) or {}

    def num(self, key: str, default: float) -> float:
        try:
            return float(self.cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    def flag(self, key: str, default: bool = True) -> bool:
        return bool(self.cfg.get(key, default))

    @property
    def emoji(self) -> str:
        return str(self.cfg.get("claim_emoji") or "💖")

    def allowed(self, message) -> bool:
        guild = getattr(message, "guild", None)
        if guild is None:
            return False                                       # characters live in communities
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

    @staticmethod
    def who(message) -> tuple[str, str, str]:
        a = message.author
        return (str(message.guild.id), str(a.id),
                getattr(a, "display_name", None) or getattr(a, "name", None) or "someone")

    def name_of(self, guild: str, user: str) -> str:
        return self.store.player(guild, user)["name"] or "someone"

    # -- pictures ------------------------------------------------------------------------------------------------
    def fetch_picture(self, char: engine.Char) -> tuple[bytes, str]:
        """Blocking: the character's picture, downloaded once into the data folder (under 1 MB, or shrunk to be)."""
        ext = char.pic.rsplit(".", 1)[-1].lower()
        path = self.data / "images" / f"{char.id}.{ext}"
        if not path.is_file():
            req = urllib.request.Request(self.catalog.url(char), headers={"User-Agent": "vectiq-fable"})
            with urllib.request.urlopen(req, timeout=25) as r:  # noqa: S310 - fixed picture host
                data = r.read(8_000_000)
            if len(data) > MAX_PICTURE:
                from PIL import Image
                im = Image.open(io.BytesIO(data)).convert("RGB")
                im.thumbnail((512, 768))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=85, optimize=True)
                data, path = buf.getvalue(), path.with_suffix(".jpg")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return path.read_bytes(), path.name

    async def send_card(self, channel, char: engine.Char, lines: str = "", reply_to=None, footer: str = ""):
        """An embed: header (name, series, stars, extra lines), the picture, then the footer."""
        card = vector.Embed(title=char.name, description="\n".join(p for p in (char.series, f"**{engine.stars(char.stars)}**", lines) if p))
        card.set_footer(text=" · ".join(p for p in ("Fable", footer) if p))
        file = None
        try:
            data, name = await asyncio.to_thread(self.fetch_picture, char)
            file = vector.File(data, filename=name, compress=False)
            card.set_image(url=f"attachment://{name}")
        except Exception as e:  # noqa: BLE001 - a missing picture shouldn't lose the roll
            self.last_error = f"{char.name}: {e}"
            log.warning("Fable: no picture for %s: %s", char.name, e)
        kw = {"embed": card, **({"file": file} if file else {})}
        return await (reply_to.reply(**kw) if reply_to is not None else channel.send(**kw))

    # -- rolling and claiming --------------------------------------------------------------------------------
    def allowance(self, guild: str, user: str, name: str = "") -> tuple[dict, int, float]:
        """(player, rolls left, seconds until the allowance renews). Renews hourly, from the first roll."""
        p = self.store.player(guild, user, name)
        now = time.time()
        due, left = engine.window(now, p["window_start"])
        if due and p["rolls_used"]:
            self.store.update(guild, user, rolls_used=0, window_start=0)
            p = self.store.player(guild, user)
        per = int(self.num("rolls_per_hour", 10))
        return p, max(0, per - p["rolls_used"]), left

    @commands.command(name="roll", aliases=["w", "pull"], help="Roll a random character, react to claim it")
    async def roll(self, ctx):
        guild, user, name = self.who(ctx.message)
        p, left, wait = self.allowance(guild, user, name)
        if left <= 0:
            return await ctx.reply(f"⏳ No rolls left. They come back in **{engine.wait(wait)}**. "
                                   f"`{self.prefix}fshop` sells a reset.")
        now = time.time()
        self.store.update(guild, user, rolls_used=p["rolls_used"] + 1, window_start=p["window_start"] or now,
                          last_seen=now)
        at_least = p["guarantee"] or 1
        if p["guarantee"]:
            self.store.update(guild, user, guarantee=0)
        stars = self.catalog.roll_stars(self.rng, at_least)
        char = self.catalog.pick(self.rng, stars, self.store.taken(guild) if self.flag("skip_owned", False) else None)
        owner = self.store.owner(guild, char.id)
        window = int(self.num("claim_window_seconds", 30))
        wishers = [self.name_of(guild, w) for w in self.store.wishers(guild, char.id) if w != owner]
        lines = []
        if wishers:
            lines.append(f"💫 Wished by {', '.join(sorted(set(wishers)))}")
        foot = (f"Belongs to {self.name_of(guild, owner)}" if owner
                else f"{self.emoji} React here to claim · {window}s · {left - 1} roll(s) left")
        async with ctx.channel.typing():
            sent = await self.send_card(ctx.channel, char, "\n".join(lines), footer=foot)
        if sent is None or not getattr(sent, "id", None):
            return
        self.store.add_roll(str(sent.id), guild, str(ctx.channel.id), char.id, user)
        self.store.log(guild, user, "roll", char.id)
        if not owner:
            try:
                await sent.add_reaction(self.emoji)
            except Exception as e:  # noqa: BLE001
                log.debug("couldn't add the claim emoji: %s", e)

    @property
    def prefix(self) -> str:
        return str(getattr(self.bot.config, "prefix", "!") or "!")

    # -- one look for every reply: views are embeds, results are ✅ / ❌ / ⏳ lines (as in core Vectiq) -------
    async def view(self, target, title: str, body: str = "", footer: str = "", fields=()):
        e = vector.Embed(title=title, description=body or None)
        for name, value, inline in fields:
            e.add_field(name=name, value=value or "-", inline=inline)
        e.set_footer(text=" · ".join(p for p in ("Fable", footer) if p))
        return await target.reply(embed=e)

    @staticmethod
    def ok(text: str) -> str:
        return f"✅ {text}"

    @staticmethod
    def fail(text: str) -> str:
        return f"❌ {text}"

    # -- coins: the bot's wallet (!bal, !daily), shared with the rest of Vectiq -------------------------------
    @property
    def eco(self):
        return getattr(getattr(self.bot, "stores", None), "economy", None)

    @property
    def sym(self) -> str:
        try:
            return self.bot.config.get("economy.currency_symbol", "🪙") or "🪙"
        except Exception:  # noqa: BLE001
            return "🪙"

    @property
    def start(self) -> int:
        try:
            return int(self.bot.config.get("economy.start_balance", 0) or 0)
        except Exception:  # noqa: BLE001
            return 0

    def money(self, n: int) -> str:
        return f"{self.sym} {n:,}"

    async def balance(self, guild: str, user: str) -> int:
        if self.eco is not None:
            return (await self.eco.wallet(guild, user, start=self.start)).balance
        return self.store.player(guild, user)["coins"]

    async def change(self, guild: str, user: str, n: int, reason: str) -> int | None:
        """Add (or take, if negative) coins. None when they don't have enough."""
        if self.eco is not None:
            try:
                return await self.eco.adjust(guild, user, n, f"fable:{reason}", start=self.start)
            except Exception as e:  # noqa: BLE001
                if type(e).__name__ == "InsufficientFunds":
                    return None
                raise
        if self.store.player(guild, user)["coins"] + n < 0:
            return None
        return self.store.add_coins(guild, user, n)

    async def try_claim(self, channel, roll: dict, user: str, loud: bool) -> None:
        guild, mid = roll["guild"], roll["message_id"]
        char = self.catalog.by_id.get(roll["char_id"])
        if char is None or roll["claimed_by"]:
            return
        now = time.time()
        window = self.num("claim_window_seconds", 30)
        if now - roll["at"] > window:
            if loud:
                await channel.send(self.fail("That roll has expired. Roll again!"))
            return
        if self.store.owner(guild, char.id):
            return
        wishers = self.store.wishers(guild, char.id)
        priority = self.num("wish_priority_seconds", 10)
        if wishers and user not in wishers and now - roll["at"] < priority:
            if loud:
                await channel.send(f"⏳ {char.name} is wished by someone, who gets first pick for "
                                   f"{int(priority - (now - roll['at'])) + 1}s.")
            return
        p = self.store.player(guild, user)
        ready_in = p["last_claim"] + self.num("claim_cooldown_hours", 3) * 3600 - now
        if ready_in > 0:
            key = (guild, user)
            if now - self.cooldown_notice.get(key, 0) > 20:       # tell them once, not on every reaction
                self.cooldown_notice[key] = now
                await channel.send(f"⏳ {p['name'] or 'You'} can claim again in **{engine.wait(ready_in)}**.")
            return
        if not self.store.mark_claimed(mid, user) or not self.store.claim(guild, char.id, user):
            return
        self.store.update(guild, user, last_claim=now, last_seen=now)
        self.store.log(guild, user, "claim", char.id)
        await channel.send(self.ok(f"**{p['name'] or 'Someone'}** claimed **{char.name}** "
                                   f"({engine.stars(char.stars)}) from {char.series}! {self.emoji}"))

    @commands.command(name="claim", help="Claim the latest roll in this channel")
    async def claim(self, ctx):
        guild, user, name = self.who(ctx.message)
        self.store.player(guild, user, name)
        roll = self.store.latest_roll(str(ctx.channel.id))
        if roll is None or roll["guild"] != guild:
            return await ctx.reply(self.fail(f"Nothing to claim here. `{self.prefix}roll` first."))
        await self.try_claim(ctx.channel, roll, user, loud=True)

    # -- reactions: claiming and confirming ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        me = str(getattr(self.bot.user, "id", ""))
        user, mid, emoji = str(payload.user_id), str(payload.message_id), str(getattr(payload, "emoji", ""))
        if user == me:
            return
        pend = self.pending.get(mid)
        if pend and emoji == CONFIRM and user == pend["user"]:
            self.pending.pop(mid, None)
            if time.time() <= pend["expires"]:
                await pend["run"]()
            return
        if emoji != self.emoji:
            return
        roll = self.store.roll(mid)
        if roll is None:
            return
        channel = self.bot.get_channel(str(payload.channel_id))
        if channel is None or not self.allowed(type("M", (), {"guild": getattr(channel, "guild", None),
                                                              "channel": channel})):
            return
        # the name comes from an earlier message of theirs, or the community's member list
        guild = roll["guild"]
        member = None
        try:
            member = channel.guild.get_member(user)
        except Exception:  # noqa: BLE001
            pass
        self.store.player(guild, user, getattr(member, "display_name", "") or "")
        await self.try_claim(channel, roll, user, loud=False)

    async def confirm(self, ctx, title: str, text: str, run, user: str | None = None, seconds: float = 45) -> None:
        e = vector.Embed(title=title, description=text)
        e.set_footer(text=f"Fable · React {CONFIRM} within {int(seconds)}s to confirm")
        sent = await ctx.reply(embed=e)
        if sent is None or not getattr(sent, "id", None):
            return
        self.pending[str(sent.id)] = {"user": user or str(ctx.author.id), "run": run, "expires": time.time() + seconds}
        try:
            await sent.add_reaction(CONFIRM)
        except Exception as e:  # noqa: BLE001
            log.debug("couldn't add %s: %s", CONFIRM, e)

    # -- finding characters --------------------------------------------------------------------------------------
    def mine(self, guild: str, user: str, query: str) -> list[engine.Char]:
        owned = self.store.owned_by(guild, user)
        chars = [self.catalog.by_id[i] for i in owned if i in self.catalog.by_id]
        q = engine.norm(query)
        exact = [c for c in chars if c.key() == q]
        return exact or [c for c in chars if q and q in c.key()]

    @staticmethod
    def split_mention(message, text: str) -> tuple:
        """(the first mentioned person or None, the text without the @mention words)."""
        people = list(getattr(message, "mentions", None) or [])
        person = next((p for p in people if not getattr(p, "bot", False)), None)
        if person is None:
            return None, text.strip()
        words = [w for w in text.split() if not w.startswith("<@") and not w.startswith("@")]
        return person, " ".join(words)

    # -- collection --------------------------------------------------------------------------------------------
    @commands.command(name="harem", aliases=["mm", "collection"], help="Your characters: !harem [@person] [page]")
    async def harem(self, ctx, *, args: str = ""):
        guild, user, name = self.who(ctx.message)
        person, rest = self.split_mention(ctx.message, args)
        target = str(person.id) if person else user
        who = (getattr(person, "display_name", None) or getattr(person, "name", None)) if person else name
        page = max(1, int(rest.split()[-1])) if rest.split() and rest.split()[-1].isdigit() else 1
        owned = [self.catalog.by_id[i] for i in self.store.owned_by(guild, target) if i in self.catalog.by_id]
        if not owned:
            return await ctx.reply(self.fail(f"{who} has no characters yet. `{self.prefix}roll` and claim some!"))
        owned.sort(key=lambda c: (-c.stars, c.name))
        size = int(self.num("page_size", 10))
        pages = (len(owned) + size - 1) // size
        page = min(page, pages)
        rows = [f"{engine.STAR * c.stars} **{c.name}** · {c.series}" for c in owned[(page - 1) * size: page * size]]
        await self.view(ctx, f"🎴 {who}'s characters ({len(owned)})", "\n".join(rows),
                        footer=f"Page {page}/{pages}" + (f" · {self.prefix}harem {page + 1} for more" if page < pages else ""))

    @commands.command(name="im", aliases=["character", "info"], help="Look up a character: !im <name>")
    async def im(self, ctx, *, name: str = ""):
        guild, *_ = self.who(ctx.message)
        found = self.catalog.find(name)
        if not found:
            return await ctx.reply(self.fail("I don't know that character."))
        char, owner = found[0], self.store.owner(guild, found[0].id)
        foot = f"Belongs to {self.name_of(guild, owner)}" if owner else "Nobody has them yet"
        also = ("Also: " + ", ".join(c.name for c in found[1:5])) if len(found) > 1 else ""
        await self.send_card(ctx.channel, char, also, reply_to=ctx.message, footer=foot)

    @commands.command(name="wish", aliases=["wishlist"], help="Wishes: !wish add|remove <name>, !wish")
    async def wish(self, ctx, *, text: str = ""):
        guild, user, name = self.who(ctx.message)
        self.store.player(guild, user, name)
        verb, _, rest = text.strip().partition(" ")
        verb = verb.lower()
        if verb in ("add", "remove", "del") and rest:
            found = self.catalog.find(rest)
            if not found:
                return await ctx.reply(self.fail("I don't know that character."))
            on = verb == "add"
            self.store.wish(guild, user, found[0].id, on)
            return await ctx.reply(self.ok(f"{'Wishing for' if on else 'No longer wishing for'} **{found[0].name}**. "
                                           + ("You get first pick when they show up." if on else "")))
        wishes = [self.catalog.by_id[i] for i in self.store.wishes(guild, user) if i in self.catalog.by_id]
        if not wishes:
            return await ctx.reply(self.fail(f"No wishes yet. `{self.prefix}wish add <name>`"))
        await self.view(ctx, "💫 Your wishes", "\n".join(f"{engine.STAR * c.stars} **{c.name}** · {c.series}" for c in wishes),
                        footer=f"{self.prefix}wish remove <name>")

    @commands.command(name="party", help="Your party of five: !party, !party <1-5> <name>, !party clear <1-5>")
    async def party(self, ctx, *, text: str = ""):
        guild, user, name = self.who(ctx.message)
        self.store.player(guild, user, name)
        parts = text.split(maxsplit=1)
        if parts and parts[0].lower() == "clear" and len(parts) > 1 and parts[1].strip() in "12345":
            self.store.set_party(guild, user, int(parts[1].strip()), None)
        elif parts and parts[0] in ("1", "2", "3", "4", "5") and len(parts) > 1:
            found = self.mine(guild, user, parts[1])
            if not found:
                return await ctx.reply(self.fail("You don't have a character called that."))
            self.store.set_party(guild, user, int(parts[0]), found[0].id)
        slots = self.store.party(guild, user)
        rows = []
        for slot in range(1, 6):
            c = self.catalog.by_id.get(slots.get(slot))
            rows.append(f"{slot}. " + (f"{engine.STAR * c.stars} **{c.name}** · {c.series}" if c else "—"))
        await self.view(ctx, "⚔️ Your party", "\n".join(rows), footer=f"{self.prefix}party <1-5> <name>")

    # -- giving, trading, stealing, merging --------------------------------------------------------------------
    async def move(self, guild: str, char: engine.Char, to: str) -> None:
        self.store.transfer(guild, char.id, to)

    @commands.command(name="givechar", aliases=["gift"], help="Give a character away: !givechar @person <name>")
    async def give(self, ctx, *, text: str = ""):
        if not self.flag("allow_trading"):
            return await ctx.reply(self.fail("Trading is off here."))
        guild, user, name = self.who(ctx.message)
        person, rest = self.split_mention(ctx.message, text)
        if person is None or not rest:
            return await ctx.reply(self.fail(f"Use `{self.prefix}givechar @person <character>`."))
        found = self.mine(guild, user, rest)
        if not found:
            return await ctx.reply(self.fail("You don't have a character called that."))
        char, to = found[0], str(person.id)
        if to == user:
            return await ctx.reply(self.fail("That's you!"))
        self.store.player(guild, to, getattr(person, "display_name", None) or getattr(person, "name", "") or "")
        await self.move(guild, char, to)
        self.store.log(guild, user, "give", char.id)
        await ctx.reply(self.ok(f"**{char.name}** now belongs to {self.name_of(guild, to)}. 🎁"))

    @commands.command(name="trade", help="Trade: !trade @person <yours> / <theirs>")
    async def trade(self, ctx, *, text: str = ""):
        if not self.flag("allow_trading"):
            return await ctx.reply(self.fail("Trading is off here."))
        guild, user, name = self.who(ctx.message)
        person, rest = self.split_mention(ctx.message, text)
        if person is None or "/" not in rest:
            return await ctx.reply(self.fail(f"Use `{self.prefix}trade @person <your character> / <their character>`."))
        mine_q, theirs_q = (s.strip() for s in rest.split("/", 1))
        other = str(person.id)
        oname = getattr(person, "display_name", None) or getattr(person, "name", None) or "them"
        self.store.player(guild, other, oname)
        a, b = self.mine(guild, user, mine_q), self.mine(guild, other, theirs_q)
        if not a or not b or other == user:
            return await ctx.reply(self.fail("Both of you need to own the characters named."))
        ca, cb = a[0], b[0]

        async def run():
            if self.store.owner(guild, ca.id) != user or self.store.owner(guild, cb.id) != other:
                return await ctx.channel.send(self.fail("The trade fell through: ownership changed."))
            await self.move(guild, ca, other)
            await self.move(guild, cb, user)
            self.store.log(guild, user, "trade", ca.id)
            await ctx.channel.send(self.ok(f"Traded **{ca.name}** ↔ **{cb.name}**. 🔁"))

        await self.confirm(ctx, "🔁 Trade offer", f"{name} offers **{ca.name}** ({engine.stars(ca.stars)}) for {oname}'s "
                           f"**{cb.name}** ({engine.stars(cb.stars)}). {oname}, do you accept?", run, user=other)

    @commands.command(name="steal", help="Try to steal a character from someone: !steal <name>")
    async def steal(self, ctx, *, name: str = ""):
        if not self.flag("allow_stealing"):
            return await ctx.reply(self.fail("Stealing is off here."))
        guild, user, uname = self.who(ctx.message)
        p = self.store.player(guild, user, uname)
        found = self.catalog.find(name)
        char = next((c for c in found if self.store.owner(guild, c.id)), None)
        if char is None:
            return await ctx.reply(self.fail("Nobody owns a character like that."))
        owner = self.store.owner(guild, char.id)
        if owner == user:
            return await ctx.reply(self.fail("That one's already yours."))
        now = time.time()
        cool = p["last_steal"] + self.num("steal_cooldown_hours", 24) * 3600 - now
        if cool > 0:
            return await ctx.reply(f"⏳ You can try stealing again in **{engine.wait(cool)}**.")
        cost = int(self.num("steal_cost", 50))
        if cost and await self.change(guild, user, -cost, "steal") is None:
            return await ctx.reply(self.fail(f"Stealing costs **{self.money(cost)}**; you have "
                                             f"{self.money(await self.balance(guild, user))}."))
        inactive = (now - self.store.player(guild, owner)["last_seen"]) / 86400 if self.store.player(guild, owner)["last_seen"] else 30
        chance = engine.steal_chance(char.stars, inactive)
        self.store.update(guild, user, last_steal=now, last_seen=now)
        if self.rng.randrange(100) < chance:
            await self.move(guild, char, user)
            self.store.log(guild, user, "steal", char.id)
            await ctx.reply(self.ok(f"Stolen! (**{chance}%** chance) **{char.name}** is yours now. 🥷"))
        else:
            self.store.log(guild, user, "steal-failed", char.id)
            await ctx.reply(self.fail(f"{self.name_of(guild, owner)} noticed. (**{chance}%** chance) Better luck next time."))

    @commands.command(name="merge", help="Merge five characters into one of a higher rating: !merge <2-5>")
    async def merge(self, ctx, target: int = 0):
        if not self.flag("allow_merging"):
            return await ctx.reply(self.fail("Merging is off here."))
        guild, user, name = self.who(ctx.message)
        owned = [self.catalog.by_id[i] for i in self.store.owned_by(guild, user) if i in self.catalog.by_id]
        protected = set(self.store.party(guild, user).values())
        group = engine.merge_group(owned, target, protected) if 2 <= target <= 5 else None
        if group is None:
            return await ctx.reply(self.fail(f"Use `{self.prefix}merge <2-5>`. It takes five {max(1, target - 1)}★ characters "
                                   "(not in your party) to make one new {target}★.".replace("{target}", str(target))))
        free = [c for c in self.catalog.by_stars[target] if not self.store.owner(guild, c.id)]
        if not free:
            return await ctx.reply(self.fail(f"Every {target}★ character already has an owner."))

        async def run():
            have = {c.id for c in group if self.store.owner(guild, c.id) == user}
            if len(have) < len(group):
                return await ctx.channel.send(self.fail("The merge fell through: you no longer own all five."))
            new = self.rng.choice([c for c in free if not self.store.owner(guild, c.id)] or free)
            for c in group:
                self.store.release(guild, c.id)
            self.store.claim(guild, new.id, user)
            self.store.log(guild, user, "merge", new.id)
            await self.send_card(ctx.channel, new, f"Merged from {', '.join(c.name for c in group)}",
                                 footer=f"New for {name}")

        await self.confirm(ctx, "🧬 Merge", "Merge " + ", ".join(f"**{c.name}**" for c in group) + f" into a random "
                           f"**{target}★** character?", run)

    @commands.command(name="divorce", aliases=["release"], help="Release a character for coins: !divorce <name>")
    async def divorce(self, ctx, *, name: str = ""):
        guild, user, uname = self.who(ctx.message)
        found = self.mine(guild, user, name) if name else []
        if not found:
            return await ctx.reply(self.fail("You don't have a character called that."))
        char = found[0]
        value = engine.VALUE[char.stars]

        async def run():
            if self.store.owner(guild, char.id) != user:
                return
            self.store.release(guild, char.id)
            coins = await self.change(guild, user, value, "release")
            self.store.log(guild, user, "release", char.id)
            await ctx.channel.send(self.ok(f"**{char.name}** is free again. You got **{self.money(value)}** "
                                           f"({self.money(coins or 0)} total)."))

        await self.confirm(ctx, "👋 Release", f"Release **{char.name}** ({engine.stars(char.stars)}) for **{self.money(value)}**?", run)

    # -- coins, daily, shop and status ----------------------------------------------------------------------------
    @commands.command(name="fdaily", aliases=["fabledaily"], help="Daily coins (only when Vectiq's economy is off)")
    async def daily(self, ctx):
        if self.eco is not None:
            return await ctx.reply(self.fail(f"Fable uses your wallet: `{self.prefix}daily` collects coins, "
                                             f"`{self.prefix}bal` shows them."))
        guild, user, name = self.who(ctx.message)
        p = self.store.player(guild, user, name)
        now = time.time()
        left = p["daily_at"] + 20 * 3600 - now
        if left > 0:
            return await ctx.reply(f"⏳ Come back in **{engine.wait(left)}** for more.")
        amount = int(self.num("daily_coins", 100))
        coins = self.store.add_coins(guild, user, amount)
        self.store.update(guild, user, daily_at=now)
        await ctx.reply(self.ok(f"You got **{self.money(amount)}**. You have {self.money(coins)}."))

    @commands.command(name="tu", aliases=["rolls", "status"], help="Your rolls, claim and coins")
    async def tu(self, ctx):
        guild, user, name = self.who(ctx.message)
        p, left, wait = self.allowance(guild, user, name)
        per = int(self.num("rolls_per_hour", 10))
        ready_in = p["last_claim"] + self.num("claim_cooldown_hours", 3) * 3600 - time.time()
        fields = [("Rolls", f"**{left}/{per}**" + (f" · renew in {engine.wait(wait)}" if wait else ""), True),
                  ("Claim", "**ready**" if ready_in <= 0 else f"in **{engine.wait(ready_in)}**", True),
                  ("Wallet", self.money(await self.balance(guild, user)), True),
                  ("Characters", str(len(self.store.owned_by(guild, user))), True)]
        if p["guarantee"]:
            fields.append(("Next roll", f"**{p['guarantee']}★ or better**", True))
        await self.view(ctx, f"🎴 {name}", fields=fields, footer=f"{self.prefix}roll · {self.prefix}fshop")

    @commands.command(name="fshop", aliases=["fableshop"], help="See what coins buy")
    async def shop(self, ctx):
        if not self.flag("allow_shop"):
            return await ctx.reply(self.fail("The shop is closed."))
        s = engine.SHOP
        rows = [("reset", "A fresh set of rolls right now"), ("guarantee3", "Your next roll is 3★ or better"),
                ("guarantee4", "Your next roll is 4★ or better"), ("guarantee5", "Your next roll is a 5★")]
        await self.view(ctx, "🛒 Fable shop", "\n".join(f"`{k}` · **{self.money(s[k])}** · {d}" for k, d in rows),
                        footer=f"{self.prefix}fbuy <item> · coins come from {self.prefix}daily")

    @commands.command(name="fbuy", aliases=["fablebuy"], help="Buy from the shop: !fbuy <item>")
    async def buy(self, ctx, item: str = ""):
        if not self.flag("allow_shop"):
            return await ctx.reply(self.fail("The shop is closed."))
        guild, user, name = self.who(ctx.message)
        self.store.player(guild, user, name)
        item = item.lower()
        cost = engine.SHOP.get(item)
        if cost is None:
            return await ctx.reply(self.fail(f"No such item. See `{self.prefix}fshop`."))
        left = await self.change(guild, user, -cost, f"buy-{item}")
        if left is None:
            have = await self.balance(guild, user)
            return await ctx.reply(self.fail(f"**{item}** costs **{self.money(cost)}**; you have {self.money(have)}."))
        if item == "reset":
            self.store.update(guild, user, rolls_used=0, window_start=0)
        else:
            self.store.update(guild, user, guarantee=int(item[-1]))
        await ctx.reply(self.ok(f"Bought **{item}** for {self.money(cost)}. You have {self.money(left)} left."))

    @commands.command(name="fable", aliases=["gacha"], help="How Fable works")
    async def fable(self, ctx):
        p = self.prefix
        await self.view(ctx, "🎴 Fable", (
            f"Roll a character with `{p}roll`, then react {self.emoji} (or `{p}claim`) to take it. "
            f"{int(self.num('rolls_per_hour', 10))} rolls an hour, one claim every {self.num('claim_cooldown_hours', 3):g}h."),
            fields=[("Collect", f"`{p}harem` · `{p}im <name>` · `{p}wish add <name>` · `{p}party`", False),
                    ("Swap", f"`{p}givechar` · `{p}trade` · `{p}steal` · `{p}merge <2-5>` · `{p}divorce <name>`", False),
                    ("Coins", f"`{p}tu` · `{p}fshop` · `{p}fbuy` · your wallet: `{p}bal`, `{p}daily`", False)])

    # -- dashboard -----------------------------------------------------------------------------------------------
    async def dashboard_panel(self, guild, viewer):
        gid = str(getattr(guild, "id", "") or "") or None
        st = await asyncio.to_thread(self.store.stats, gid)
        items = [
            {"label": "Characters", "value": f"{len(self.catalog.chars)} in the pool"},
            {"label": "Players", "value": st["players"]},
            {"label": "Owned", "value": st["owned"]},
            {"label": "Rolls", "value": st["rolls"]},
            {"label": "Claims", "value": st["claims"]},
            {"label": "Rolls an hour", "value": int(self.num("rolls_per_hour", 10))},
        ]
        sections = [{"type": "status", "items": items}]
        if self.last_error:
            sections.append({"type": "text", "text": f"Last problem: {self.last_error}"})
        recent = await asyncio.to_thread(self.store.recent)
        rows = []
        for r in recent:
            c = self.catalog.by_id.get(r["char_id"])
            rows.append({"title": f"{r['what']}: {c.name if c else '?'}",
                         "detail": time.strftime("%b %d %H:%M", time.localtime(r["at"])),
                         "tag": engine.STAR * c.stars if c else ""})
        if rows:
            sections.append({"type": "list", "title": "Latest", "items": rows})
        return {"title": "Fable", "refresh": 20, "sections": sections}


async def setup(bot):
    await bot.add_cog(Fable(bot))
