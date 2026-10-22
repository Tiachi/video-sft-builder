#!/usr/bin/env bash
# IO: snapshots only the explicitly selected build and MP4; uploads only to the
# private relay. Disables origin push in THIS server checkout; never git-pushes.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'FAIL: execute with bash; do not source this script.' >&2
  return 2
fi
set -euo pipefail
trap 'printf "%s\n" "FAIL: relay transfer stopped; original media/build/config preserved. See the error above." >&2' ERR
project_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
python_bin="$(bash "$project_root/scripts/bootstrap.sh" --print-python --no-media --check)"
"$python_bin" "$project_root/scripts/relay_evidence.py" "$@"
