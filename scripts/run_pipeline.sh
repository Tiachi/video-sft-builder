#!/usr/bin/env bash
# IO: reads explicit config/assets/media; derived/state writes only to configured external roots.
# Paid requests occur only in `run` with a complete live configuration. demo is offline.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'FAIL: execute this script with bash; do not source it.' >&2
  return 2
fi
set -Eeuo pipefail
trap 'printf "%s\n" "FAIL: pipeline command failed; partial state preserved." >&2' ERR
project_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export PYTHONPATH="${project_root}/src${PYTHONPATH:+:${PYTHONPATH}}"
python3 -m video_sft_builder "$@"
