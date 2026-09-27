#!/usr/bin/env bash
set -Eeuo pipefail

API_BASE_URL="${API_BASE_URL:-}"
SMOKE_ACCESS_TOKEN="${SMOKE_ACCESS_TOKEN:-}"
SMOKE_EMAIL="${SMOKE_EMAIL:-}"
SMOKE_PASSWORD="${SMOKE_PASSWORD:-}"

if [[ ! "$API_BASE_URL" =~ ^https:// ]]; then
  echo "API_BASE_URL must be a production HTTPS origin" >&2
  exit 2
fi
API_BASE_URL="${API_BASE_URL%/}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

health_code="$(curl --silent --show-error --output "$tmp_dir/health.json" --write-out '%{http_code}'   "$API_BASE_URL/health")"
[[ "$health_code" == "200" ]]
python3 - "$tmp_dir/health.json" <<'PY'
import json, sys
body = json.load(open(sys.argv[1], encoding="utf-8"))
assert body.get("status") == "ok"
PY

dev_code="$(curl --silent --show-error --output "$tmp_dir/dev.json" --write-out '%{http_code}'   --request POST "$API_BASE_URL/v1/auth/dev-token"   --header 'Content-Type: application/json'   --data '{"nickname":"production-smoke"}')"
[[ "$dev_code" == "404" ]]

# The public auth routes must exist even when we intentionally submit invalid bodies.
register_code="$(curl --silent --show-error --output "$tmp_dir/register.json" --write-out '%{http_code}'   --request POST "$API_BASE_URL/v1/auth/register"   --header 'Content-Type: application/json'   --data '{}')"
[[ "$register_code" == "422" ]]

login_reachability_code="$(curl --silent --show-error --output "$tmp_dir/login-reachability.json" --write-out '%{http_code}'   --request POST "$API_BASE_URL/v1/auth/login"   --header 'Content-Type: application/json'   --data '{}')"
[[ "$login_reachability_code" == "422" ]]

invalid_code="$(curl --silent --show-error --output "$tmp_dir/invalid.json" --write-out '%{http_code}'   "$API_BASE_URL/v1/user"   --header 'Authorization: Bearer definitely-invalid-production-token')"
[[ "$invalid_code" == "401" || "$invalid_code" == "403" ]]

if [[ -z "$SMOKE_ACCESS_TOKEN" ]]; then
  if [[ -z "$SMOKE_EMAIL" || -z "$SMOKE_PASSWORD" ]]; then
    echo "set SMOKE_ACCESS_TOKEN or both SMOKE_EMAIL and SMOKE_PASSWORD" >&2
    exit 3
  fi

  python3 - "$tmp_dir/login.json" <<'PY'
import json, os, sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(
        {"email": os.environ["SMOKE_EMAIL"], "password": os.environ["SMOKE_PASSWORD"]},
        handle,
    )
PY

  login_code="$(curl --silent --show-error --output "$tmp_dir/login-response.json" --write-out '%{http_code}'     --request POST "$API_BASE_URL/v1/auth/login"     --header 'Content-Type: application/json'     --data-binary "@$tmp_dir/login.json")"
  [[ "$login_code" == "200" ]]
  SMOKE_ACCESS_TOKEN="$(python3 - "$tmp_dir/login-response.json" <<'PY'
import json, sys
body = json.load(open(sys.argv[1], encoding="utf-8"))
token = body.get("access_token")
assert isinstance(token, str) and token
print(token)
PY
)"
fi

user_code="$(curl --silent --show-error --output "$tmp_dir/user.json" --write-out '%{http_code}'   "$API_BASE_URL/v1/user"   --header "Authorization: Bearer $SMOKE_ACCESS_TOKEN")"
[[ "$user_code" == "200" ]]

echo "production smoke PASS"
