#!/usr/bin/env python3
"""Select verified stable Handbuilt workflows without editing host plugin caches."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import time
import urllib.request
import urllib.parse
import zipfile

REPOSITORY = 'stephenfsetzer/handbuilt-church-labs'
LATEST_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
CHECK_INTERVAL = 86400
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_UNPACKED = 96 * 1024 * 1024
PACKAGE = 'handbuilt-workflow.zip'
CHECKSUM = 'handbuilt-workflow.sha256'
REQUIRED = ('tools/church_workflow.py', 'tools/handbuilt_runtime.py',
            'tools/workflow_updates.py', 'tools/plugin_identity.py',
            'scaffold/church-folder/handbuilt.py', 'requirements.txt',
            'skills/onboarding/SKILL.md', 'skills/bulletin/SKILL.md',
            'skills/sermon-research/SKILL.md')


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError('Expected a stable release version.')
    return tuple(map(int, value.split('.')))


def package_version(root):
    values = [json.loads((root / directory / 'plugin.json').read_text())
              for directory in ('.codex-plugin', '.claude-plugin')]
    if any(not isinstance(item, dict) or item.get('name') != 'handbuilt-church-labs' for item in values):
        raise ValueError('Unexpected workflow package name.')
    if values[0].get('version') != values[1].get('version'):
        raise ValueError('The plugin manifests disagree.')
    result = values[0]['version']
    version(result)
    return result


def fetch(url, limit):
    """Bounded public downloads. No church content or credentials are sent."""
    if url != LATEST_URL and not re.fullmatch(
            re.escape(f'https://github.com/{REPOSITORY}/releases/download/')
            + r'v[0-9]+\.[0-9]+\.[0-9]+/handbuilt-workflow\.(zip|sha256)', url):
        raise ValueError('Unexpected release source.')
    request = urllib.request.Request(url, headers={'User-Agent': 'Handbuilt-Workflow-Updater',
                                                 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=8) as response:
        final = urllib.parse.urlparse(response.url)
        if final.scheme != 'https' or final.hostname not in {
            'api.github.com', 'github.com', 'release-assets.githubusercontent.com',
            'objects.githubusercontent.com'}:
            raise ValueError('Unexpected release download destination.')
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Release download exceeded its size limit.')
        return data


def latest_release(download=fetch):
    release = json.loads(download(LATEST_URL, 1024 * 1024))
    if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
        raise ValueError('Expected a published stable release.')
    tag = release.get('tag_name', '')
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise ValueError('Unexpected release tag.')
    number = tag[1:]
    version(number)
    assets = release.get('assets', [])
    if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
        raise ValueError('Invalid release assets.')
    urls = {}
    for name in (PACKAGE, CHECKSUM):
        matches = [asset for asset in assets if asset.get('name') == name]
        expected = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'
        if len(matches) == 1 and matches[0].get('browser_download_url') == expected:
            urls[name] = expected
    return {'name': 'handbuilt-church-labs', 'version': number, 'tag': tag, 'assets': urls,
            'url': f'https://github.com/{REPOSITORY}/releases/tag/{tag}'}


def validate_release_metadata(latest):
    """Treat cached metadata with the same source restrictions as a fresh lookup."""
    if not isinstance(latest, dict):
        raise ValueError('Invalid cached release metadata.')
    version(latest.get('version'))
    tag = 'v' + latest['version']
    if latest.get('tag') != tag or not isinstance(latest.get('assets'), dict):
        raise ValueError('Invalid cached release metadata.')
    for name, url in latest['assets'].items():
        if name not in (PACKAGE, CHECKSUM) or url != f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}':
            raise ValueError('Unexpected cached release source.')


def _safe_name(name):
    if not isinstance(name, str):
        return False
    path = PurePosixPath(name)
    return (isinstance(name, str) and name != '' and '\\' not in name
            and not path.is_absolute() and '..' not in path.parts
            and ':' not in name and str(path) == name)


def unpack_verified(data, digest, destination, expected_version):
    if len(data) > MAX_ARCHIVE or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Invalid release checksum or size.')
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('The downloaded release failed its checksum.')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (len(names) > 3000 or len(names) != len(set(names))
                or len(names) != len({name.casefold() for name in names})
                or any(not _safe_name(name) for name in names)
                or sum(entry.file_size for entry in entries) > MAX_UNPACKED):
            raise ValueError('Unsafe release archive.')
        if any(entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16)
               or (stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG))
               for entry in entries):
            raise ValueError('Only regular files are allowed in a release.')
        manifest = json.loads(archive.read('.handbuilt-workflow.json'))
        if not isinstance(manifest, dict):
            raise ValueError('Invalid release file manifest.')
        files = manifest.get('files')
        if (manifest.get('schema_version') != 1 or manifest.get('version') != expected_version
                or not isinstance(files, dict)
                or set(names) != set(files) | {'.handbuilt-workflow.json'}
                or not set(REQUIRED).issubset(files)):
            raise ValueError('The release file manifest is incomplete or incompatible.')
        for name, expected in files.items():
            content = archive.read(name)
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError('A release file failed its checksum.')
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (destination / '.handbuilt-workflow.json').write_text(json.dumps(manifest))
    if package_version(destination) != expected_version:
        raise ValueError('The package version does not match its release.')


def verify_installed(root):
    manifest = json.loads((root / '.handbuilt-workflow.json').read_text())
    if (not isinstance(manifest, dict) or manifest.get('schema_version') != 1
            or manifest.get('version') != package_version(root)
            or not isinstance(manifest.get('files'), dict)
            or not set(REQUIRED).issubset(manifest['files'])):
        raise ValueError('The installed workflow manifest is invalid.')
    for name, digest in manifest['files'].items():
        if not _safe_name(name):
            raise ValueError('Unsafe installed workflow path.')
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Installed workflow files must stay inside their release.')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('The installed workflow was changed; preserve it for review.')
    actual = {path.relative_to(root).as_posix() for path in root.rglob('*')
              if path.is_file() and '__pycache__' not in path.parts}
    if actual != set(manifest['files']) | {'.handbuilt-workflow.json'}:
        raise ValueError('The installed workflow contains unexpected files; preserve it for review.')
    return manifest['version']


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.update-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def file_lock(path):
    """An OS-released lock survives process crashes without stale lock recovery."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            lock = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            unlock = lambda: (stream.seek(0), msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1))
        else:
            import fcntl
            lock = lambda: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            unlock = lambda: fcntl.flock(stream, fcntl.LOCK_UN)
        try:
            lock()
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            unlock()


