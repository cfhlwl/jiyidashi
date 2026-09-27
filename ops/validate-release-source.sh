#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET_SHA="${TARGET_SHA:-$(git -C "$ROOT_DIR" rev-parse HEAD)}"

if [[ ! "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "TARGET_SHA must be a full immutable git SHA" >&2
  exit 2
fi

actual_sha="$(git -C "$ROOT_DIR" rev-parse HEAD)"
if [[ "$actual_sha" != "$TARGET_SHA" ]]; then
  echo "checked-out HEAD $actual_sha does not match TARGET_SHA $TARGET_SHA" >&2
  exit 2
fi

status="$(git -C "$ROOT_DIR" status --porcelain=v1 --untracked-files=all)"
if [[ -n "$status" ]]; then
  echo "refusing release from a dirty or untracked build context:" >&2
  printf '%s\n' "$status" >&2
  exit 3
fi

echo "release source PASS: $TARGET_SHA"
