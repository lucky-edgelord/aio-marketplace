#!/usr/bin/env python3
"""Build modules/<id>.module.json from sources/<id>/: module.json (everything but code) plus the files in code/.

    python3 tools/pack.py vectoria       then: python3 tools/make_catalog.py --fix

For code modules that are easier to edit as normal files. Needs only Python 3.9+.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(mid: str) -> None:
    src = ROOT / "sources" / mid
    module = json.loads((src / "module.json").read_text("utf-8"))
    files = {p.relative_to(src / "code").as_posix(): p.read_text("utf-8")
             for p in sorted((src / "code").rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
    module["code"] = {"entry": module.pop("entry", "cog"), "files": files}
    out = ROOT / "modules" / f"{mid}.module.json"
    out.write_text(json.dumps(module, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1000} KB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__))
