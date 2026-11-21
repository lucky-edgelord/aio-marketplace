# Adding a module

1. **Write it.** Start from [`template.module.json`](template.module.json), export one from Vectiq (*Marketplace → Installed → Export*, or `vectiq --export-module NAME`), or ask an AI with the prompt below. *Marketplace → Add a module* on the dashboard checks a module as you type.
2. **Save it** as `modules/<id>.module.json` (the file name is its `id`).
3. **Run** `python3 tools/make_catalog.py --fix`. It checks every module, tidies the layout and rewrites the catalog. Only Python 3 is needed.
4. **Open a pull request.** CI runs `python3 tools/make_catalog.py --check`.

## What makes a good module

- One clear job, said in `summary` (one line) and `description` (a short paragraph). Fill in `author`, `license` and `tags`.
- **Show it.** Give it an `icon` (an emoji, or a square picture) and, if you can, `images`: screenshots or a short animated preview of it working. Put pictures in `modules/media/<id>/` and refer to them as `media/<id>/name.png`. The first image is the card's cover, so make it 16:9.
- Anything a community will want to change (texts, links, channel names, times) goes in `settings` and is used as `{settings.key}`. People edit settings on the dashboard.
- Sensible cooldowns on commands and autoresponders, so a busy channel isn't flooded.
- **Prefer data to code.** Modules with `code` are read line by line before they're merged, and must say in their description what they send where.
- Bump `release` when you change a module: Vectiq shows **Update** when the file changes.

## Asking an AI to write one

Paste this into Claude (or another AI), add what you want at the end, and paste its answer into *Marketplace → Add a module*:

```text
Write a Vectiq module as one JSON file. Vectiq is a bot for Vector messenger communities.

Use exactly this shape (no comments, no trailing commas, nothing before or after the JSON):
{"format":"vectiq-module","version":1,"id":"lowercase_id","name":"Name","summary":"One line","group":"Community|Fun|Members|Safety|Integrations","release":"1.0.0","author":"","license":"MIT","tags":["..."],
 "settings":[{"key":"name","label":"Label","type":"text|longtext|int|number|bool|channel|enum|list","default":...,"help":"","options":["for enum"]}],
 "commands":[{"name":"cmd","aliases":[],"help":"what it does","reply":"text" OR "replies":["one is picked at random"],"card":{"title":"optional: show as a card","color":"#59fcb3"},"react":["emoji"],"cooldown":3,"roles":["only these roles"],"channels":["only these channels"],"dm":false,"delete_trigger":false}],
 "autoresponders":[{"match":"contains|word|exact|startswith|endswith","phrases":["..."],"reply":"..." OR "replies":[...],"react":["emoji"],"cooldown":60,"channels":[]}],
 "timers":[{"channel":"channel name or {settings.key}","every_minutes":60 OR "at":"18:30","timezone":"Europe/London","order":"random|in_turn","replies":["..."],"card":{"title":"..."}}]}

In any text you may use {user} {mention} {args} (what followed the command) {channel} {community} {members} {prefix} and {settings.key}.
Put anything a community would want to change (texts, links, channel names, times) in "settings" and refer to it with {settings.key}.
Keep replies short and friendly. Commands are lowercase. Do not include "code".
The module I want:
```

## The checker

`tools/module_format.py` is an unchanged copy of the checker Vectiq itself uses, so a module that passes here is accepted by the bot. Refresh it with `tools/sync_format.sh path/to/aio-vector-bot`.
