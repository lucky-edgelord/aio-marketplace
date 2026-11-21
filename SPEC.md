# Module pack format, version 1

A module pack is a UTF-8 JSON file named `<id>.vqmodule.json`, at most 600 KB. The full reference, with examples, is in the Vectiq docs: <https://lucky-edgelord.github.io/aio-vector-bot/module-packs.html>.

```json
{
  "format": "vectiq-module",
  "spec": 1,
  "id": "server_rules",
  "label": "Server rules",
  "help": "One line about it",
  "group": "Community",
  "version": "1.0.0",
  "author": "you",
  "license": "MIT",
  "tags": ["rules"],
  "settings": { "defaults": { "rules": "Be kind." },
                "fields": [ { "key": "rules", "label": "The rules", "type": "longtext" } ] },
  "commands": [ { "name": "rules", "help": "Show the rules", "reply": "{cfg.rules}" } ]
}
```

| Key | |
|---|---|
| `format`, `spec` | `"vectiq-module"` and `1`. |
| `id` | 2–32 of `a-z 0-9 _`, starting with a letter. Not a built-in module's name. |
| `label`, `help`, `group`, `version` | Required. `version` is `1.2.3`. |
| `author`, `license`, `homepage`, `tags`, `description`, `provides` | Optional. |
| `settings` | `defaults` and `fields` (`key`, `label`, `type`, `help`, `options`). Types: `text` `longtext` `int` `number` `bool` `channel` `enum` `list`. |
| `commands` | `name`, `aliases`, `help`, `reply` or `replies`, `embed`, `cooldown`, `roles`, `channels`, `dm`, `delete_invocation`. |
| `triggers` | `match` (`contains` `word` `exact` `startswith` `endswith`), `phrases`, `reply`/`replies`, `react`, `cooldown`, `channels`, `roles`. |
| `schedules` | `channel`, `every_minutes` or `daily_at`, `timezone`, `order`, `reply`/`replies`, `embed`. |
| `preset` | `config` (setting path → value) and `modules` (name → on/off). Never applied without a preview. |
| `code` | `files` (path → text) with an `__init__.py` that defines `MODULE` and `setup(bot)`. Can't be combined with commands, triggers or schedules. |

Replies may use `{user}` `{mention}` `{args}` `{channel}` `{community}` `{members}` `{prefix}` and `{cfg.<setting>}`. Nothing else is interpreted.

A pack must do something: have commands, triggers, schedules, a preset or code.
