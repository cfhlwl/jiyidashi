#!/usr/bin/env bash
set -euo pipefail

sha_pattern='^[0-9a-f]{40}$'

require_commit_sha() {
  local label="$1"
  local value="$2"
  if [[ ! "$value" =~ $sha_pattern ]]; then
    echo "$label must be a 40-character lowercase Git commit SHA" >&2
    return 1
  fi
  if ! git cat-file -e "$value^{commit}" 2>/dev/null; then
    echo "$label is not a commit present in the checkout" >&2
    return 1
  fi
}

if [[ $# -eq 1 ]]; then
  require_commit_sha target_sha "$1"
elif [[ $# -eq 2 ]]; then
  target_sha="$1"
  base_sha="$2"
  require_commit_sha target_sha "$target_sha"
  require_commit_sha base_sha "$base_sha"
  if [[ "$base_sha" == "$target_sha" ]]; then
    echo "base SHA and target SHA must differ" >&2
    exit 1
  fi
  if ! git merge-base --is-ancestor "$base_sha" "$target_sha"; then
    echo "base SHA is not an ancestor of target SHA" >&2
    exit 1
  fi
else
  echo "usage: $0 TARGET_SHA [BASE_SHA]" >&2
  exit 2
fi
