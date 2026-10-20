#!/usr/bin/env bash
# IO: reads Git state/identity, fetches origin/main, fast-forwards this checkout only.
# No dataset/media/API access. Safe to rerun; dirty/diverged/wrong repos fail closed.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'FAIL: execute this script with bash; do not source it.' >&2
  return 2
fi
set -Eeuo pipefail
trap 'printf "%s\n" "FAIL: Git synchronization command failed; no automatic rollback or cleanup." >&2' ERR

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
project_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
actual_root="$(git -C "$project_root" rev-parse --show-toplevel)"
actual_root="$(CDPATH= cd -- "$actual_root" && pwd -P)"
[[ "$actual_root" == "$project_root" ]] || fail 'script is not in its standalone repository root.'

origin_url="$(git -C "$project_root" config --get remote.origin.url)"
case "$origin_url" in
  https://github.com/Tiachi/video-sft-builder|https://github.com/Tiachi/video-sft-builder.git|git@github.com:Tiachi/video-sft-builder.git|ssh://git@ssh.github.com:443/Tiachi/video-sft-builder.git) ;;
  *) fail 'origin does not identify Tiachi/video-sft-builder.' ;;
esac
[[ "$(git -C "$project_root" branch --show-current)" == main ]] || fail 'checkout must be on main.'
[[ -z "$(git -C "$project_root" status --porcelain=v1 --untracked-files=normal)" ]] || fail 'checkout is dirty; preserve and handle local changes before syncing.'

git -C "$project_root" fetch --no-tags origin refs/heads/main
target_sha="$(git -C "$project_root" rev-parse FETCH_HEAD)"
current_sha="$(git -C "$project_root" rev-parse HEAD)"
git -C "$project_root" merge-base --is-ancestor "$current_sha" "$target_sha" || fail 'local main is ahead or diverged; refusing to merge or overwrite.'
git -C "$project_root" merge --ff-only --no-edit "$target_sha"

local_sha="$(git -C "$project_root" rev-parse HEAD)"
remote_line="$(git -C "$project_root" ls-remote --exit-code origin refs/heads/main)"
remote_sha="${remote_line%%[[:space:]]*}"
[[ "$local_sha" == "$target_sha" && "$local_sha" == "$remote_sha" ]] || fail 'GitHub main changed or SHA mismatch; inspect and synchronize again.'
[[ -z "$(git -C "$project_root" status --porcelain=v1 --untracked-files=normal)" ]] || fail 'checkout changed during synchronization; inspect local work.'
printf 'PASS: main %s\n' "$local_sha"
