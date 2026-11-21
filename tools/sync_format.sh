#!/bin/sh
# Refresh the checker and the list of built-in module names from a checkout of aio-vector-bot:
#   tools/sync_format.sh ../aio-vector-bot
set -e
src="${1:?give the path to an aio-vector-bot checkout}"
here="$(cd "$(dirname "$0")" && pwd)"
{ echo "# Copied unchanged from aio-vector-bot (src/vectiq/jsonmods/fmt.py) by tools/sync_format.sh. Don't edit it here."
  cat "$src/src/vectiq/jsonmods/fmt.py"; } > "$here/module_format.py"
PYTHONPATH="$src/src" python3 -c "
import json, sys
from vectiq import modules
open(sys.argv[1], 'w').write(json.dumps(sorted(m.name for m in modules.BUILTIN), indent=1) + '\n')" "$here/reserved.json"
echo "updated tools/module_format.py and tools/reserved.json"
