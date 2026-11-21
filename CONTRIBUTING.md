# Adding a module

1. Write a pack. Start from one in `modules/`, or export your own in Vectiq: **Marketplace → Import & export → Export a module** (or `vectiq --pack-export NAME --out file.vqmodule.json`). The format is in [SPEC.md](SPEC.md).
2. Save it as `modules/<id>.vqmodule.json`. The file name is the pack's `id`.
3. Run `python3 tools/build_catalog.py --fix`, which checks the pack, tidies its layout and rewrites `catalog.json`. It needs only Python 3.
4. Open a pull request. CI runs `python3 tools/build_catalog.py --check`.

## What makes a pack welcome

- **Say what it does** in `help` (one line) and `description` (a short paragraph), and fill in `author`, `license` and `tags`.
- **Put what people will want to change in `settings`**, not in the replies: channel names, links, text. Reference them as `{cfg.name}`.
- **No surprises.** A pack must do what its description says and nothing else. Packs that collect or send data somewhere must say so in the description.
- **Prefer data over code.** Commands, auto-replies, scheduled posts and presets cover most needs and can't run anything. Packs with `code` are reviewed line by line before they are merged, and people only get them if they've allowed code.
- **Presets** may not touch owners, the dashboard, MCP, webhooks, plugin folders or anything that looks like a secret. The validator enforces it.
- **Bump `version`** when you change a pack. Vectiq shows an Update button when the file's checksum changes.

## The validator

`tools/vectiq_spec.py` is a copy of the checker Vectiq itself uses, so a pack that passes here is accepted by the bot. Refresh it from a Vectiq checkout with `tools/sync_spec.sh path/to/aio-vector-bot`.
