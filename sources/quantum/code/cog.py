"""Quantum: circuits in chat, from lucky-edgelord/quantum-web-lab. ``!qc`` with a code block in micro QASM, MicroQiskit
(Python), Q text (H-X#0) or console lines runs it and answers with an IBM Composer-style picture: the circuit, the
probabilities and a Bloch sphere per qubit. ``!qc h 0`` / ``!qc cx 0 1`` / ``!qc run`` builds your own circuit step by
step. ``!qc -> qasm`` converts. ``!qlab`` sends the whole lab as a mini app."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path

import vector
from vector.ext import commands

from . import microqiskit as mq
from . import qtext, render
from .safepy import Runner, SnippetError

log = logging.getLogger("vectiq.quantum")
DEFAULT_ASSETS = "https://raw.githubusercontent.com/lucky-edgelord/aio-marketplace/main/modules/media/quantum/assets/"
ASSET_FILES = ["IBMPlexSans-Regular.ttf", "IBMPlexSans-SemiBold.ttf", "IBMPlexMono-Regular.ttf",
               "IBMPlexMono-SemiBold.ttf", "quantum-web-lab.xdc"]
FENCE = re.compile(r"```(?:([^\s`]+)\n|\n?)(.*?)```", re.S)
FORMATS = {"qasm": "OpenQASM 3", "qasm2": "OpenQASM 2", "python": "MicroQiskit", "q": "Q text", "diagram": "ASCII diagram"}
CONSOLE_WORDS = {"run", "show", "reset", "clear", "undo", "explain", "code", "help"}


class QuantumError(Exception):
    pass


class Saved:
    """Each person's console circuit (ops and qubit count). SQLite."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("CREATE TABLE IF NOT EXISTS circuits (key TEXT PRIMARY KEY, ops TEXT NOT NULL, n INTEGER NOT NULL, at REAL)")
        self.lock = threading.Lock()

    def get(self, key: str) -> tuple[list, int]:
        with self.lock:
            r = self.db.execute("SELECT ops, n FROM circuits WHERE key=?", (key,)).fetchone()
        return (json.loads(r[0]), r[1]) if r else ([], 1)

    def put(self, key: str, ops: list, n: int) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO circuits VALUES (?,?,?,?)", (key, json.dumps(ops), n, time.time()))

    def close(self):
        with self.lock:
            self.db.close()


