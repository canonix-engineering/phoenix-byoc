#!/usr/bin/env bash
set -euo pipefail

environment=default
while (($# > 0)); do
  case "$1" in
    --environment)
      environment=${2:-}
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"

(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" helmfile --environment "$environment" status
)
