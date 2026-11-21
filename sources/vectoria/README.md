# Vectoria (source)

The readable source of `modules/vectoria.module.json`. Edit the files in `code/` or the metadata in `module.json`, bump `release`, then:

```sh
python3 tools/pack.py vectoria && python3 tools/make_catalog.py --fix
```

- `cog.py`: chat commands (`!vec`, `!vectoria`, `!vecmemory`, `!vecforget`, `!vecface`, `!vecvoice`), replies, votes and her dashboard page.
- `brain.py`: Ollama chat with web search and fetch, her notes (`kb_*.md`), per-person memory (SQLite in `<data>/vectoria/`).
- `video.py`: SAM voice (built on the bot's computer by `!vecvoice`, never bundled: it has no licence), lip-sync, VHS look, subtitles.
- `assets.json`: her four sprites (WebP) and the Press Start 2P font (SIL OFL, unmodified; licence in `OFL.txt`).
- `persona.md`: who she is. The text and video modes add their own instructions in `brain.py`.
