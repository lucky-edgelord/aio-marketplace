"""Run code: piston-bot (engineer-man) for Vectiq. ``!run python`` and a code block runs it on a Piston server and
answers with the output. Edit your message and the answer updates; delete it and the answer goes too."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

import vector
from vector.ext import commands

from .codeswap import add_boilerplate
from .parse import RunError, format_output, parse

log = logging.getLogger("vectiq.piston")
DEFAULT_URL = "https://emkc.org/api/v2/piston"
WHITELIST_HINT = ("Piston's public server only runs code for whitelisted bots since February 2026. An owner can "
                  "run their own Piston (one Docker command, see the module page) and set its address under "
                  "Run code → Piston server, or put a whitelisted key in .env.")


def version_key(v: str):
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-+]", v or "0"))


class Piston(commands.Cog, name="Run code"):
    dashboard_page = {"label": "Run code", "icon": "▶️", "scope": "bot", "owner_only": True}

    def __init__(self, bot):
        self.bot = bot
        self.languages: dict[str, str] = {}      # alias -> language
        self.versions: dict[str, str] = {}       # language -> newest version
        self.loaded_at = 0.0
        self.last: dict[str, dict] = {}          # user -> {"input": id, "output": message}
        self.recent: dict[str, list[float]] = {}
        self.runs = 0
        self.last_error = ""

    # -- settings ------------------------------------------------------------------------------------------------
    @property
    def cfg(self) -> dict:
        return self.bot.config.get("piston", {}) or {}

    def num(self, key: str, default: float) -> float:
        try:
            return float(self.cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    @property
    def url(self) -> str:
        return str(self.cfg.get("piston_url") or DEFAULT_URL).rstrip("/")

    @property
    def prefix(self) -> str:
        return str(getattr(self.bot.config, "prefix", "!") or "!")

    def allowed(self, message) -> bool:
        guild = getattr(message, "guild", None)
        if guild is None:
            return bool(self.cfg.get("allow_dms", True))
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

    # -- the Piston server ----------------------------------------------------------------------------------------
    def call(self, path: str, body: dict | None = None):
        """Blocking request to Piston. Raises RunError with a message for people."""
        headers = {"User-Agent": "vectiq-piston", "Content-Type": "application/json"}
        key = os.environ.get(str(self.cfg.get("api_key_env") or "PISTON_API_KEY"), "")
        if key:
            headers["Authorization"] = key
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=int(self.num("request_timeout", 30))) as r:  # noqa: S310
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("message", "")
            except Exception:  # noqa: BLE001
                msg = ""
            self.last_error = f"HTTP {e.code}: {msg}"
            if "whitelist" in msg.lower():
                raise RunError(WHITELIST_HINT) from e
            raise RunError(f"The code runner said no (HTTP {e.code}){': ' + msg[:200] if msg else ''}.") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            self.last_error = f"{type(e).__name__}: {e}"
            raise RunError("I couldn't reach the code runner. An owner can check Run code → Piston server.") from e

    async def load_languages(self, force: bool = False) -> None:
        if self.languages and not force and time.time() - self.loaded_at < 6 * 3600:
            return
        runtimes = await asyncio.to_thread(self.call, "/runtimes")
        langs, vers = {}, {}
        for rt in runtimes:
            lang = rt["language"]
            if lang not in vers or version_key(rt["version"]) > version_key(vers[lang]):
                vers[lang] = rt["version"]
            langs[lang] = lang
            for alias in rt.get("aliases") or []:
                langs[alias] = lang
        self.languages, self.versions, self.loaded_at = langs, vers, time.time()

    def limited(self, user: str) -> float:
        per = self.num("runs_per_minute", 6)
        now = time.time()
        recent = [t for t in self.recent.get(user, []) if now - t < 60]
        if per and len(recent) >= per:
            self.recent[user] = recent
            return 60 - (now - recent[0])
        recent.append(now)
        self.recent[user] = recent
        return 0.0

    async def execute(self, text: str, attachment=None) -> vector.Embed:
        """Run what ``text`` describes; returns the answer as an embed. Raises RunError."""
        job = parse(text, attachment)
        await self.load_languages()
        if job.language not in self.languages:
            close = [a for a in self.languages if a.startswith(job.language[:2])][:6]
            raise RunError(f"I don't know **{job.language[:40]}**."
                           + (f" Did you mean {', '.join(f'`{c}`' for c in close)}?" if close else "")
                           + f" `{self.prefix}langs` lists them all.")
        language = self.languages[job.language]
        version = self.versions[language]
        body = {"language": language, "version": version, "files": [{"content": add_boilerplate(language, job.source)}],
                "args": job.args, "stdin": job.stdin,
                "run_timeout": int(self.num("run_timeout_ms", 3000)),
                "compile_timeout": int(self.num("compile_timeout_ms", 10000))}
        t = time.perf_counter()
        result = await asyncio.to_thread(self.call, "/execute", body)
        took = time.perf_counter() - t
        self.runs += 1
        kind, output = format_output(result, f"{language} {version}", int(self.num("max_lines", 30)))
        run = result.get("run") or {}
        code, signal = run.get("code"), run.get("signal")
        title = {"ok": f"▶️ {language} {version}", "stderr": f"⚠️ {language} {version} · errors",
                 "compile": f"⚠️ {language} {version} · didn't compile", "empty": f"▶️ {language} {version}"}[kind]
        desc = f"```{job.output_syntax}\n{output}\n```" if output else "*Ran without any output.*"
        status = f"killed ({signal})" if signal else f"exit {code}" if code is not None else "no exit code"
        e = vector.Embed(title=title, description=desc)
        e.set_footer(text=f"Run code · {status} · {took:.2f}s · edit your message to run it again")
        return e

    # -- commands -------------------------------------------------------------------------------------------------
    async def source_from(self, message):
        """(text after !run, attachment) — from the message, or the message it replies to when it has no code."""
        text = re.sub(r"^\s*\S+run\b", "", message.content or "", count=1)
        files = [a for a in (getattr(message, "attachments", None) or [])]
        if files:
            a = files[0]
            if getattr(a, "size", 0) > 65535:
                raise RunError("That file is too big (the limit is 64 KB).")
            raw = await a.read()
            try:
                return text, (a.filename, raw.decode("utf-8"))
            except UnicodeDecodeError as e:
                raise RunError("That file isn't text.") from e
        if "```" not in text:
            ref = getattr(message, "reference", None)
            target = getattr(ref, "resolved", None) if ref else None
            if ref and target is None:
                try:
                    target = await message.channel.fetch_message(str(ref.message_id))
                except Exception:  # noqa: BLE001
                    target = None
            if target is not None and "```" in (target.content or ""):
                lang = text.strip().split("\n")[0]
                block = (target.content or "")[(target.content or "").index("```"):]
                return f"{lang}\n{block}", None
        return text, None

    async def answer(self, message) -> vector.Embed | str:
        text, attachment = await self.source_from(message)
        if not text.strip() and attachment is None:
            return self.howto()
        wait = self.limited(str(message.author.id))
        if wait:
            return f"⏳ That's a lot of runs. Try again in {int(wait) + 1}s."
        try:
            return await self.execute(text, attachment)
        except RunError as e:
            return f"❌ {e}"

    def howto(self) -> vector.Embed:
        p = self.prefix
        e = vector.Embed(title="▶️ Run code", description=(
            f"Write `{p}run` and the language, then your code in a code block:\n"
            f"{p}run python\n\\`\\`\\`\nprint('hello')\n\\`\\`\\`\n"
            "Lines between the command and the block are command-line arguments (one per line); "
            "lines after the block are standard input. You can also attach a source file, or reply "
            f"`{p}run` to a message that has a code block."))
        e.set_footer(text=f"Run code · {p}langs lists the languages · edit to rerun · {p}rundel removes your last answer")
        return e

    @commands.command(name="run", help="Run code: !run <language> then a code block")
    async def run(self, ctx, *, _: str = ""):
        async with ctx.channel.typing():
            out = await self.answer(ctx.message)
        sent = await (ctx.reply(embed=out) if isinstance(out, vector.Embed) else ctx.reply(out))
        if sent is not None:
            self.last[str(ctx.author.id)] = {"input": str(ctx.message.id), "output": sent}

    @commands.command(name="langs", aliases=["languages"], help="Languages !run knows")
    async def langs(self, ctx):
        try:
            await self.load_languages()
        except RunError as e:
            return await ctx.reply(f"❌ {e}")
        names = sorted(self.versions)
        e = vector.Embed(title=f"▶️ {len(names)} languages", description=", ".join(names)[:3900])
        e.set_footer(text=f"Run code · aliases work too, like py, js, ts, c++ · {self.prefix}run <language>")
        await ctx.reply(embed=e)

    @commands.command(name="rundel", aliases=["del"], help="Delete your last !run answer")
    async def rundel(self, ctx):
        entry = self.last.pop(str(ctx.author.id), None)
        if not entry:
            return await ctx.reply("❌ Nothing of yours to delete.")
        try:
            await entry["output"].delete()
            await ctx.message.add_reaction("✅")
        except Exception:  # noqa: BLE001
            await ctx.reply("❌ I couldn't delete it.")

    # -- edit to rerun, delete to clean up --------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not self.cfg.get("edit_to_rerun", True) or getattr(after.author, "bot", False):
            return
        entry = self.last.get(str(after.author.id))
        if not entry or entry["input"] != str(after.id) or not self.allowed(after):
            return
        if not re.match(rf"^\s*{re.escape(self.prefix)}run\b", after.content or ""):
            return
        out = await self.answer(after)
        try:
            if isinstance(out, vector.Embed):
                await entry["output"].edit(content=None, embed=out)
            else:
                await entry["output"].edit(content=out, embed=None)
        except Exception as e:  # noqa: BLE001 - fall back to a new answer
            log.debug("couldn't edit the answer: %s", e)
            sent = await (after.reply(embed=out) if isinstance(out, vector.Embed) else after.reply(out))
            entry["output"] = sent

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        mid = str(getattr(payload, "message_id", ""))
        for user, entry in list(self.last.items()):
            if entry["input"] == mid:
                self.last.pop(user, None)
                try:
                    await entry["output"].delete()
                except Exception:  # noqa: BLE001
                    pass

    # -- dashboard -----------------------------------------------------------------------------------------------
    async def dashboard_panel(self, guild, viewer):
        items = [{"label": "Piston server", "value": self.url},
                 {"label": "Languages", "value": len(self.versions) or "not loaded yet"},
                 {"label": "Runs since start", "value": self.runs}]
        sections = [{"type": "status", "items": items}]
        if self.last_error:
            sections.append({"type": "text", "text": f"Last problem: {self.last_error}"})
        if self.url == DEFAULT_URL:
            sections.append({"type": "text", "text": WHITELIST_HINT})
        return {"title": "Run code", "refresh": 30, "sections": sections}


async def setup(bot):
    await bot.add_cog(Piston(bot))
