#!/usr/bin/env bash
# IO: repository assets and tiny, disposable synthetic fixtures only. No paid API.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'FAIL: execute with bash; do not source this script.' >&2
  return 2
fi
set -Eeuo pipefail
trap 'printf "%s\n" "FAIL: offline validation failed." >&2' ERR
project_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "${project_root}"
export PYTHONPATH="${project_root}/src${PYTHONPATH:+:${PYTHONPATH}}"
python3 scripts/validate_design.py
python3 -m unittest discover -s tests -v
printf '%s\n' 'PASS: offline validation completed; real API/media/student validation is separate.'
