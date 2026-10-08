#!/usr/bin/env bash
# Preserve both image bytes and signed evidence, then verify at the destination.
set -euo pipefail
source_ref=${1:?source required}
target_ref=${2:?target required}
tools_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source_digest=$(crane digest "$source_ref")
source_ref="${source_ref%@*}@$source_digest"
identity_args=()
if [[ -n "${PHOENIX_SBOM_IDENTITY:-}" ]]; then identity_args+=(--identity "$PHOENIX_SBOM_IDENTITY"); fi
python3 "$tools_dir/verify.py" "$source_ref" "${identity_args[@]}"
existing=$(crane digest "$target_ref" 2>/dev/null || true)
if [[ -n "$existing" && "$existing" != "$source_digest" ]]; then
  echo "Refusing to replace an existing image with different bytes: $target_ref" >&2
  exit 1
fi
# cosign copy includes legacy sig/att/sbom attachments. Recursive OCI referrer
# copying is also required by registries using the new referrer layout.
cosign copy "$source_ref" "$target_ref"
oras cp --recursive "$source_ref" "$target_ref"
[[ "$(crane digest "$target_ref")" == "$source_digest" ]] || { echo 'Mirror digest mismatch' >&2; exit 1; }
python3 "$tools_dir/verify.py" "$target_ref@$source_digest" "${identity_args[@]}"
