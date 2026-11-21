# Copied from aio-vector-bot: src/vectiq/packs/spec.py. Run tools/sync_spec.sh to update it. Do not edit here.
"""Module packs: a module as one JSON file.

A pack is what the marketplace hands out and what ``Export`` writes. Most packs are *declarative*: custom commands,
auto-replies, scheduled posts, settings and config presets, all as data, with no code to trust. A pack can also carry
Python (``code``), which only installs when ``marketplace.allow_code`` is on. See docs/module-packs.md.

This file only reads and checks packs. Nothing here touches the bot.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

FORMAT = "vectiq-module"
SPEC = 1
EXTENSION = ".vqmodule.json"

ID = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
COLOR = re.compile(r"^#?[0-9a-fA-F]{6}$")
FIELD_TYPES = ("text", "longtext", "int", "number", "bool", "channel", "enum", "list")
MATCHES = ("contains", "word", "exact", "startswith", "endswith")
CODE_SUFFIXES = (".py", ".json", ".txt", ".md", ".yaml", ".yml")

MAX_BYTES = 600_000
MAX_COMMANDS, MAX_TRIGGERS, MAX_SCHEDULES, MAX_FIELDS = 60, 60, 10, 20
MAX_TEXT, MAX_REPLIES, MAX_PHRASES = 2000, 40, 30
MAX_FILES, MAX_CODE_BYTES = 30, 300_000

# A preset may not touch these: they decide who controls the bot, or hold secrets.
DENIED_PRESET = ("owners", "dashboard", "mcp", "plugins", "marketplace", "webhooks", "communities")
DENIED_WORDS = ("token", "secret", "password", "nsec", "apikey", "api_key", "cookie", "binary")


class PackError(ValueError):
    """The pack isn't valid. ``problems`` lists everything that is wrong, in plain words."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems[:6]) + (f" (and {len(problems) - 6} more)" if len(problems) > 6 else ""))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps(pack: Mapping) -> str:
    """The way a pack is written to a file: readable, stable, UTF-8."""
    return json.dumps(pack, ensure_ascii=False, indent=2) + "\n"


def preset_path_allowed(path: str) -> bool:
    p = path.lower()
    head = p.split(".", 1)[0]
    return head not in DENIED_PRESET and not any(w in p for w in DENIED_WORDS)


class _Check:
    def __init__(self) -> None:
        self.problems: list[str] = []

    def bad(self, where: str, why: str) -> None:
        self.problems.append(f"{where}: {why}")

    def text(self, where: str, v: Any, *, limit: int = MAX_TEXT, required: bool = False, default: str = "") -> str:
        if v is None or v == "":
            if required:
                self.bad(where, "is needed")
            return default
        if not isinstance(v, str):
            self.bad(where, "must be text")
            return default
        if len(v) > limit:
            self.bad(where, f"is too long (most {limit} characters)")
            return v[:limit]
        return v

    def strings(self, where: str, v: Any, *, limit: int, each: int = MAX_TEXT, required: bool = False) -> list[str]:
        if v is None:
            if required:
                self.bad(where, "is needed")
            return []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
            self.bad(where, "must be a list of text")
            return []
        if required and not v:
            self.bad(where, "is needed")
        if len(v) > limit:
            self.bad(where, f"has too many items (most {limit})")
            v = v[:limit]
        for x in v:
            if len(x) > each:
                self.bad(where, f"an item is too long (most {each} characters)")
        return [x[:each] for x in v]

    def number(self, where: str, v: Any, *, low: float, high: float, default: float | None = None) -> Any:
        if v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not low <= v <= high:
            self.bad(where, f"must be a number from {low:g} to {high:g}")
            return default
        return v


def _replies(c: _Check, where: str, d: Mapping, *, need: bool) -> dict:
    out: dict[str, Any] = {}
    reply = c.text(f"{where}.reply", d.get("reply"))
    replies = c.strings(f"{where}.replies", d.get("replies"), limit=MAX_REPLIES)
    if reply:
        out["reply"] = reply
    if replies:
        out["replies"] = replies
    emb = d.get("embed")
    if emb is not None:
        if not isinstance(emb, Mapping):
            c.bad(f"{where}.embed", "must be an object with a title and a color")
        else:
            color = c.text(f"{where}.embed.color", emb.get("color"), limit=7)
            if color and not COLOR.match(color):
                c.bad(f"{where}.embed.color", "must look like #5865f2")
            out["embed"] = {"title": c.text(f"{where}.embed.title", emb.get("title"), limit=200),
                            **({"color": color.lstrip("#")} if color else {})}
    if need and not (reply or replies or d.get("react")):
        c.bad(where, "needs a reply (or replies to pick from)")
    return out


