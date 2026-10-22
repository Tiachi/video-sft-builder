#!/usr/bin/env bash
# Reads one explicitly transferred private bundle and one Git checkout.
# Writes only the private proxy home and two reversible repo-local GitHub keys.
# No downloads, package installs, TUN/global env/system proxy changes, or model calls.
# Safe to rerun for identical inputs. Run as a child process, never source.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'FAIL: execute this script; do not source it.' >&2
  return 2
fi
set -euo pipefail
trap 'printf "%s\n" "FAIL: GitHub proxy setup stopped; inspect the private service state before retrying." >&2' ERR
umask 077
if [[ "$#" != 2 ]]; then
  printf '%s\n' 'FAIL: usage: bash setup_github_only_proxy.sh /absolute/private/bundle /absolute/repository' >&2
  exit 2
fi
script_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
bundle="$(CDPATH= cd -- "$1" && pwd -P)"
repo="$(CDPATH= cd -- "$2" && pwd -P)"
core_digest="$(cat -- "$bundle/core.sha256")"
python3 "$script_root/github_only_proxy.py" install --core "$bundle/mihomo" --config "$bundle/config.json" --sha256 "$core_digest"
python3 "$script_root/github_only_proxy.py" start
python3 "$script_root/github_only_proxy.py" git-enable --repo "$repo"
printf '%s\n' 'PASS: standalone GitHub-only proxy enabled; HF/packages/model APIs untouched; no global proxy set.'
