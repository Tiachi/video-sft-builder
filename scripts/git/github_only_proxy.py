#!/usr/bin/env python3
"""Private, standalone Mihomo with a GitHub-only destination allowlist.

export reads one explicit Clash YAML (local PyYAML required), writes one NEW
private JSON-as-YAML. install/start/stop read/write only a private service home;
install takes an already transferred, SHA256-verified Linux core. git-enable and
git-disable touch two URL-scoped LOCAL Git keys with a private reversible backup.
Only git-enable performs a bounded GitHub ls-remote. No global env/Git proxy,
TUN, automatic downloads, model calls, dataset access, or telemetry/probes.
Raw core/config errors are kept out of terminal output. Core log is private.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

DOMAINS = ('github.com', 'githubusercontent.com', 'githubassets.com')
PORT = 17898
KEYS = ('http.https://github.com/.proxy', 'http.https://github.com/.version')
PROXY_ENV = ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')
NODE_KEYS = {'name', 'type', 'server', 'port', 'password', 'sni', 'alpn',
             'client-fingerprint', 'skip-cert-verify', 'udp', 'idle-session-check-interval',
             'idle-session-timeout', 'min-idle-session'}


def read_json(path):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Private metadata exceeds size bound')
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def private_json(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def make_config(node):
    node = deepcopy(node)
    if (not isinstance(node, dict) or set(node) - NODE_KEYS or node.get('type') != 'anytls'
            or not isinstance(node.get('server'), str) or not node['server'].strip()
            or type(node.get('port')) is not int or not 1 <= node['port'] <= 65535
            or not isinstance(node.get('password'), str) or not node['password']):
        raise ValueError('Only self-contained AnyTLS nodes are supported; no provider/chain/file imports')
    node['name'] = 'GITHUB_NODE'
    return {'port': PORT, 'socks-port': 0, 'mixed-port': 0, 'redir-port': 0, 'tproxy-port': 0,
            'allow-lan': False, 'bind-address': '127.0.0.1', 'mode': 'rule', 'log-level': 'warning',
            'ipv6': False, 'external-controller': '', 'find-process-mode': 'off',
            'geo-auto-update': False, 'tun': {'enable': False}, 'dns': {'enable': False},
            'profile': {'store-selected': False, 'store-fake-ip': False},
            'proxies': [node], 'rules': ['DOMAIN-SUFFIX,' + host + ',GITHUB_NODE' for host in DOMAINS] + ['MATCH,REJECT']}


def validate_config(value):
    if (not isinstance(value, dict) or not isinstance(value.get('proxies'), list)
            or len(value['proxies']) != 1 or value != make_config(value['proxies'][0])):
        raise ValueError('Config differs from the exact GitHub-only policy')
    return value


def export_profile(source, output, index=None):
    try:
        import yaml
    except ImportError:
        raise ValueError('Local export needs PyYAML; the Linux service does not') from None
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node):
        result = {}
        for key, value in node.value:
            key = loader.construct_object(key)
            if key in result:
                raise ValueError('Duplicate YAML key')
            result[key] = loader.construct_object(value)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    if source.stat().st_size > 4 * 1024 * 1024 or not output.parent.is_dir():
        raise ValueError('Profile size/path bound exceeded')
    try:
        value = yaml.load(source.read_text(encoding='utf-8-sig'), Loader=UniqueLoader)
    except yaml.YAMLError:
        raise ValueError('Invalid YAML; raw parser output suppressed') from None
    nodes = value.get('proxies', [])
    eligible = [i for i, node in enumerate(nodes) if node.get('type') == 'anytls'
                and not re.search('剩余|流量|到期|订阅|套餐|官网|更新', node.get('name', ''))]
    chosen = index if index is not None else next(iter(eligible), None)
    if chosen not in eligible:
        raise ValueError('No eligible AnyTLS node at the selected index')
    private_json(output, make_config(nodes[chosen]))
    return 'PASS: one AnyTLS node exported privately; source untouched; node index ' + str(chosen)


def clean_env():
    return {key: value for key, value in os.environ.items() if key not in PROXY_ENV}


def linux_only():
    if platform.system() != 'Linux':
        raise ValueError('Service operations require Linux')


def service(home):
    linux_only()
    home = Path(home).expanduser().resolve(strict=True)
    manifest = read_json(home / 'manifest.json')
    if sha256(home / 'mihomo') != manifest['core_sha256'] or sha256(home / 'config.json') != manifest['config_sha256']:
        raise ValueError('Installed core/config identity changed; refusing operation')
    validate_config(read_json(home / 'config.json'))
    if home.stat().st_mode & 0o077 or (home / 'config.json').stat().st_mode & 0o077:
        raise ValueError('Service home/config permissions must be private')
    return home


def install(home, core, config, expected):
    linux_only()
    home, core, config = Path(home).expanduser().resolve(), Path(core).resolve(strict=True), Path(config).resolve(strict=True)
    if not re.fullmatch('[0-9a-f]{64}', expected) or sha256(core) != expected:
        raise ValueError('Core SHA256 mismatch')
    validate_config(read_json(config))
    desired = {'core_sha256': expected, 'config_sha256': sha256(config)}
    if home.exists():
        service(home)
        if read_json(home / 'manifest.json') != desired:
            raise ValueError('Existing service differs; no overwrite performed')
        return 'PASS: identical private service already installed'
    home.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.github-proxy-', dir=home.parent) as temporary:
        staging = Path(temporary)
        os.chmod(staging, 0o700)
        shutil.copyfile(core, staging / 'mihomo')
        shutil.copyfile(config, staging / 'config.json')
        os.chmod(staging / 'mihomo', 0o700)
        os.chmod(staging / 'config.json', 0o600)
        checked = subprocess.run([str(staging / 'mihomo'), '-t', '-d', str(staging), '-f', str(staging / 'config.json')],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, env=clean_env())
        if checked.returncode:
            raise ValueError('Mihomo policy validation failed; nothing installed')
        private_json(staging / 'manifest.json', desired)
        os.rename(staging, home)
    return 'PASS: private service installed; not started; no Git settings changed'


def owned_pid(home):
    marker = home / 'process.json'
    if not marker.exists():
        return None
    saved = read_json(marker)
    pid = saved['pid']
    if type(pid) is not int or pid <= 1:
        raise ValueError('Invalid managed PID')
    proc = Path('/proc') / str(pid)
    try:
        stat = (proc / 'stat').read_text().split()
    except FileNotFoundError:
        return None
    if stat[2] == 'Z':
        return None
    if (proc / 'exe').resolve() != home / 'mihomo' or stat[21] != saved['start_ticks']:
        raise ValueError('Process identity mismatch; refusing to touch unrelated PID')
    return pid


def listening():
    with socket.socket() as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(('127.0.0.1', PORT)) == 0


def start(home):
    home = service(home)
    pid = owned_pid(home)
    if pid:
        if not listening():
            raise ValueError('Owned core exists but port is unavailable; inspect private core log')
        return 'PASS: owned core already running, PID ' + str(pid)
    if listening():
        raise ValueError('Loopback port is occupied; no unrelated process stopped')
    (home / 'process.json').unlink(missing_ok=True)
    fd = os.open(home / 'core.log', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'ab') as log:
        child = subprocess.Popen([str(home / 'mihomo'), '-d', str(home), '-f', str(home / 'config.json')],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, env=clean_env())
    try:
        ticks = (Path('/proc') / str(child.pid) / 'stat').read_text().split()[21]
        private_json(home / 'process.json', {'pid': child.pid, 'start_ticks': ticks})
        for _ in range(30):
            if child.poll() is not None:
                raise ValueError('Core exited; inspect its private log, which may contain node details')
            if listening():
                return 'PASS: GitHub-only HTTP proxy on 127.0.0.1:' + str(PORT) + '; PID ' + str(child.pid)
            time.sleep(0.1)
        raise ValueError('Core startup timed out')
    except BaseException:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
        (home / 'process.json').unlink(missing_ok=True)
        raise


def git(repo, *arguments, missing=False, timeout=10):
    result = subprocess.run(['git', '-C', str(repo), *arguments], capture_output=True, text=True,
                            timeout=timeout, env={**clean_env(), 'GIT_TERMINAL_PROMPT': '0'})
    if result.returncode and not (missing and result.returncode in (1, 5)):
        raise ValueError('Git operation failed; raw output suppressed to protect credentials')
    return result.stdout.strip()


def git_values(repo, key):
    return git(repo, 'config', '--local', '--get-all', key, missing=True).splitlines()


def set_git(repo, key, values):
    git(repo, 'config', '--local', '--unset-all', key, missing=True)
    for value in values:
        git(repo, 'config', '--local', '--add', key, value)


def git_configure(home, repo, disable=False):
    home = service(home)
    repo = Path(repo).resolve(strict=True)
    if Path(git(repo, 'rev-parse', '--show-toplevel')).resolve() != repo:
        raise ValueError('Use the repository root')
    backup = Path(git(repo, 'rev-parse', '--absolute-git-dir')) / 'github-only-proxy-backup.json'
    current = {key: git_values(repo, key) for key in KEYS}
    saved = read_json(backup) if backup.exists() else None
    applied = dict(zip(KEYS, [['http://127.0.0.1:' + str(PORT)], ['HTTP/1.1']]))
    if disable:
        if not saved:
            return 'PASS: no managed Git keys to restore'
        if current != saved['applied']:
            raise ValueError('Managed Git keys were edited; no overwrite performed')
        for key in KEYS:
            set_git(repo, key, saved['original'][key])
        backup.unlink()
        return 'PASS: original URL-scoped Git keys restored; public push protection unchanged'
    if (any(os.environ.get(key) for key in PROXY_ENV)
            or git(repo, 'config', '--get', 'remote.origin.proxy', missing=True)
            or git(repo, 'config', '--get-urlmatch', 'http.proxy', 'https://huggingface.co/', missing=True)):
        raise ValueError('Existing broad/environment/origin proxy needs inspection; nothing changed')
    if saved and current != saved['applied']:
        raise ValueError('Managed Git keys were edited; no overwrite performed')
    if not owned_pid(home) or not listening():
        raise ValueError('Start the owned proxy first')
    origin = git(repo, 'remote', 'get-url', 'origin')
    if urlsplit(origin).scheme != 'https' or urlsplit(origin).hostname != 'github.com':
        raise ValueError('Origin must be HTTPS github.com')
    # URL-scoped flags override existing GitHub HTTP values just for this probe.
    observed = git(repo, '-c', KEYS[0] + '=' + applied[KEYS[0]][0], '-c', KEYS[1] + '=HTTP/1.1',
                   'ls-remote', '--exit-code', 'origin', 'refs/heads/main', timeout=25)
    if not re.fullmatch('[0-9a-f]{40}\\s+refs/heads/main', observed):
        raise ValueError('Unexpected GitHub main response; no settings changed')
    if current != {key: git_values(repo, key) for key in KEYS}:
        raise ValueError('Git keys changed during probe; no overwrite performed')
    if not saved:
        private_json(backup, {'original': current, 'applied': applied})
    try:
        for key in KEYS:
            set_git(repo, key, applied[key])
    except BaseException:
        for key in KEYS:
            set_git(repo, key, current[key])
        if not saved:
            backup.unlink()
        raise
    return 'PASS: only this repo HTTPS github.com uses the proxy; no global/env settings changed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home() / '.local/share/video-sft-github-proxy')
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    export.add_argument('--profile', type=Path, required=True)
    export.add_argument('--output', type=Path, required=True)
    export.add_argument('--node-index', type=int)
    setup = sub.add_parser('install')
    setup.add_argument('--core', type=Path, required=True)
    setup.add_argument('--config', type=Path, required=True)
    setup.add_argument('--sha256', required=True)
    for command in ('start', 'status', 'stop'):
        sub.add_parser(command)
    for command in ('git-enable', 'git-disable'):
        child = sub.add_parser(command)
        child.add_argument('--repo', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'export':
            result = export_profile(args.profile, args.output, args.node_index)
        elif args.command == 'install':
            result = install(args.home, args.core, args.config, args.sha256)
        elif args.command == 'start':
            result = start(args.home)
        elif args.command.startswith('git-'):
            result = git_configure(args.home, args.repo, args.command == 'git-disable')
        else:
            home = service(args.home)
            pid = owned_pid(home)
            if args.command == 'stop' and pid:
                os.kill(pid, signal.SIGTERM)
                for _ in range(30):
                    if owned_pid(home) is None:
                        break
                    time.sleep(0.1)
                if owned_pid(home) is not None:
                    raise ValueError('Core did not exit; no forced kill performed')
                (home / 'process.json').unlink(missing_ok=True)
                result = 'PASS: only owned core stopped; disable managed Git keys before future direct fetches'
            else:
                result = 'PASS: owned core ' + ('running PID ' + str(pid) if pid else 'not running')
        print(result)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('FAIL: operation refused or failed; no raw private configuration/error output. Check paths, permissions, state and private core log.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