def _commands(c: _Check, raw: Any) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_COMMANDS:
        c.bad("commands", f"must be a list of at most {MAX_COMMANDS}")
        return []
    out, seen = [], set()
    for i, d in enumerate(raw):
        where = f"commands[{i}]"
        if not isinstance(d, Mapping):
            c.bad(where, "must be an object")
            continue
        name = c.text(f"{where}.name", d.get("name"), limit=32, required=True).lower()
        names = [name, *[a.lower() for a in c.strings(f"{where}.aliases", d.get("aliases"), limit=6, each=32)]]
        for n in names:
            if n and not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", n):
                c.bad(where, f"command name {n!r}: use letters, digits, - and _")
            if n in seen:
                c.bad(where, f"command name {n!r} is used twice")
            seen.add(n)
        item = {"name": name, "help": c.text(f"{where}.help", d.get("help"), limit=200) or f"Custom command {name}",
                **_replies(c, where, d, need=True)}
        if names[1:]:
            item["aliases"] = names[1:]
        cd = c.number(f"{where}.cooldown", d.get("cooldown"), low=0, high=86400, default=0)
        if cd:
            item["cooldown"] = cd
        for key in ("roles", "channels"):
            vals = c.strings(f"{where}.{key}", d.get(key), limit=20, each=64)
            if vals:
                item[key] = vals
        for key in ("dm", "delete_invocation"):
            if d.get(key):
                item[key] = bool(d[key])
        out.append(item)
    return out


def _triggers(c: _Check, raw: Any) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_TRIGGERS:
        c.bad("triggers", f"must be a list of at most {MAX_TRIGGERS}")
        return []
    out = []
    for i, d in enumerate(raw):
        where = f"triggers[{i}]"
        if not isinstance(d, Mapping):
            c.bad(where, "must be an object")
            continue
        match = d.get("match", "contains")
        if match not in MATCHES:
            c.bad(f"{where}.match", f"pick one of {', '.join(MATCHES)}")
            match = "contains"
        phrases = c.strings(f"{where}.phrases", d.get("phrases"), limit=MAX_PHRASES, each=200, required=True)
        reacts = c.strings(f"{where}.react", d.get("react"), limit=5, each=32)
        item = {"match": match, "phrases": phrases, **_replies(c, where, {**d, "react": reacts}, need=True)}
        if reacts:
            item["react"] = reacts
        item["cooldown"] = c.number(f"{where}.cooldown", d.get("cooldown"), low=0, high=86400, default=30)
        for key in ("channels", "roles"):
            vals = c.strings(f"{where}.{key}", d.get(key), limit=20, each=64)
            if vals:
                item[key] = vals
        out.append(item)
    return out


def _schedules(c: _Check, raw: Any) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_SCHEDULES:
        c.bad("schedules", f"must be a list of at most {MAX_SCHEDULES}")
        return []
    out = []
    for i, d in enumerate(raw):
        where = f"schedules[{i}]"
        if not isinstance(d, Mapping):
            c.bad(where, "must be an object")
            continue
        item: dict[str, Any] = {"channel": c.text(f"{where}.channel", d.get("channel"), limit=100, required=True),
                                **_replies(c, where, d, need=True)}
        every, at = d.get("every_minutes"), d.get("daily_at")
        if (every is None) == (at is None):
            c.bad(where, "give either every_minutes or daily_at")
        if every is not None:
            item["every_minutes"] = c.number(f"{where}.every_minutes", every, low=5, high=10080, default=60)
        if at is not None:
            at = c.text(f"{where}.daily_at", at, limit=40)
            if not (re.fullmatch(r"\d{1,2}:\d{2}", at) or re.fullmatch(r"\{cfg\.[a-z0-9_]+\}", at)):
                c.bad(f"{where}.daily_at", "must look like 18:30 (or {cfg.setting})")
            item["daily_at"] = at
        if d.get("timezone"):
            item["timezone"] = c.text(f"{where}.timezone", d.get("timezone"), limit=64)
        if d.get("order") in ("random", "sequence"):
            item["order"] = d["order"]
        out.append(item)
    return out


