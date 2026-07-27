#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

if [[ ! -f "$repo_root/values.yaml" ]]; then
  cp "$repo_root/config/values.example.yaml" "$repo_root/values.yaml"
  echo "Created values.yaml"
else
  echo "Keeping existing values.yaml"
fi

if [[ ! -f "$repo_root/values.secrets.yaml" ]]; then
  cp "$repo_root/config/values.secrets.example.yaml" "$repo_root/values.secrets.yaml"
  echo "Created values.secrets.yaml"
else
  echo "Keeping existing values.secrets.yaml"
fi
chmod 600 "$repo_root/values.secrets.yaml"
echo "Enforced mode 0600 on values.secrets.yaml"

echo "Edit both files, then run: ./scripts/preflight.sh"
