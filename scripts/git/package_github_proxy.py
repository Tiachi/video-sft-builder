#!/usr/bin/env python3
"""Build one NEW private ARM64 proxy ZIP from verified local inputs, offline.

Reads one official Release metadata JSON, its gzip, one private GitHub-only config,
and the two reviewed deployment scripts. Writes only the explicit NEW ZIP outside
the code checkout. No networking or server execution. ZIP contains a node secret:
never commit/upload it to GitHub. Linux deployment scripts need no PyYAML.
"""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

from github_only_proxy import read_json, sha256, validate_config

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = 'github-only-proxy-arm64'


def package(archive, release, config, output):
    archive, release, config = (Path(p).resolve(strict=True) for p in (archive, release, config))
    output = Path(output).resolve()
    if output.is_relative_to(ROOT) or not output.parent.is_dir() or output.exists():
        raise ValueError('Use a NEW output path outside the source checkout')
    metadata = read_json(release)
    expected = 'https://github.com/MetaCubeX/mihomo/releases/download/' + metadata['version'] + '/mihomo-linux-arm64-' + metadata['version'] + '.gz'
    if (metadata['url'] != expected or metadata['name'] != expected.rsplit('/', 1)[-1]
            or archive.stat().st_size != metadata['size'] or archive.stat().st_size > 50 * 1024 * 1024
            or metadata['digest'] != 'sha256:' + sha256(archive)):
        raise ValueError('Official Release metadata/hash mismatch')
    validate_config(read_json(config))
    if subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain'], capture_output=True, text=True, check=True).stdout:
        raise ValueError('Commit reviewed scripts before packaging')
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix='.github-only-private-', dir=output.parent) as directory:
        staging = Path(directory)
        os.chmod(staging, 0o700)
        core = staging / 'mihomo'
        total = 0
        with gzip.open(archive, 'rb') as source, core.open('xb') as target:
            while block := source.read(1024 * 1024):
                total += len(block)
                if total > 128 * 1024 * 1024:
                    raise ValueError('Core decompression bound exceeded')
                target.write(block)
        shutil.copyfile(config, staging / 'config.json')
        for name in ('github_only_proxy.py', 'setup_github_only_proxy.sh'):
            shutil.copyfile(ROOT / 'scripts/git' / name, staging / name)
        (staging / 'core.sha256').write_text(sha256(core) + '\n')
        provenance = {'source_commit': commit, 'release': metadata, 'files': {
            path.name: sha256(path) for path in staging.iterdir()}}
        (staging / 'deployment_provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        zipped = staging / 'private.zip'
        with zipfile.ZipFile(zipped, 'x', compression=zipfile.ZIP_DEFLATED) as result:
            for path in sorted(staging.iterdir()):
                if path != zipped:
                    item = zipfile.ZipInfo(BUNDLE + '/' + path.name)
                    mode = 0o700 if path.name in ('mihomo', 'setup_github_only_proxy.sh') else 0o600
                    item.create_system = 3
                    item.external_attr = (0o100000 | mode) << 16
                    item.compress_type = zipfile.ZIP_DEFLATED
                    result.writestr(item, path.read_bytes())
        with zipfile.ZipFile(zipped) as result:
            if result.testzip() is not None:
                raise ValueError('Private ZIP CRC check failed')
        # Hard link publishes without overwriting an output created concurrently.
        os.link(zipped, output)
        os.chmod(output, 0o600)
    return {'status': 'private_bundle_prepared_not_server_verified', 'source_commit': commit,
            'zip_sha256': sha256(output), 'bytes': output.stat().st_size,
            'contains_secret': True, 'core_arch': 'linux-arm64'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'release', 'config', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(package(args.archive, args.release, args.config, args.output)))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, gzip.BadGzipFile, zipfile.BadZipFile):
        print('FAIL: private packaging refused; no secret content printed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
