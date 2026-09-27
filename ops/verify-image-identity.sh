#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE_REF="${1:-}"
EXPECTED_SHA="${2:-}"

if [[ -z "$IMAGE_REF" || ! "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 <image-ref> <full-40-char-git-sha>" >&2
  exit 2
fi

revision="$(docker image inspect "$IMAGE_REF" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
image_id="$(docker image inspect "$IMAGE_REF" --format '{{.Id}}')"

if [[ "$revision" != "$EXPECTED_SHA" ]]; then
  echo "image revision label mismatch: $revision != $EXPECTED_SHA" >&2
  exit 3
fi
if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "image does not have an immutable sha256 image ID: $image_id" >&2
  exit 3
fi
if [[ -n "${EXPECTED_IMAGE_ID:-}" && "$image_id" != "$EXPECTED_IMAGE_ID" ]]; then
  echo "image ID mismatch: $image_id != $EXPECTED_IMAGE_ID" >&2
  exit 3
fi

echo "release image PASS"
echo "IMAGE_REF=$IMAGE_REF"
echo "RELEASE_SHA=$EXPECTED_SHA"
echo "IMAGE_ID=$image_id"
