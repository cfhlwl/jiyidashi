#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_REF="${1:-}"
EXPECTED_SHA="${2:-}"
STATE_DIR="${RELEASE_IMAGE_STATE_DIR:-$ROOT_DIR/.ops-state/release-images}"

if [[ -z "$IMAGE_REF" || ! "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 <image-ref> <full-40-char-git-sha>" >&2
  exit 2
fi

manifest="$STATE_DIR/$EXPECTED_SHA.image-id"
if [[ ! -f "$manifest" ]]; then
  echo "missing immutable release image record: $manifest" >&2
  exit 4
fi

expected_image_id="$(tr -d '\r\n' <"$manifest")"
if [[ ! "$expected_image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "invalid release image record for $EXPECTED_SHA: $expected_image_id" >&2
  exit 4
fi

if ! docker image inspect "$IMAGE_REF" >/dev/null 2>&1; then
  echo "recorded release image is not retained locally: $IMAGE_REF" >&2
  echo "refusing to resolve a mutable registry tag during rollback/reuse" >&2
  exit 5
fi

EXPECTED_IMAGE_ID="$expected_image_id" \
  bash "$ROOT_DIR/ops/verify-image-identity.sh" "$IMAGE_REF" "$EXPECTED_SHA"

echo "recorded release image PASS"
echo "RELEASE_IMAGE_RECORD=$manifest"