def _settings(c: _Check, raw: Any, pack_id: str) -> dict:
    if raw is None:
        return {"defaults": {}, "fields": []}
    if not isinstance(raw, Mapping):
        c.bad("settings", "must be an object with defaults and fields")
        return {"defaults": {}, "fields": []}
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, Mapping) or not all(isinstance(k, str) and re.fullmatch(r"[a-z][a-z0-9_]*", k)
                                                    for k in defaults):
        c.bad("settings.defaults", "must be an object whose keys are lowercase names")
        defaults = {}
    for k, v in defaults.items():
        if not isinstance(v, (str, int, float, bool, list)) or isinstance(v, list) and not all(
                isinstance(x, str) for x in v):
            c.bad(f"settings.defaults.{k}", "must be text, a number, on/off or a list of text")
    fields_raw = raw.get("fields") or []
    if not isinstance(fields_raw, list) or len(fields_raw) > MAX_FIELDS:
        c.bad("settings.fields", f"must be a list of at most {MAX_FIELDS}")
        fields_raw = []
    fields = []
    for i, f in enumerate(fields_raw):
        where = f"settings.fields[{i}]"
        if not isinstance(f, Mapping):
            c.bad(where, "must be an object")
            continue
        key = c.text(f"{where}.key", f.get("key"), limit=40, required=True)
        if key and key not in defaults:
            c.bad(where, f"{key!r} needs a value in settings.defaults")
        kind = f.get("type", "text")
        if kind not in FIELD_TYPES:
            c.bad(f"{where}.type", f"pick one of {', '.join(FIELD_TYPES)}")
            kind = "text"
        item = {"key": key, "label": c.text(f"{where}.label", f.get("label"), limit=80, required=True),
                "type": kind, "help": c.text(f"{where}.help", f.get("help"), limit=300)}
        if kind == "enum":
            item["options"] = c.strings(f"{where}.options", f.get("options"), limit=20, each=60, required=True)
        for bound in ("min", "max"):
            if f.get(bound) is not None:
                item[bound] = c.number(f"{where}.{bound}", f[bound], low=-1e9, high=1e9)
        fields.append(item)
    return {"defaults": dict(defaults), "fields": fields}


def _preset(c: _Check, raw: Any) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        c.bad("preset", "must be an object with config and modules")
        return {}
    cfg = raw.get("config") or {}
    mods = raw.get("modules") or {}
    out: dict[str, Any] = {}
    if not isinstance(cfg, Mapping) or len(cfg) > 400:
        c.bad("preset.config", "must be an object of setting paths and values (at most 400)")
        cfg = {}
    if not isinstance(mods, Mapping) or not all(isinstance(v, bool) for v in mods.values()):
        c.bad("preset.modules", "must map module names to true or false")
        mods = {}
    good_cfg = {}
    for path, value in cfg.items():
        if not isinstance(path, str) or not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z0-9_]+)*", path):
            c.bad("preset.config", f"{path!r} isn't a setting path like leveling.xp_per_message")
        elif not preset_path_allowed(path):
            c.bad("preset.config", f"{path} can't be changed by a preset (it controls access or holds a secret)")
        else:
            good_cfg[path] = value
    if good_cfg:
        out["config"] = good_cfg
    clean_mods = {}
    for name, on in mods.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            c.bad("preset.modules", f"{name!r} isn't a module name")
        elif name in ("dashboard", "mcp", "webhooks"):
            c.bad("preset.modules", f"a preset can't switch {name} (it opens the bot to the network)")
        else:
            clean_mods[name] = on
    if clean_mods:
        out["modules"] = clean_mods
    return out


def _code(c: _Check, raw: Any) -> dict:
    if raw is None:
        return {}
    files = raw.get("files") if isinstance(raw, Mapping) else None
    if not isinstance(files, Mapping) or not files:
        c.bad("code", "needs files: an object of file name → text")
        return {}
    if len(files) > MAX_FILES:
        c.bad("code.files", f"has too many files (most {MAX_FILES})")
    total, clean = 0, {}
    for name, body in files.items():
        p = PurePosixPath(str(name))
        if p.is_absolute() or ".." in p.parts or not p.parts or "\\" in str(name) or str(name).startswith("."):
            c.bad("code.files", f"{name!r}: use a plain relative path")
            continue
        if p.suffix not in CODE_SUFFIXES:
            c.bad("code.files", f"{name!r}: only {', '.join(CODE_SUFFIXES)} files")
            continue
        if any(not part.replace("_", "").replace("-", "").replace(".", "").isalnum() for part in p.parts):
            c.bad("code.files", f"{name!r}: letters, digits, _ - and . only")
            continue
        if not isinstance(body, str):
            c.bad("code.files", f"{name!r}: must be text")
            continue
        total += len(body.encode())
        clean[str(p)] = body
    if total > MAX_CODE_BYTES:
        c.bad("code", f"is too big ({total // 1000} KB; most {MAX_CODE_BYTES // 1000} KB)")
    if "__init__.py" not in clean:
        c.bad("code.files", "needs an __init__.py that defines MODULE and setup(bot)")
    return {"files": clean}


