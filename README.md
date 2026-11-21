# aio-marketplace

Modules for [Vectiq](https://github.com/lucky-edgelord/aio-vector-bot), the all-in-one bot for [Vector](https://vectorapp.io) communities. Each module is **one JSON file**.

**Browse:** <https://lucky-edgelord.github.io/aio-marketplace/> · **Install:** Vectiq dashboard → **Marketplace** → Browse → Install

| Module | What it does | Kind |
|---|---|---|
| `server_rules` | A `!rules` command, and a nudge when someone asks about the rules. | ready to use |
| `faq_helper` | `!invite`, `!support`, `!links` and answers to the questions newcomers always ask. | ready to use |
| `daily_question` | A conversation starter posted every day at a time you choose, and `!question`. | ready to use |
| `magic_8ball` | `!8ball`, `!coin` and `!dice`. | ready to use |
| `community_starter` | Switches on the modules most communities want on day one and sets calm defaults. | preset |
| `ai_automod` | An AI model reads each message against your rules. Works with Ollama, OpenAI or any compatible API. | runs code |

*Ready to use* modules are data: commands, auto-replies and scheduled posts that Vectiq knows how to run, with no code. *Presets* are settings you preview before applying. *Runs code* modules contain Python that runs on the bot's computer; Vectiq only installs them when its owner has turned on **Allow packs with code**.

## How it works

- `modules/*.vqmodule.json` are the packs. The format is described in [SPEC.md](SPEC.md) and in the [Vectiq docs](https://lucky-edgelord.github.io/aio-vector-bot/module-packs.html).
- `catalog.json` lists every pack with its SHA-256. Vectiq checks each file against it before reading it, and only talks to `raw.githubusercontent.com`. Don't edit it by hand: `python3 tools/build_catalog.py` writes it.
- `docs/` is the website (GitHub Pages: branch `main`, folder `/docs`).

## Without the dashboard

```
curl -LO https://raw.githubusercontent.com/lucky-edgelord/aio-marketplace/main/modules/server_rules.vqmodule.json
vectiq --pack-check server_rules.vqmodule.json
vectiq --pack-install server_rules.vqmodule.json
```

then `!module scan` and `!module on server_rules` in chat.

## Adding yours

See [CONTRIBUTING.md](CONTRIBUTING.md). Licence: MIT.
