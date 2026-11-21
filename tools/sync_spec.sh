#!/bin/sh
# Refresh the validator and the list of built-in module names from a checkout of aio-vector-bot.
# Usage: tools/sync_spec.sh path/to/aio-vector-bot
set -e
src="${1:?path to the aio-vector-bot checkout}"
here="$(cd "$(dirname "$0")" && pwd)"
{ echo "# Copied from aio-vector-bot: src/vectiq/packs/spec.py. Run tools/sync_spec.sh to update it. Do not edit here."; cat "$src/src/vectiq/packs/spec.py"; } > "$here/vectiq_spec.py"
PYTHONPATH="$src/src" python3 - "$here/builtin_modules.json" <<'PY'
import json, sys
from vectiq import modules
with open(sys.argv[1], "w") as f:
    json.dump(sorted(m.name for m in modules.BUILTIN), f, indent=1)
    f.write("\n")
PY
echo "updated tools/vectiq_spec.py and tools/builtin_modules.json"