class Quantum(commands.Cog, name="Quantum"):
    dashboard_page = {"label": "Quantum", "icon": "⚛️", "scope": "bot", "owner_only": True}

    def __init__(self, bot):
        self.bot = bot
        self.data = Path(str(getattr(bot.config, "data_dir", None) or "data")) / "quantum"
        self.saved = Saved(str(self.data / "quantum.db"))
        self._assets: Path | None = None
        self.runs = 0
        self.last_error = ""

    async def cog_unload(self):
        self.saved.close()

    # -- settings and assets ----------------------------------------------------------------------------------
    @property
    def cfg(self) -> dict:
        return self.bot.config.get("quantum", {}) or {}

    def num(self, key: str, default: int) -> int:
        try:
            return int(self.cfg.get(key, default))
        except (TypeError, ValueError):
            return default

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
        return any(w == str(message.channel.id).lower() or w in name for w in wanted)

    async def cog_check(self, ctx) -> bool:
        return self.allowed(ctx.message)

    def assets(self) -> Path:
        if self._assets is None:
            src = str(self.cfg.get("assets_url") or DEFAULT_ASSETS)
            if not src.startswith("http"):
                self._assets = Path(src)
            else:
                dest = self.data / "assets"
                for name in ASSET_FILES:
                    p = dest / name
                    if not p.is_file():
                        p.parent.mkdir(parents=True, exist_ok=True)
                        req = urllib.request.Request(src.rstrip("/") + "/" + name, headers={"User-Agent": "vectiq-quantum"})
                        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - owner-chosen host
                            p.write_bytes(r.read(5_000_000))
                self._assets = dest
        return self._assets

    # -- reading what was sent --------------------------------------------------------------------------------
    @staticmethod
    def options(head: str) -> tuple[dict, str | None]:
        """shots=, seed=, and '-> format' from the first line."""
        opts, target = {}, None
        m = re.search(r"->\s*(\w+)", head)
        if m:
            target = {"qasm3": "qasm", "openqasm": "qasm", "py": "python", "qiskit": "python", "microqiskit": "python",
                      "text": "q", "qtext": "q", "ascii": "diagram", "draw": "diagram"}.get(m.group(1).lower(), m.group(1).lower())
            if target not in FORMATS:
                raise QuantumError(f"I can convert to {', '.join(FORMATS)}.")
        for k, v in re.findall(r"(shots|seed)\s*=\s*(\d+)", head):
            opts[k] = int(v)
        for word in ("text", "both", "picture"):
            if re.search(rf"\b{word}\b", head.lower()):
                opts["output"] = word
        return opts, target

    def circuit_from(self, syntax: str, code: str) -> tuple[mq.QuantumCircuit, str, str]:
        """(circuit, format name, printed output). Raises QuantumError."""
        syntax = (syntax or "").lower()
        text = code.strip()
        try:
            if syntax in ("qasm", "openqasm", "qasm3", "qasm2") or (not syntax and re.search(r"OPENQASM|qubit\[|qreg ", text)):
                return mq.from_qasm(text), "micro QASM", ""
            if syntax in ("py", "python", "qiskit", "microqiskit") or (not syntax and re.search(r"QuantumCircuit|qc\.", text)):
                run = Runner(max_qubits=self.num("max_qubits", 12), max_gates=self.num("max_gates", 500)).run(text)
                qc = run.circuit()
                if qc is None:
                    raise QuantumError("Your code didn't make a circuit. Start with `qc = QuantumCircuit(2, 2)`.")
                return qc, "MicroQiskit", run.printed()
            if syntax in ("console", "qconsole") or (not syntax and qtext.looks_like_console(text)):
                ops, n = qtext.apply_console([], 1, text)
                return qtext.build(ops, n), "console", ""
            return qtext.from_text(text), "Q text", ""
        except SnippetError as e:
            raise QuantumError(str(e)) from e
        except QuantumError:
            raise
        except (ValueError, TypeError, KeyError, IndexError) as e:
            raise QuantumError(str(e) or type(e).__name__) from e

    def convert(self, qc, target: str) -> str:
        if target == "qasm":
            return qc.qasm()
        if target == "qasm2":
            return qasm2(qc.qasm())
        if target == "python":
            return qtext.to_python(qc)
        if target == "q":
            return qtext.to_text(qc)
        return qc.draw()

    # -- running and answering --------------------------------------------------------------------------------
    def check_size(self, qc):
        limit = self.num("max_qubits", 12)
        if qc.num_qubits > limit:
            raise QuantumError(f"{qc.num_qubits} qubits is too many here; the limit is {limit}.")
        gates = sum(1 for op in qc.data if op[0] != "barrier")
        if gates > self.num("max_gates", 500):
            raise QuantumError(f"That's {gates} gates; the limit is {self.num('max_gates', 500)}.")

    def picture(self, qc, shots: int, seed, title: str) -> tuple[bytes, dict, bool]:
        """Blocking: (PNG card, the distribution shown, was it measured)."""
        self.check_size(qc)
        measured = any(op[0] == "measure" for op in qc.data)
        bare = mq.QuantumCircuit(qc.num_qubits)
        bare.data = [op for op in qc.data if op[0] != "measure"]
        state = mq.simulate(bare, get="statevector")
        if measured:
            dist = mq.simulate(qc, shots, "counts", seed)
            chart = f"Measured · {shots:,} shots" + (f" · seed {seed}" if seed is not None else "")
        else:
            dist = mq.simulate(qc, get="probabilities")
            chart = "Probabilities"
        png = render.card(qc, dist, state, render.Fonts(self.assets()), title, chart,
                          max_spheres=self.num("max_spheres", 4))
        return png, dist, measured

    async def answer(self, ctx, qc, fmt: str, printed: str, opts: dict, title: str, footer_extra: str = ""):
        shots = max(1, min(100000, opts.get("shots", self.num("shots", 1024))))
        seed = opts.get("seed")
        mode = opts.get("output") or str(self.cfg.get("output") or "picture")
        if mode in ("text", "both"):
            try:
                self.check_size(qc)
                body = await asyncio.to_thread(text_results, qc, shots, seed)
            except QuantumError as e:
                return await ctx.reply(f"❌ {e}")
            out = printed.strip()
            blocks = ([("Output", out[:1200])] if out else []) + body
            await ctx.reply(embed=plain(f"⚛️ {title}", blocks, " · ".join(p for p in ("Quantum", fmt, "qubit 0 is the right-most digit", footer_extra) if p)))
            if mode == "text":
                self.runs += 1
                return
            printed = ""
        try:
            async with ctx.channel.typing():
                png, dist, measured = await asyncio.wait_for(
                    asyncio.to_thread(self.picture, qc, shots, seed, title), 30)
        except QuantumError as e:
            return await ctx.reply(f"❌ {e}")
        except asyncio.TimeoutError:
            return await ctx.reply("❌ That took too long to simulate.")
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            log.warning("quantum: %s", self.last_error)
            return await ctx.reply("❌ Something went wrong drawing that circuit.")
        self.runs += 1
        total = sum(dist.values()) or 1
        top = sorted(dist.items(), key=lambda kv: -kv[1])[:4]
        summary = " · ".join(f"`{k}` {v / total * 100:.1f}%" for k, v in top)
        card = vector.Embed(title=f"⚛️ {title}", description=summary)
        card.set_image(url="attachment://quantum.png")
        bits = "qubit 0 is the right-most digit"
        card.set_footer(text=" · ".join(p for p in ("Quantum", fmt, bits, footer_extra) if p))
        await ctx.reply(embed=card, file=vector.File(io.BytesIO(png), filename="quantum.png", compress=False))
        if printed.strip():
            await ctx.channel.send(embed=plain("🖨️ Your code printed", [("", printed.strip()[:1500])], "Quantum"))

    @staticmethod
    def title_of(code: str, default: str) -> str:
        for line in code.strip().splitlines()[:3]:
            m = re.match(r"\s*(?://|#)\s*(.+)", line)
            if m and not m.group(1).lower().startswith(("include", "!")):
                return m.group(1).strip()[:60]
        return default

    @commands.command(name="qc", aliases=["quantum"], help="Quantum circuits: !qc with a code block, or !qc h 0 / cx 0 1 / run")
    async def qc(self, ctx, *, text: str = ""):
        text = text or ""
        if not text.strip():
            return await ctx.reply(embed=self.help_text())
        try:
            head = text.split("\n", 1)[0]
            m = FENCE.search(text)
            if m:
                opts, target = self.options(head if not head.lstrip().startswith("```") else "")
                code = m.group(2)
                qc, fmt, printed = await asyncio.to_thread(self.circuit_from, m.group(1), code)
                if target:
                    return await self.send_code(ctx, qc, target)
                return await self.answer(ctx, qc, fmt, printed, opts, self.title_of(code, "Quantum circuit"))
            return await self.console(ctx, text)
        except QuantumError as e:
            await ctx.reply(f"❌ {e}")

    async def send_code(self, ctx, qc, target: str):
        out = self.convert(qc, target)
        lang = {"qasm": "qasm", "qasm2": "qasm", "python": "python", "q": "", "diagram": ""}[target]
        await ctx.reply(embed=plain(f"⚛️ {FORMATS[target]}", [("", out)], f"Quantum · {self.prefix}qc -> qasm | qasm2 | python | q | diagram",
                              lang=lang))

    # -- the console: your own circuit, built a step at a time -----------------------------------------------
    @staticmethod
    def key(message) -> str:
        g = getattr(message, "guild", None)
        return f"{getattr(g, 'id', None) or 'dm'}|{message.author.id}"

    async def console(self, ctx, text: str):
        key = self.key(ctx.message)
        ops, n = self.saved.get(key)
        word = text.strip().split()[0].lower()
        opts, target = self.options(text)
        if target:
            return await self.send_code(ctx, qtext.build(ops, n), target)
        if word in ("reset", "clear"):
            self.saved.put(key, [], 1)
            return await ctx.reply(f"✅ Your circuit is empty again. Try `{self.prefix}qc h 0`.")
        if word == "undo":
            if not ops:
                return await ctx.reply("❌ Nothing to undo.")
            self.saved.put(key, ops[:-1], n)
            ops = ops[:-1]
            return await self.answer(ctx, qtext.build(ops, n), "your circuit", "", opts, "Your circuit", "undone")
        if word == "explain":
            gate = (text.split()[1:] or [""])[0].lower()
            gate = {"cnot": "cx", "toffoli": "ccx", "m": "measure", "i": "id"}.get(gate, gate)
            info = qtext.INFO.get(gate)
            return await ctx.reply(f"ℹ️ **{gate}**: {info}" if info else "❌ Gates: " + ", ".join(sorted(qtext.INFO)))
        if word == "help":
            return await ctx.reply(embed=self.help_text())
        if word in ("run", "show") or re.fullmatch(r"(run|show)?\s*((shots|seed)\s*=\s*\d+\s*)*", text.strip()):
            if not ops:
                return await ctx.reply(f"❌ Your circuit is empty. Start with `{self.prefix}qc h 0`.")
            return await self.answer(ctx, qtext.build(ops, n), "your circuit", "", opts, "Your circuit")
        try:
            new_ops, new_n = qtext.apply_console(ops, n, text)
            qc = qtext.build(new_ops, new_n)
            self.check_size(qc)
        except (ValueError, QuantumError) as e:
            return await ctx.reply(f"❌ {e}")
        self.saved.put(key, new_ops, new_n)
        await self.answer(ctx, qc, "your circuit", "", opts, "Your circuit",
                          f"{self.prefix}qc undo · reset · -> qasm")

    # -- the lab and help -------------------------------------------------------------------------------------
    @commands.command(name="qlab", aliases=["quantumlab"], help="The Quantum Web Lab as a mini app")
    async def qlab(self, ctx):
        try:
            path = (await asyncio.to_thread(self.assets)) / "quantum-web-lab.xdc"
        except Exception as e:  # noqa: BLE001
            self.last_error = f"assets: {e}"
            return await ctx.reply("❌ I couldn't get the lab. An owner can check the Quantum settings.")
        e = vector.Embed(title="⚛️ Quantum Web Lab", description="Tap to open: a composer with a Bloch sphere, "
                         "code in MicroQiskit, micro QASM and Q text, a console and challenges. Works offline.")
        e.set_footer(text="Quantum · the lab runs on your phone, nothing is sent anywhere")
        await ctx.reply(embed=e, file=vector.File(str(path), filename="quantum-web-lab.xdc"))

    def help_text(self) -> vector.Embed:
        p, b = self.prefix, "```"
        e = vector.Embed(title="⚛️ Quantum circuits", description=(
            f"**Step by step:** `{p}qc h 0`, `{p}qc cx 0 1`, `{p}qc measure`, then `{p}qc run`. "
            f"Also `{p}qc undo`, `{p}qc reset`, `{p}qc explain h`.\n\n"
            f"**A whole circuit:** `{p}qc` and a code block. Q text:\n"
            f"{b}\nH-X#0-M\nI-X#1-M\n{b}\n"
            "micro QASM:\n"
            f"{b}qasm\nqubit[2] q;\nh q[0];\ncx q[0], q[1];\n{b}\n"
            "MicroQiskit:\n"
            f"{b}python\nqc = QuantumCircuit(2, 2)\nqc.h(0)\nqc.cx(0, 1)\nqc.measure_all()\n{b}\n"
            f"**On the first line:** `shots=2000`, `seed=7`, `text` for results as text, "
            f"or `-> qasm`, `-> python`, `-> q`, `-> diagram` to convert.\n"
            f"`{p}qlab` opens the full Quantum Web Lab."))
        e.set_footer(text=f"Quantum · up to {self.num('max_qubits', 12)} qubits · qubit 0 is the right-most digit, like Qiskit")
        return e

    # -- dashboard -----------------------------------------------------------------------------------------------
    async def dashboard_panel(self, guild, viewer):
        items = [{"label": "Circuits run", "value": self.runs}, {"label": "Max qubits", "value": self.num("max_qubits", 12)}]
        sections = [{"type": "status", "items": items}]
        if self.last_error:
            sections.append({"type": "text", "text": f"Last problem: {self.last_error}"})
        return {"title": "Quantum", "refresh": 30, "sections": sections}


