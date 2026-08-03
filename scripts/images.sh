#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
release_file="$repo_root/release.yaml"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/images.sh list [--registry <registry/path>]
  ./scripts/images.sh verify [--registry <registry/path>]
  ./scripts/images.sh ecr-login [--profile <aws-profile>]
  ./scripts/images.sh mirror --to <registry/path> [--source-ecr-profile <aws-profile>] [--dry-run]

Commands:
  list     Print the nine Phoenix runtime image references.
  verify   Resolve every image with crane and fail if one is unavailable.
  ecr-login
           Authenticate crane to the release's source Amazon ECR registry.
  mirror   Copy every image to another registry, preserving names and tags.

Authenticate to private source or destination registries before running
verify or mirror. For the Phoenix source ECR, either run ecr-login first or pass
--source-ecr-profile to mirror. The optional registry may include a path, for example:
registry.customer.example/phoenix
EOF
}

read_images() {
  awk '
    /^images:$/ { in_images=1; next }
    in_images && /^[^ ]/ { exit }
    in_images && /^    name:/ {
      name=$2
      gsub(/"/, "", name)
    }
    in_images && /^    repository:/ {
      repository=$2
      gsub(/"/, "", repository)
    }
    in_images && /^    tag:/ {
      tag=$2
      gsub(/"/, "", tag)
      print name "\t" repository ":" tag "\t" tag
    }
  ' "$release_file"
}

source_ecr_registry() {
  local source_registry=""
  local current_registry
  local name
  local source
  local tag

  while IFS=$'\t' read -r name source tag; do
    current_registry=${source%%/*}
    if [[ -z "$source_registry" ]]; then
      source_registry=$current_registry
    elif [[ "$current_registry" != "$source_registry" ]]; then
      echo "ERROR: release images use more than one source registry." >&2
      return 1
    fi
  done < <(read_images)

  if [[ ! "$source_registry" =~ ^[0-9]{12}\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com$ ]]; then
    echo "ERROR: release source is not a supported Amazon ECR registry: $source_registry" >&2
    return 1
  fi

  printf '%s\t%s\n' "$source_registry" "${BASH_REMATCH[1]}"
}

login_source_ecr() {
  local profile=${1:-}
  local source_registry
  local region
  local aws_args=()

  command -v aws >/dev/null 2>&1 || {
    echo "ERROR: AWS CLI is required for source ECR authentication." >&2
    return 1
  }
  command -v crane >/dev/null 2>&1 || {
    echo "ERROR: crane is required for source ECR authentication." >&2
    return 1
  }

  IFS=$'\t' read -r source_registry region < <(source_ecr_registry)
  if [[ -n "$profile" ]]; then
    aws_args+=(--profile "$profile")
  fi

  aws "${aws_args[@]}" ecr get-login-password --region "$region" |
    crane auth login "$source_registry" --username AWS --password-stdin
  echo "Authenticated crane to $source_registry using a short-lived ECR token."
}

command=${1:-}
shift || true
registry=""
destination=""
dry_run=false
aws_profile=""
source_ecr_profile=""

while (($# > 0)); do
  case "$1" in
    --registry)
      registry=${2:-}
      shift 2
      ;;
    --to)
      destination=${2:-}
      shift 2
      ;;
    --profile)
      aws_profile=${2:-}
      shift 2
      ;;
    --source-ecr-profile)
      source_ecr_profile=${2:-}
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

registry=${registry%/}
destination=${destination%/}

case "$command" in
  list)
    while IFS=$'\t' read -r name source tag; do
      if [[ -n "$registry" ]]; then
        printf '%s/%s:%s\n' "$registry" "$name" "$tag"
      else
        printf '%s\n' "$source"
      fi
    done < <(read_images)
    ;;
  verify)
    command -v crane >/dev/null 2>&1 || {
      echo "ERROR: crane is required for image verification." >&2
      exit 1
    }
    while IFS=$'\t' read -r name source tag; do
      reference=$source
      if [[ -n "$registry" ]]; then
        reference="$registry/$name:$tag"
      fi
      digest=$(crane digest "$reference")
      printf '%s@%s\n' "$reference" "$digest"
    done < <(read_images)
    ;;
  ecr-login)
    login_source_ecr "$aws_profile"
    ;;
  mirror)
    if [[ -z "$destination" ]]; then
      echo "ERROR: mirror requires --to <registry/path>" >&2
      exit 2
    fi
    if [[ "$dry_run" != true ]]; then
      command -v crane >/dev/null 2>&1 || {
        echo "ERROR: crane is required for image mirroring." >&2
        exit 1
      }
      if [[ -n "$source_ecr_profile" ]]; then
        login_source_ecr "$source_ecr_profile"
      fi
    fi
    while IFS=$'\t' read -r name source tag; do
      target="$destination/$name:$tag"
      if [[ "$dry_run" == true ]]; then
        printf 'crane copy %q %q\n' "$source" "$target"
      else
        echo "Copying $source -> $target"
        crane copy "$source" "$target"
      fi
    done < <(read_images)
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
