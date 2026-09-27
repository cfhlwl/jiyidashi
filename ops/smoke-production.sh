#!/usr/bin/env bash
set -Eeuo pipefail

API_BASE_URL="${API_BASE_URL:-}"
SMOKE_ACCESS_TOKEN="${SMOKE_ACCESS_TOKEN:-}"

if [[ ! "$API_BASE_URL" =~ ^https:// ]]; then
  echo "API_BASE_URL must be a production HTTPS origin" >&2
  exit 2
fi
API_BASE_URL="${API_BASE_URL%/}"

status() {
  curl --silent --show-error --output "$2" --write-out '%{http_code}' "$1" "${@:3}"
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

health_code="$(status "$API_BASE_URL/health" "$tmp_dir/health.json")"
[[ "$health_code" == "200" ]]
python3 - "$tmp_dir/health.json" <<'PY'
import json, sys
body=json.load(open(sys.argv[1], encoding="utf-8"))
assert body.get("status") == "ok"
PY

dev_code="$(curl --silent --show-error --output "$tmp_dir/dev.json" --write-out '%{http_code}'   --request POST "$API_BASE_URL/v1/auth/dev-token"   --header 'Content-Type: application/json'   --data '{"nickname":"production-smoke"}')"
[[ "$dev_code" == "404" ]]

register_code="$(curl --silent --show-error --output "$tmp_dir/register.json" --write-out '%{http_code}'   --request POST "$API_BASE_URL/v1/auth/register"   --header 'Content-Type: application/json'   --data '{}')"
[[ "$register_code" == "422" ]]

login_code="$(curl --silent --show-error --output "$tmp_dir/login.json" --write-out '%{http_code}'   --request POST "$API_BASE_URL/v1/auth/login"   --header 'Content-Type: application/json'   --data '{}')"
[[ "$login_code" == "422" ]]

invalid_code="$(curl --silent --show-error --output "$tmp_dir/invalid.json" --write-out '%{http_code}'   "$API_BASE_URL/v1/user"   --header 'Authorization: Bearer definitely-invalid-production-token')"
[[ "$invalid_code" == "401" || "$invalid_code" == "403" ]]

if [[ -z "$SMOKE_ACCESS_TOKEN" ]]; then
  echo "SMOKE_ACCESS_TOKEN is required for authenticated /v1/user acceptance" >&2
  exit 3
fi

user_code="$(curl --silent --show-error --output "$tmp_dir/user.json" --write-out '%{http_code}'   "$API_BASE_URL/v1/user"   --header "Authorization: Bearer $SMOKE_ACCESS_TOKEN")"
[[ "$user_code" == "200" ]]

echo "production smoke PASS"
