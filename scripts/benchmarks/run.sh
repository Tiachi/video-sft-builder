#!/usr/bin/env bash
# IO: exact registered annotation/media paths read-only; all new writes under data root.
# Downloads direct only. No model calls, Git writes, system-network edits, or source-data writes.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'FAIL: execute with bash; do not source.' >&2
  return 2
fi
set -Eeuo pipefail
trap 'printf "%s\n" "FAIL: benchmark operation incomplete; inspect the saved report and rerun to resume." >&2' ERR
project_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
benchmark_root="/mnt/sfs/ltj/data/benchmark_research_20261022"
case "${1:-download}" in inventory|download) ;; *) printf '%s\n' 'FAIL: use inventory or download.' >&2; exit 2;; esac
printf 'Network preflight: proxy variable names only (values hidden):\n'
env | cut -d= -f1 | grep -Ei '^(http|https|all)_proxy$' || true
printf 'Git proxy setting names only (Git is not used for dataset transfers):\n'
git -C "$project_root" config --name-only --get-regexp '.*proxy.*' || true
# Child process only: parent terminal and persistent configuration are unchanged.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY='*' no_proxy='*' HF_HUB_DISABLE_XET=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1
export HF_HUB_DOWNLOAD_TIMEOUT=60 HF_HUB_ETAG_TIMEOUT=15
mkdir -p "$benchmark_root/_tools"
exec 9>"$benchmark_root/.operation.lock"
flock -n 9 || { printf '%s\n' 'FAIL: another benchmark operation holds the lock.' >&2; exit 1; }
benchmark_python="$benchmark_root/_tools/venv/bin/python"
if [[ ! -x "$benchmark_python" ]]; then python3 -m venv "$benchmark_root/_tools/venv"; fi
if ! "$benchmark_python" -c 'import huggingface_hub, pyarrow, yt_dlp' >/dev/null 2>&1; then
  "$benchmark_python" -m pip --disable-pip-version-check install --proxy '' --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r "$project_root/scripts/benchmarks/requirements.txt"
fi
"$benchmark_python" -u "$project_root/scripts/benchmarks/benchmark_assets.py" "${1:-download}" --config "$project_root/configs/benchmark_assets.json"
printf '%s\n' 'PASS: requested benchmark operation finished; download completeness and media readiness are separate report fields.'