def update_lock(store):
    return file_lock(store / 'update.lock')


def select_release(current_root, store, validate, *, download=fetch, now=time.time, force=False):
    """Return a candidate only after byte and runtime checks; never write church data."""
    current_root, store = Path(current_root).resolve(), Path(store).resolve()
    current_version = package_version(current_root)
    result = {'status': 'current', 'selected_root': str(current_root),
              'selected_version': current_version, 'latest': None, 'freshness': 'unknown',
              'host_plugin_updated': False}
    if (current_root / '.git').exists():
        return dict(result, status='pinned', reason='development_connection')
    try:
        with update_lock(store) as acquired:
            if not acquired:
                return dict(result, status='deferred', reason='another_update_in_progress')
            state_path = store / 'latest-check.json'
            try:
                state = json.loads(state_path.read_text())
            except (OSError, ValueError):
                state = {}
            if not isinstance(state, dict):
                state = {}
            checked = state.get('checked_at', 0)
            if not force and isinstance(checked, (float, int)) and 0 <= now() - checked < CHECK_INTERVAL:
                latest = state.get('latest')
                if not isinstance(latest, dict):
                    return dict(result, status='deferred', reason='recent_check_unavailable')
                result['freshness'] = 'cached'
            else:
                try:
                    latest = latest_release(download)
                except (OSError, ValueError, TypeError, KeyError):
                    _atomic_json(state_path, {'checked_at': now(), 'latest': None})
                    raise
                _atomic_json(state_path, {'checked_at': now(), 'latest': latest})
                result['freshness'] = 'verified'
            validate_release_metadata(latest)
            result['latest'] = latest
            if version(latest['version']) <= version(current_version):
                return result
            if set(latest['assets']) != {PACKAGE, CHECKSUM}:
                return dict(result, status='deferred', reason='release_assets_unavailable')
            checksum_text = download(latest['assets'][CHECKSUM], 1024).decode('ascii').strip()
            match = re.fullmatch(r'([0-9a-f]{64})(?:\s+\*?handbuilt-workflow\.zip)?', checksum_text)
            if not match:
                raise ValueError('Invalid release checksum asset.')
            digest = match[1]
            releases = store / 'releases'
            releases.mkdir(exist_ok=True)
            destination = releases / (latest['version'] + '-' + digest[:16])
            if destination.exists():
                if verify_installed(destination) != latest['version']:
                    raise ValueError('The installed version does not match the release.')
            else:
                data = download(latest['assets'][PACKAGE], MAX_ARCHIVE)
                with tempfile.TemporaryDirectory(dir=releases, prefix='.staging-') as staging:
                    stage = Path(staging) / 'package'
                    stage.mkdir()
                    unpack_verified(data, digest, stage, latest['version'])
                    validate(stage)
                    os.replace(stage, destination)
            # Validate again from the final path: relative paths may matter.
            validate(destination)
            return dict(result, status='updated', selected_root=str(destination),
                        selected_version=latest['version'])
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile) as exc:
        # The working release survives network, extraction and validation failures.
        return dict(result, status='deferred', reason='update_unavailable', detail=str(exc))
