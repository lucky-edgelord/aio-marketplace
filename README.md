# aio-marketplace

Modules for [Vectiq](https://github.com/lucky-edgelord/aio-vector-bot), the all-in-one bot for [Vector](https://vectorapp.io) communities. A module is **one JSON file**: commands, autoresponders and timers that Vectiq runs for you, and sometimes a little Python.

**Website:** <https://lucky-edgelord.github.io/aio-marketplace/>

## Getting a module

| Where | How |
|---|---|
| Dashboard | **Marketplace → Browse**, then **Get**. You see what a module does before it's added. |
| Chat (owners) | `!module market` lists them, `!module get server_rules` adds one and switches it on. |
| Terminal | Download the file, then `vectiq --import-module server_rules.module.json`. |

| Module | What it does |
|---|---|
| `server_rules` | `!rules` shows your rules as a card, and the bot points people to it when they ask. |
| `faq_helper` | `!invite`, `!support`, `!links`, with answers for the questions newcomers ask. |
| `daily_question` | A conversation starter every day at your time, and `!question`. |
| `magic_8ball` | `!8ball`, `!coin` and `!dice`. |
| `good_vibes` | Reacts to good mornings, thanks and congratulations; `!hug` and `!highfive`. |
| `vectoria` | Vectoria, a talking pixel-art expert on Vector bots and WebXDC: `!vec` answers in text, `!vectoria` in a lip-synced video. **Runs code.** |
| `ai_automod` | An AI model checks messages against your rules (Ollama, OpenAI or any compatible API). **Runs code.** |

Modules without code only do what Vectiq knows how to do with data: answer commands, reply or react to phrases, and post on a timer. Modules marked **runs code** carry Python that runs on the bot's computer; Vectiq only installs them when its owner turns on *Settings → Marketplace → Allow modules with code*.

## How it works

Like the course library of [Lilith Learning Lab](https://github.com/lucky-edgelord/Lilith-Learning-Lab):

- `modules/*.module.json` are the modules. The format is in [FORMAT.md](FORMAT.md).
- `modules/catalog.json` lists them, with each file's SHA-256. Vectiq reads only from `raw.githubusercontent.com` and refuses a file that doesn't match its checksum. `python3 tools/make_catalog.py` writes the catalog; don't edit it by hand.
- `docs/` is the website (GitHub Pages: branch `main`, folder `/docs`).

Any repository with the same layout is a marketplace: point *Settings → Marketplace* at it.

## Making one

See [CONTRIBUTING.md](CONTRIBUTING.md): start from [`template.module.json`](template.module.json), or ask an AI to write one. Licence: MIT.