def plain(title: str, blocks: list[tuple[str, str]], footer: str, lang: str = "") -> vector.Embed:
    """An embed whose description holds real code blocks (each fence on its own line, so Vector renders them)."""
    parts = []
    for label, body in blocks:
        if label:
            parts.append(f"**{label}**")
        parts.append(f"```{lang}\n" + body.replace("```", "`\u200b``") + "\n```")
    e = vector.Embed(title=title, description="\n".join(parts))
    e.set_footer(text=footer)
    return e


def text_results(qc, shots: int, seed) -> list[tuple[str, str]]:
    """The circuit as a diagram, the results as text bars, and each qubit's Bloch arrow."""
    measured = any(op[0] == "measure" for op in qc.data)
    bare = mq.QuantumCircuit(qc.num_qubits)
    bare.data = [op for op in qc.data if op[0] != "measure"]
    state = mq.simulate(bare, get="statevector")
    if measured:
        dist = mq.simulate(qc, shots, "counts", seed)
        label = f"Measured, {shots:,} shots" + (f", seed {seed}" if seed is not None else "")
    else:
        dist = mq.simulate(qc, get="probabilities")
        label = "Probabilities"
    total = sum(dist.values()) or 1
    rows = sorted(dist.items(), key=lambda kv: -kv[1])[:16]
    rows.sort()
    width = 16
    bars = "\n".join(f"{k}  {'█' * round(v / total * width):<{width}} {v / total * 100:5.1f}%"
                     + (f"  ({v})" if measured else "") for k, v in rows)
    if len(dist) > len(rows):
        bars += f"\n+ {len(dist) - len(rows)} more"
    from .render import bloch_vectors
    import math
    vecs = bloch_vectors(state, qc.num_qubits)
    bl = []
    for i, (x, y, z) in enumerate(vecs[:12]):
        length = math.sqrt(x * x + y * y + z * z)
        if length < 0.02:
            bl.append(f"q[{i}]  entangled, no arrow")
        else:
            th = math.degrees(math.acos(max(-1, min(1, z / length))))
            ph = math.degrees(math.atan2(y, x)) % 360 if math.hypot(x, y) > 1e-6 else 0
            bl.append(f"q[{i}]  x {x:+.2f}  y {y:+.2f}  z {z:+.2f}   θ {th:3.0f}°  φ {ph:3.0f}°" + ("" if length > 0.98 else f"  (length {length:.2f})"))
    return [("Circuit", qc.draw()), (label, bars), ("Bloch arrows (before measurement)", "\n".join(bl))]


def qasm2(text: str) -> str:
    """OpenQASM 3 from MicroQiskit to OpenQASM 2."""
    out = []
    for line in text.splitlines():
        line = line.replace("OPENQASM 3.0;", "OPENQASM 2.0;").replace('include "stdgates.inc";', 'include "qelib1.inc";')
        m = re.match(r"qubit\[(\d+)\] (\w+);", line)
        if m:
            line = f"qreg {m.group(2)}[{m.group(1)}];"
        m = re.match(r"bit\[(\d+)\] (\w+);", line)
        if m:
            line = f"creg {m.group(2)}[{m.group(1)}];"
        m = re.match(r"(\w+\[\d+\]) = measure (\w+\[\d+\]);", line)
        if m:
            line = f"measure {m.group(2)} -> {m.group(1)};"
        line = re.sub(r"^p\(", "u1(", line)
        line = re.sub(r"^cp\(", "cu1(", line)
        out.append(line)
    return "\n".join(out)


async def setup(bot):
    await bot.add_cog(Quantum(bot))
