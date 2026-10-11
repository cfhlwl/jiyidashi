#!/usr/bin/env bash
set -euo pipefail

validator="$(dirname "$0")/validate_ci_sha_inputs.sh"
target_sha="$(git rev-parse HEAD)"
if [[ "$(git rev-parse --is-shallow-repository)" == "true" ]]; then
  git fetch --no-tags --unshallow origin
fi
base_sha="$(git rev-parse "$target_sha^")"

expect_failure() {
  if bash "$validator" "$@"; then
    echo "expected validation failure: $*" >&2
    exit 1
  fi
}

expect_failure "not-a-commit-sha"
expect_failure "$target_sha" "$target_sha"

empty_tree="$(git mktree < /dev/null)"
unrelated_sha="$(
  GIT_AUTHOR_NAME=ci-test \
  GIT_AUTHOR_EMAIL=ci-test@example.invalid \
  GIT_COMMITTER_NAME=ci-test \
  GIT_COMMITTER_EMAIL=ci-test@example.invalid \
    git commit-tree "$empty_tree" -m unrelated
)"
expect_failure "$target_sha" "$unrelated_sha"

bash "$validator" "$target_sha" "$base_sha"
echo "CI SHA validation boundary tests passed"
