#!/usr/bin/env python3
"""Configure only this repo's Git origin to use a loopback SSH/Clash proxy.

Reads Git identity/config and probes public origin/main (25-second bound).
Writes only two local Git keys and a private backup inside .git; no media,
model API, global proxy, DNS, SSH daemon or TLS verification changes.
Rerunnable; --restore refuses to overwrite subsequent manual key changes.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ORIGIN = 'https://github.com/Tiachi/video-sft-builder.git'
KEYS = ('remote.origin.proxy', 'http.version')


def git(root, *args, allow_missing=False, timeout=10):
    try:
        value = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                               text=True, timeout=timeout, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    except subprocess.TimeoutExpired:
        raise ValueError('Git operation timed out; no automatic retries') from None
    if value.returncode and not (allow_missing and value.returncode in (1, 5)):
        # Never dump Git config/proxy credentials or HTTP traces.
        raise ValueError('Git operation failed (exit ' + str(value.returncode) + '); check tunnel/network/authentication')
    return value.stdout


def get_values(root, key):
    return git(root, 'config', '--local', '--get-all', key, allow_missing=True).splitlines()


def set_values(root, key, values):
    git(root, 'config', '--local', '--unset-all', key, allow_missing=True)
    for value in values:
        git(root, 'config', '--local', '--add', key, value)


def probe(root, proxy):
    result = git(root, '-c', 'remote.origin.proxy=' + proxy, '-c', 'http.version=HTTP/1.1',
                 'ls-remote', '--exit-code', 'origin', 'refs/heads/main', timeout=25).strip()
    if not re.fullmatch(r'[0-9a-f]{40}\trefs/heads/main', result):
        raise ValueError('Unexpected public main response; configuration was not applied')
    return result.split()[0]


def configure(root, port=17897, *, restore=False, check=False):
    root = Path(root).resolve(strict=True)
    if Path(git(root, 'rev-parse', '--show-toplevel').strip()).resolve() != root:
        raise ValueError('Run this tool inside its standalone project root')
    if git(root, 'config', '--get', 'remote.origin.url').strip().rstrip('/') not in (ORIGIN, ORIGIN.removesuffix('.git')):
        raise ValueError('Origin must be the canonical public HTTPS repository')
    directory = Path(git(root, 'rev-parse', '--absolute-git-dir').strip())
    backup = directory / 'video-sft-proxy-backup.json'
    current = {key: get_values(root, key) for key in KEYS}
    saved = json.loads(backup.read_text(encoding='utf-8')) if backup.exists() else None
    if restore:
        if not saved:
            raise ValueError('No managed proxy backup exists')
        if current != saved['applied']:
            raise ValueError('Managed keys were manually changed; refusing to overwrite them')
        for key in KEYS:
            set_values(root, key, saved['original'][key])
        backup.unlink()
        return 'PASS: original local Git proxy/version restored; origin push protection unchanged'
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError('Proxy port must be between 1024 and 65535')
    proxy = 'http://127.0.0.1:' + str(port)
    print('CHECK: public origin/main through ' + proxy + ' (at most 25 seconds)', flush=True)
    sha = probe(root, proxy)
    if check:
        return 'PASS: proxy reachable; public main ' + sha + '; no configuration changed'
    if {key: get_values(root, key) for key in KEYS} != current:
        raise ValueError('Local proxy keys changed during connectivity check; refusing to overwrite them')
    applied = {'remote.origin.proxy': [proxy], 'http.version': ['HTTP/1.1']}
    if saved and current != saved['applied']:
        raise ValueError('Managed keys were manually changed; inspect them before reconfiguration')
    if not saved:
        # Private, no-clobber backup; original proxy settings may contain secrets.
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'original': current, 'applied': applied}, stream)
    elif saved['applied'] != applied:
        raise ValueError('Restore the previous managed configuration before changing ports')
    changed = []
    try:
        for key in KEYS:
            changed.append(key)
            set_values(root, key, applied[key])
    except BaseException:
        for key in changed:
            set_values(root, key, current[key])
        if not saved:
            backup.unlink()
        raise
    return 'PASS: local Git origin proxy configured; public main ' + sha + '; origin push protection unchanged'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=17897)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    try:
        print(configure(Path(__file__).resolve().parents[2], args.port, restore=args.restore, check=args.check))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
