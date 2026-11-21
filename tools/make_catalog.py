#!/usr/bin/env python3
"""Check every module in modules/ and write modules/catalog.json (and docs/catalog.json for the website).

    python3 tools/make_catalog.py           write the catalog
    python3 tools/make_catalog.py --fix     also rewrite module files in the standard layout
    python3 tools/make_catalog.py --check   change nothing; fail if a module is invalid or the catalog is stale (CI)

Needs only Python 3.9+.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import module_format as fmt  # noqa: E402

REPO = "lucky-edgelord/aio-marketplace"
MAX_PICTURE = 800_000
RESERVED = tuple(json.loads((HERE / "reserved.json").read_text()))


def main() -> int:
    check, fix = "--check" in sys.argv, "--fix" in sys.argv
    problems, entries, notes = [], [], []
    for path in sorted((ROOT / "modules").glob("*" + fmt.SUFFIX)):
        raw = path.read_bytes()
        r = fmt.validate(raw, reserved=RESERVED)
        if not r.ok:
            problems += [f"{path.name}: {e}" for e in r.errors]
            continue
        m = r.module
        notes += [f"{path.name}: {w}" for w in r.warnings]
        if path.name != m["id"] + fmt.SUFFIX:
            problems.append(f"{path.name}: should be called {m['id']}{fmt.SUFFIX}")
        if raw.decode("utf-8") != fmt.dumps(m):
            if fix:
                path.write_text(fmt.dumps(m), "utf-8")
                raw = path.read_bytes()
            else:
                problems.append(f"{path.name}: not in the standard layout (run: python3 tools/make_catalog.py --fix)")
        for pic in [m["icon"]] * fmt.media_path(m.get("icon")) + [i["src"] for i in m.get("images", [])]:
            f = ROOT / "modules" / pic
            if not f.is_file():
                problems.append(f"{path.name}: {pic} is missing (put it in modules/{pic})")
            elif f.stat().st_size > MAX_PICTURE:
                problems.append(f"{path.name}: {pic} is {f.stat().st_size // 1000} KB; keep pictures under "
                                f"{MAX_PICTURE // 1000} KB")
        s = fmt.summary(m)
        entries.append({**s, "file": path.name, "bytes": len(raw), "sha256": fmt.digest(raw)})
    for n in notes:
        print("note:", n)
    for p in problems:
        print("✗", p, file=sys.stderr)
    if problems:
        return 1
    entries.sort(key=lambda e: (e["group"], e["name"].lower()))
    catalog = {"format": fmt.CATALOG_FORMAT, "version": 1, "repo": REPO,
               "groups": sorted({e["group"] for e in entries}), "modules": entries}
    text = json.dumps(catalog, ensure_ascii=False, indent=1) + "\n"
    targets = [ROOT / "modules" / "catalog.json", ROOT / "docs" / "catalog.json"]
    if check:
        stale = [str(t.relative_to(ROOT)) for t in targets if not t.exists() or t.read_text("utf-8") != text]
        if stale:
            print(f"✗ out of date: {', '.join(stale)} (run: python3 tools/make_catalog.py)", file=sys.stderr)
            return 1
        print(f"✓ {len(entries)} modules; the catalog is up to date")
        return 0
    for t in targets:
        t.write_text(text, "utf-8")
    print(f"✓ wrote {len(entries)} modules to modules/catalog.json and docs/catalog.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
