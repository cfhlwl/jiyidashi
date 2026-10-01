#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_REF="${1:-}"
EXPECTED_SHA="${2:-}"
COMPONENT="${3:-backend}"
STATE_DIR="${RELEASE_IMAGE_STATE_DIR:-$ROOT_DIR/.ops-state/release-images}"

if [[ -z "$IMAGE_REF" || "$IMAGE_REF" == *@* || ! "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 <tagged-image-ref> <full-40-char-git-sha> [backend|edge]" >&2
  exit 2
fi

case "$COMPONENT" in
  backend)
    archive_paths=(backend)
    dockerfile="backend/Dockerfile"
    build_context="backend"
    record_suffix=""
    ;;
  edge)
    archive_paths=(admin ops)
    dockerfile="ops/Dockerfile"
    build_context="."
    record_suffix=".edge"
    ;;
  *)
    echo "unsupported release component: $COMPONENT" >&2
    exit 2
    ;;
esac

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
manifest="$STATE_DIR/$EXPECTED_SHA$record_suffix.image-id"
lock_dir="$STATE_DIR/$EXPECTED_SHA$record_suffix.lock"
candidate="${IMAGE_REF}-candidate-${BASHPID}"
build_root=""

if ! mkdir "$lock_dir" 2>/dev/null; then
  echo "release image preparation already in progress for $EXPECTED_SHA component=$COMPONENT" >&2
  exit 6
fi

cleanup() {
  docker image rm "$candidate" >/dev/null 2>&1 || true
  if [[ -n "$build_root" ]]; then
    rm -rf "$build_root"
  fi
  rmdir "$lock_dir" >/dev/null 2>&1 || true
}
trap cleanup EXIT

build_candidate() {
  build_root="$(mktemp -d "${TMPDIR:-/tmp}/jiyidashi-release-tree.XXXXXX")"

  # Build only from the reviewed Git object tree. Workstation files that are
  # untracked or ignored by Git never enter the Docker build context.
  git -C "$ROOT_DIR" archive --format=tar "$EXPECTED_SHA" "${archive_paths[@]}" \
    | tar -xf - -C "$build_root"

  test -f "$build_root/$dockerfile"

  docker build \
    --file "$build_root/$dockerfile" \
    --build-arg "RELEASE_SHA=$EXPECTED_SHA" \
    --tag "$candidate" \
    "$build_root/$build_context"

  rm -rf "$build_root"
  build_root=""
}

if [[ -f "$manifest" ]]; then
  expected_image_id="$(tr -d '\r\n' <"$manifest")"
  if [[ ! "$expected_image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "invalid immutable release image record: $manifest" >&2
    exit 4
  fi

  if docker image inspect "$IMAGE_REF" >/dev/null 2>&1; then
    RELEASE_IMAGE_STATE_DIR="$STATE_DIR" \
      bash "$ROOT_DIR/ops/verify-recorded-release-image.sh" "$IMAGE_REF" "$EXPECTED_SHA" "$COMPONENT"
    echo "immutable SHA image already exists; reusing without rebuild: $IMAGE_REF"
    exit 0
  fi

  echo "record exists but local tag is missing; rebuilding only to recover the exact recorded image"
  build_candidate
  EXPECTED_IMAGE_ID="$expected_image_id" \
    bash "$ROOT_DIR/ops/verify-image-identity.sh" "$candidate" "$EXPECTED_SHA"
  docker tag "$candidate" "$IMAGE_REF"
  RELEASE_IMAGE_STATE_DIR="$STATE_DIR" \
    bash "$ROOT_DIR/ops/verify-recorded-release-image.sh" "$IMAGE_REF" "$EXPECTED_SHA" "$COMPONENT"
  echo "immutable release image recovered: $IMAGE_REF"
  exit 0
fi

if docker image inspect "$IMAGE_REF" >/dev/null 2>&1; then
  echo "image tag already exists without an immutable release record: $IMAGE_REF" >&2
  echo "refusing to rebuild or adopt an unrecorded SHA tag" >&2
  exit 7
fi

build_candidate
bash "$ROOT_DIR/ops/verify-image-identity.sh" "$candidate" "$EXPECTED_SHA"
image_id="$(docker image inspect "$candidate" --format '{{.Id}}')"
if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "candidate image has invalid image ID: $image_id" >&2
  exit 3
fi

tmp_manifest="$manifest.tmp.$$"
printf '%s\n' "$image_id" >"$tmp_manifest"
chmod 600 "$tmp_manifest"
mv "$tmp_manifest" "$manifest"

docker tag "$candidate" "$IMAGE_REF"
RELEASE_IMAGE_STATE_DIR="$STATE_DIR" \
  bash "$ROOT_DIR/ops/verify-recorded-release-image.sh" "$IMAGE_REF" "$EXPECTED_SHA" "$COMPONENT"

echo "immutable release image prepared: $IMAGE_REF"
echo "RELEASE_IMAGE_RECORD=$manifest"
