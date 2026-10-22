#!/usr/bin/env bash
# IO: first checks/installs local runtime dependencies (bootstrap.sh), then runs pipeline.
# Reads explicit config/assets/media; derived/state writes only to configured external roots.
# Paid requests occur only in `run` with a complete live configuration. demo is offline.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'FAIL: execute this script with bash; do not source it.' >&2
  return 2
fi
set -euo pipefail
trap 'printf "%s\n" "FAIL: pipeline command failed; partial state preserved." >&2' ERR
project_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ -n "${CONDA_PREFIX:-}" && -d "$CONDA_PREFIX/bin" ]]; then
  export PATH="$CONDA_PREFIX/bin:$PATH"
fi
# Metadata/reporting/offline commands do not require media tools. Interactive UI
# and real media commands always preflight before settings or model requests.
bootstrap_args=(--print-python)
case "${1:-ui}" in
  demo|init-config|validate-config|report|export|recover|--help|-h) bootstrap_args+=(--no-media) ;;
esac
python_bin="$(bash "$project_root/scripts/bootstrap.sh" "${bootstrap_args[@]}")"
export PATH="$(dirname -- "$python_bin"):$PATH"
export PYTHONPATH="${project_root}/src${PYTHONPATH:+:${PYTHONPATH}}"
"$python_bin" -m video_sft_builder "$@"
