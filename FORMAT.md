# The module format (version 1)

A module is a UTF-8 JSON object in a file called `<id>.module.json`, up to 1 MB. The full guide, with examples, is in the [Vectiq docs](https://lucky-edgelord.github.io/aio-vector-bot/json-modules.html). [`template.module.json`](template.module.json) shows every part except code.

| Key | |
|---|---|
| `format`, `version` | `"vectiq-module"` and `1`. |
| `id` | 2–32 of `a-z 0-9 _`, starting with a letter; not a built-in module's name. Made from `name` if missing. |
| `name`, `summary`, `group`, `release` | What it's called, one line about it, where it's listed (Community, Fun, Members, Safety, Integrations), and its version (`1.2.0`). |
| `description`, `author`, `license`, `homepage`, `tags` | Shown in the marketplace. |
| `provides` | A job it does instead of a built-in module, like `automod`. Only one module does each job. |
| `settings` | `[{ "key", "label", "type", "default", "help", "options", "min", "max", "private" }]`. Types: `text` `longtext` `int` `number` `bool` `channel` `enum` `list`. Editable on the dashboard; `private` ones (and keys that look like tokens or passwords) are never exported. |
| `commands` | `{ "name", "aliases", "help", "reply" or "replies", "card": {"title", "color"}, "react", "cooldown", "roles", "channels", "dm", "delete_trigger" }` |
| `autoresponders` | `{ "match": contains / word / exact / startswith / endswith, "phrases", "reply" or "replies", "react", "cooldown", "roles", "channels" }` |
| `timers` | `{ "channel", "every_minutes" or "at": "18:30", "timezone", "order": random / in_turn, "replies", "card" }` |
| `code` | `{ "entry": "cog", "files": { "cog.py": "…" }, "packages": { "httpx": "httpx>=0.27" } }`. Python whose `entry` module has `setup(bot)`. Needs *Allow modules with code*. |

Text can use `{user}` `{mention}` `{args}` `{channel}` `{community}` `{members}` `{prefix}` and `{settings.key}`. Nothing else in braces is interpreted.

The checker is forgiving: a broken command, autoresponder or timer is skipped with a note; only problems that make the module unusable are errors.
