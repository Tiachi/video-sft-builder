#!/usr/bin/env bash
# IO: probes runtime tools; installs missing packages from configured OS/active Conda
# repositories; creates/deletes only a tiny synthetic self-test in the OS temp dir.
# No settings/API keys/user videos/build state are read or changed. Safe to rerun.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'FAIL: execute bootstrap with bash; do not source it.' >&2
  return 2
fi
set -Eeuo pipefail
trap 'printf "%s\n" "FAIL: dependency initialization failed. If packages are unavailable in configured OS repos, activate a Conda environment and rerun (see docs/terminal_quickstart.md). Existing config/builds preserved." >&2' ERR
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
note() { printf '%s\n' "$*" >&2; }
project_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ -n "${CONDA_PREFIX:-}" && -d "$CONDA_PREFIX/bin" ]]; then
  export PATH="$CONDA_PREFIX/bin:$PATH"
fi
install="${VIDEO_SFT_AUTO_INSTALL:-1}"
print_python=0
media=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) install=0 ;;
    --print-python) print_python=1 ;;
    --no-media) media=0 ;;
    --help|-h)
      printf '%s\n' 'Usage: bash scripts/bootstrap.sh [--check] [--no-media] [--print-python]' \
        'Default: check and install missing dependencies, then synthetic media self-test.' \
        '--check: no installs. VIDEO_SFT_AUTO_INSTALL=0 also disables installs.' \
        'VIDEO_SFT_PYTHON=/path/to/python3.11 selects an existing interpreter.'
      exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
  shift
done
[[ "$install" == 0 || "$install" == 1 ]] || fail 'VIDEO_SFT_AUTO_INSTALL must be 0 or 1.'

python_bin=''
choose_python() {
  local candidate
  local -a candidates
  if [[ -n "${VIDEO_SFT_PYTHON:-}" ]]; then
    candidates=("$VIDEO_SFT_PYTHON")
  else
    candidates=(python3 python3.13 python3.12 python3.11 python)
  fi
  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c \
      'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
      python_bin="$(command -v "$candidate")"
      return 0
    fi
  done
  return 1
}

manager=''
sudo_prefix=()
select_manager() {
  [[ "$(uname -s)" == Linux ]] || fail 'Automatic installation supports Linux; install Python>=3.11 and FFmpeg/ffprobe on this OS, then rerun.'
  # Use an already active Conda environment, without upgrading its Python implicitly.
  if [[ -n "${CONDA_PREFIX:-}" && -n "${CONDA_EXE:-}" && -x "$CONDA_EXE" ]]; then
    manager=conda
    note "INIT: using active Conda prefix $CONDA_PREFIX"
    return
  fi
  for manager in apt-get dnf yum zypper pacman; do
    if command -v "$manager" >/dev/null 2>&1; then break; fi
    manager=''
  done
  [[ -n "$manager" ]] || fail 'No supported package manager. Install Python>=3.11 and FFmpeg (including ffprobe) with your administrator/Conda environment, then rerun.'
  if [[ "$(id -u)" != 0 ]]; then
    command -v sudo >/dev/null 2>&1 || fail 'Installing missing OS packages requires root or sudo; rerun in a prepared environment.'
    # Never prompt invisibly for a password during application startup.
    sudo -n true 2>/dev/null || fail 'No noninteractive sudo permission. Ask an administrator to run bash scripts/bootstrap.sh, or activate a prepared Conda environment.'
    sudo_prefix=(sudo -n)
  fi
}

package_install() {
  local purpose="$1" package
  [[ "$install" == 1 ]] || fail "Missing or unusable $purpose; installation disabled. Run bash scripts/bootstrap.sh to install dependencies."
  [[ -n "$manager" ]] || select_manager
  note "INIT: installing $purpose via $manager (no model/API calls)"
  if [[ "$manager" == conda ]]; then
    package=ffmpeg
    [[ "$purpose" != Python ]] || package='python>=3.11,<3.14'
    "$CONDA_EXE" install --yes --freeze-installed --prefix "$CONDA_PREFIX" -c conda-forge "$package" >&2
    export PATH="$CONDA_PREFIX/bin:$PATH"
    hash -r
    return
  fi
  package=ffmpeg
  [[ "$purpose" != Python ]] || package=python3.11
  case "$manager" in
    apt-get)
      "${sudo_prefix[@]}" env DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=1 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update >&2
      "${sudo_prefix[@]}" env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=30 install -y --no-install-recommends "$package" ca-certificates >&2 ;;
    dnf|yum)
      # Need a full build with libx264, not ffmpeg-free's restricted codec set.
      # Do not enable third-party repos or use --allowerasing automatically.
      "${sudo_prefix[@]}" "$manager" --setopt=timeout=30 --setopt=retries=1 install -y "$package" ca-certificates >&2 ;;
    zypper) "${sudo_prefix[@]}" zypper --non-interactive install "$package" ca-certificates >&2 ;;
    pacman)
      [[ "$purpose" != Python ]] || package=python
      "${sudo_prefix[@]}" pacman -S --needed --noconfirm "$package" ca-certificates >&2 ;;
  esac
  hash -r
}

if ! choose_python; then
  [[ -z "${VIDEO_SFT_PYTHON:-}" ]] || fail 'VIDEO_SFT_PYTHON is unavailable or below 3.11; correct its path/version.'
  package_install Python
  choose_python || fail 'Python>=3.11 still unavailable in configured package repositories. Activate a Python>=3.11 environment or set VIDEO_SFT_PYTHON.'
fi
# Verify SSL/SQLite before attempting any media installer or reading user settings.
"$python_bin" "$project_root/scripts/check_environment.py" --no-media >&2
if [[ "$media" == 1 ]]; then
  # Running, not merely finding, both executables also catches missing libraries.
  if ! "$python_bin" -c 'import subprocess; [subprocess.run([n,"-version"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=15) for n in ("ffmpeg","ffprobe")]' >/dev/null 2>&1; then
    package_install FFmpeg/ffprobe
  fi
  "$python_bin" "$project_root/scripts/check_environment.py" >&2
fi
note 'PASS: dependency initialization complete; existing settings and builds unchanged.'
if [[ "$print_python" == 1 ]]; then
  # Conda installs only adjust this child process PATH. Return a real interpreter
  # path; the parent launcher adds its bin directory so FFmpeg resolves there too.
  printf '%s\n' "$python_bin"
fi