def check(raw: Any, *, taken: tuple[str, ...] = ()) -> dict:
    """Validate a pack and return it cleaned up (unknown keys dropped). Raises :class:`PackError` listing every problem.

    ``taken`` are names a pack may not use (the built-in modules)."""
    c = _Check()
    if not isinstance(raw, Mapping):
        raise PackError(["a pack is a JSON object"])
    if raw.get("format") != FORMAT:
        c.bad("format", f'must be "{FORMAT}"')
    spec = raw.get("spec", SPEC)
    if not isinstance(spec, int) or spec > SPEC:
        c.bad("spec", f"this Vectiq understands spec {SPEC}; the pack is spec {spec}. Update Vectiq.")
    pack_id = c.text("id", raw.get("id"), limit=32, required=True)
    if pack_id and not ID.match(pack_id):
        c.bad("id", "use 2-32 lowercase letters, digits and _, starting with a letter")
    if pack_id in taken:
        c.bad("id", f"{pack_id!r} is a built-in module; pick another id")
    out: dict[str, Any] = {"format": FORMAT, "spec": SPEC, "id": pack_id,
                           "label": c.text("label", raw.get("label"), limit=60, required=True),
                           "help": c.text("help", raw.get("help"), limit=300, required=True),
                           "group": c.text("group", raw.get("group"), limit=24, default="Community"),
                           "version": c.text("version", raw.get("version"), limit=20, default="1.0.0")}
    if not VERSION.match(out["version"]):
        c.bad("version", "must look like 1.2.0")
    for key, limit in (("author", 80), ("license", 40), ("homepage", 200), ("provides", 32), ("description", 4000)):
        v = c.text(key, raw.get(key), limit=limit)
        if v:
            out[key] = v
    if out.get("homepage") and not out["homepage"].startswith(("https://", "http://")):
        c.bad("homepage", "must be a web address")
    tags = c.strings("tags", raw.get("tags"), limit=8, each=30)
    if tags:
        out["tags"] = [t.lower() for t in tags]
    out["settings"] = _settings(c, raw.get("settings"), pack_id)
    for key, fn in (("commands", _commands), ("triggers", _triggers), ("schedules", _schedules)):
        v = fn(c, raw.get(key))
        if v:
            out[key] = v
    preset = _preset(c, raw.get("preset"))
    if preset:
        out["preset"] = preset
    code = _code(c, raw.get("code"))
    if code:
        out["code"] = code
        if any(out.get(k) for k in ("commands", "triggers", "schedules")):
            c.bad("code", "a pack with code can't also have commands, triggers or schedules; they run their own")
    if not (code or preset or any(out.get(k) for k in ("commands", "triggers", "schedules"))):
        c.bad("pack", "does nothing: add commands, triggers, schedules, a preset or code")
    if c.problems:
        raise PackError(c.problems)
    return out


def parse(data: bytes | str, *, taken: tuple[str, ...] = ()) -> dict:
    """Read the text of a pack file."""
    raw = data if isinstance(data, bytes) else data.encode()
    if len(raw) > MAX_BYTES:
        raise PackError([f"the file is too big ({len(raw) // 1000} KB; most {MAX_BYTES // 1000} KB)"])
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackError([f"that isn't JSON: {exc}"]) from None
    return check(obj, taken=taken)


def kind(pack: Mapping) -> str:
    """``code`` | ``module`` (commands, triggers or schedules) | ``preset`` (config only)."""
    if pack.get("code"):
        return "code"
    if any(pack.get(k) for k in ("commands", "triggers", "schedules")):
        return "module"
    return "preset"


def summary(pack: Mapping) -> dict:
    """What a person should see before installing: counts and the settings a preset would change."""
    return {"id": pack["id"], "label": pack["label"], "help": pack["help"], "version": pack["version"],
            "author": pack.get("author", ""), "kind": kind(pack), "group": pack["group"],
            "commands": [c["name"] for c in pack.get("commands", [])],
            "triggers": len(pack.get("triggers", [])), "schedules": len(pack.get("schedules", [])),
            "settings": len(pack["settings"]["fields"]),
            "preset": len(pack.get("preset", {}).get("config", {})) + len(pack.get("preset", {}).get("modules", {})),
            "files": sorted(pack.get("code", {}).get("files", {}))}
