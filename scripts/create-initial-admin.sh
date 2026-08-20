#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: ./scripts/create-initial-admin.sh \\" >&2
  echo "  --namespace <name> \\" >&2
  echo "  --enterprise-name <name> \\" >&2
  echo "  --enterprise-domain <domain> \\" >&2
  echo "  --email <address> \\" >&2
  echo "  --name <administrator-name>" >&2
}

namespace=""
enterprise_name=""
enterprise_domain=""
admin_email=""
admin_name=""

while (($# > 0)); do
  case "$1" in
    --namespace)
      [[ $# -ge 2 && -n "$2" ]] || {
        echo "ERROR: --namespace requires a value." >&2
        exit 2
      }
      namespace=$2
      shift 2
      ;;
    --enterprise-name)
      [[ $# -ge 2 && -n "$2" ]] || {
        echo "ERROR: --enterprise-name requires a value." >&2
        exit 2
      }
      enterprise_name=$2
      shift 2
      ;;
    --enterprise-domain)
      [[ $# -ge 2 && -n "$2" ]] || {
        echo "ERROR: --enterprise-domain requires a value." >&2
        exit 2
      }
      enterprise_domain=$2
      shift 2
      ;;
    --email)
      [[ $# -ge 2 && -n "$2" ]] || {
        echo "ERROR: --email requires a value." >&2
        exit 2
      }
      admin_email=$2
      shift 2
      ;;
    --name)
      [[ $# -ge 2 && -n "$2" ]] || {
        echo "ERROR: --name requires a value." >&2
        exit 2
      }
      admin_name=$2
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

missing=()
[[ -n "$namespace" ]] || missing+=(--namespace)
[[ -n "$enterprise_name" ]] || missing+=(--enterprise-name)
[[ -n "$enterprise_domain" ]] || missing+=(--enterprise-domain)
[[ -n "$admin_email" ]] || missing+=(--email)
[[ -n "$admin_name" ]] || missing+=(--name)
if ((${#missing[@]} > 0)); then
  echo "ERROR: required arguments are missing:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  usage
  exit 2
fi

if [[ ! "$namespace" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
  echo "ERROR: namespace must be a valid lowercase Kubernetes DNS label." >&2
  exit 2
fi
if [[ "$enterprise_domain" =~ [[:space:]] ]]; then
  echo "ERROR: enterprise domain must not contain whitespace." >&2
  exit 2
fi
if [[ ! "$admin_email" =~ ^[^[:space:]@]+@[^[:space:]@]+$ ]]; then
  echo "ERROR: administrator email is invalid." >&2
  exit 2
fi
if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: required command is not installed: kubectl" >&2
  exit 1
fi

context=$(kubectl config current-context 2>/dev/null || true)
if [[ -z "$context" ]]; then
  echo "ERROR: kubectl has no current context." >&2
  exit 1
fi
if ! kubectl get namespace "$namespace" >/dev/null 2>&1; then
  echo "ERROR: namespace does not exist: $namespace" >&2
  exit 1
fi
if ! kubectl -n "$namespace" get deployment/phoenix-web >/dev/null 2>&1; then
  echo "ERROR: deployment/phoenix-web does not exist in namespace $namespace." >&2
  exit 1
fi
if ! kubectl -n "$namespace" wait \
    --for=condition=Available deployment/phoenix-web --timeout=300s >/dev/null; then
  echo "ERROR: deployment/phoenix-web is not available in namespace $namespace." >&2
  exit 1
fi

echo "Kubernetes context: $context"
echo "Namespace:          $namespace"
echo "Enterprise:         $enterprise_name"
echo "Primary domain:     $enterprise_domain"
echo "Administrator:      $admin_email"

printf 'Initial administrator password: ' >&2
if ! IFS= read -r -s admin_password; then
  printf '\n' >&2
  echo "ERROR: could not read the administrator password." >&2
  exit 1
fi
printf '\n' >&2
trap 'unset admin_password admin_password_confirmation' EXIT
if [[ -z "$admin_password" ]]; then
  echo "ERROR: administrator password must not be empty." >&2
  exit 1
fi

printf 'Confirm administrator password: ' >&2
if ! IFS= read -r -s admin_password_confirmation; then
  printf '\n' >&2
  echo "ERROR: could not read the password confirmation." >&2
  exit 1
fi
printf '\n' >&2
if [[ "$admin_password" != "$admin_password_confirmation" ]]; then
  echo "ERROR: administrator passwords do not match." >&2
  exit 1
fi
unset admin_password_confirmation

printf '%s' "$admin_password" | kubectl -n "$namespace" exec -i \
  deployment/phoenix-web -- env \
  ENTERPRISE_NAME="$enterprise_name" \
  ENTERPRISE_PRIMARY_DOMAIN="$enterprise_domain" \
  INITIAL_ADMIN_EMAIL="$admin_email" \
  INITIAL_ADMIN_NAME="$admin_name" \
  /rails/bin/rails runner '
    password = STDIN.read
    raise "Initial administrator password is empty" if password.empty?

    ApplicationRecord.transaction do
      enterprise = Enterprise.first || Enterprise.create!(
        name: ENV.fetch("ENTERPRISE_NAME"),
        primary_domain: ENV.fetch("ENTERPRISE_PRIMARY_DOMAIN")
      )
      email = ENV.fetch("INITIAL_ADMIN_EMAIL").downcase
      administrator = User.find_by(email: email)
      if administrator
        unless administrator.enterprise_id == enterprise.id && administrator.enterprise_role == "owner"
          raise "Existing administrator is not an owner of this Enterprise"
        end
        puts "Initial administrator already exists"
      else
        if User.exists?
          raise "Other users already exist; refusing initial-owner bootstrap"
        end
        User.create!(
          email: email,
          name: ENV.fetch("INITIAL_ADMIN_NAME"),
          password: password,
          password_confirmation: password,
          enterprise: enterprise,
          enterprise_role: :owner
        )
        puts "Initial administrator created"
      end
    end
  '
