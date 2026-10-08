#!/usr/bin/env bash
set -euo pipefail

# Valkey 9 may expose its built-in Lua engine through MODULE LIST. Reject any
# other module, including Redis Stack modules, rather than requiring no Lua.
if ! yq -p=json --exit-status '
  (tag == "!!seq") and
  (map(select(.name != "lua" or .path != "lua" or .ver != 1 or (.args | length) != 0)) | length == 0)
' >/dev/null; then
  echo "ERROR: unexpected module loaded in bundled Valkey." >&2
  exit 1
fi
