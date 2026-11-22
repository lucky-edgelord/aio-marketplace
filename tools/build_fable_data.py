#!/usr/bin/env python3
"""Build sources/fable/code/characters.json: the most-liked characters on AniList, ranked into 1-5 stars.

    python3 tools/build_fable_data.py [COUNT]        (default 2500; needs internet, takes a couple of minutes)

Run by a maintainer when the list should be refreshed. The Fable module reads the JSON and never calls AniList
itself; only the picture files are fetched later, from AniList's image host. Rows: [id, name, series, picture, stars].
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

URL = "https://graphql.anilist.co"
HOST = "https://s4.anilist.co/file/anilistcdn/character/large/"
QUERY = """query($page:Int){Page(page:$page,perPage:50){characters(sort:FAVOURITES_DESC){id name{full}
image{large} media(perPage:1,sort:POPULARITY_DESC){nodes{title{english romaji}}}}}}"""
#: ranks (best first) that get each star count: 5* the top 4%, then 10%, 24%, 32%, the rest
BANDS = [(0.04, 5), (0.14, 4), (0.38, 3), (0.70, 2)]


def fetch(page: int) -> list:
    body = json.dumps({"query": QUERY, "variables": {"page": page}}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json", "User-Agent": "aio-marketplace"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)["data"]["Page"]["characters"]
        except Exception as e:  # noqa: BLE001
            print("retry", page, e, file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"page {page} failed")


def main(count: int) -> None:
    rows, seen = [], set()
    for page in range(1, count // 50 + 2):
        for c in fetch(page):
            img = (c["image"] or {}).get("large") or ""
            nodes = (c["media"] or {}).get("nodes") or []
            if c["id"] in seen or not img.startswith(HOST) or not nodes:
                continue
            seen.add(c["id"])
            t = nodes[0]["title"]
            rows.append([c["id"], c["name"]["full"].strip(), (t.get("english") or t.get("romaji") or "").strip(), img[len(HOST):]])
        time.sleep(1.1)
        if len(rows) >= count:
            break
    rows = rows[:count]
    for i, row in enumerate(rows):
        share = i / len(rows)
        row.append(next((s for edge, s in BANDS if share < edge), 1) if share >= 0 else 1)
    out = Path(__file__).resolve().parent.parent / "sources" / "fable" / "code" / "characters.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"host": HOST, "rows": rows}, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1000} KB, {len(rows)} characters)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2500)
