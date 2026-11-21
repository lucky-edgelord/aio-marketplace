#!/usr/bin/env python3
"""Check every module pack in modules/ and write catalog.json (and docs/catalog.json, which the website reads).

    python3 tools/build_catalog.py          # write the catalog
    python3 tools/build_catalog.py --check  # exit 1 if a pack is invalid or the catalog is out of date (CI)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import vectiq_spec as spec  # noqa: E402

REPO = "lucky-edgelord/aio-marketplace"
BUILTIN = tuple(json.loads((HERE / "builtin_modules.json").read_text()))


def entry(path: Path, pack: dict, raw: bytes) -> dict:
    s = spec.summary(pack)
    out = {"id": pack["id"], "file": f"modules/{path.name}", "label": pack["label"], "help": pack["help"],
           "description": pack.get("description", ""), "version": pack["version"], "author": pack.get("author", ""),
           "license": pack.get("license", ""), "homepage": pack.get("homepage", ""), "group": pack["group"],
           "tags": pack.get("tags", []), "kind": s["kind"], "commands": s["commands"], "triggers": s["triggers"],
           "schedules": s["schedules"], "settings": s["settings"], "preset": s["preset"], "files": s["files"],
           "provides": pack.get("provides", ""), "bytes": len(raw), "sha256": spec.digest(raw)}
    return out


def build() -> tuple[dict, list[str]]:
    problems, entries, seen = [], [], set()
    for path in sorted((ROOT / "modules").glob("*" + spec.EXTENSION)):
        raw = path.read_bytes()
        try:
            pack = spec.parse(raw, taken=BUILTIN)
        except spec.PackError as exc:
            problems += [f"{path.name}: {p}" for p in exc.problems]
            continue
        if path.name != pack["id"] + spec.EXTENSION:
            problems.append(f"{path.name}: the file should be called {pack['id']}{spec.EXTENSION}")
        if raw.decode("utf-8") != spec.dumps(pack):
            problems.append(f"{path.name}: not in the standard layout. Run: python3 tools/build_catalog.py --fix")
        if pack["id"] in seen:
            problems.append(f"{path.name}: id {pack['id']} is used twice")
        seen.add(pack["id"])
        entries.append(entry(path, pack, raw))
    return {"format": "vectiq-marketplace", "version": 1, "repo": REPO, "modules": entries}, problems


def main() -> int:
    check, fix = "--check" in sys.argv, "--fix" in sys.argv
    if fix:                                   # rewrite packs in the standard layout (indent, key order, cleaned fields)
        for path in sorted((ROOT / "modules").glob("*" + spec.EXTENSION)):
            path.write_text(spec.dumps(spec.parse(path.read_bytes(), taken=BUILTIN)), encoding="utf-8")
    catalog, problems = build()
    for p in problems:
        print("✗", p, file=sys.stderr)
    if problems:
        return 1
    text = json.dumps(catalog, ensure_ascii=False, indent=1) + "\n"
    targets = [ROOT / "catalog.json", ROOT / "docs" / "catalog.json"]
    if check:
        stale = [t.relative_to(ROOT) for t in targets if not t.exists() or t.read_text(encoding="utf-8") != text]
        if stale:
            print("✗ out of date:", ", ".join(map(str, stale)), "- run python3 tools/build_catalog.py", file=sys.stderr)
            return 1
        print(f"✓ {len(catalog['modules'])} modules, catalog up to date")
        return 0
    for t in targets:
        t.write_text(text, encoding="utf-8")
    print(f"✓ wrote {len(catalog['modules'])} modules to catalog.json and docs/catalog.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
