"""Optional end-to-end rehearsal using the prepared managed runtime and synthetic data."""
import hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import church_workflow as bridge
from tools import workflow_updates as updates
from tools.package_workflow import build_package
from tests.helpers import make_church

with tempfile.TemporaryDirectory(prefix='handbuilt-update-smoke-') as tmp:
    base = Path(tmp).resolve()
    church = make_church(base)
    for relative, text in {
        'CLAUDE.md': '# Local instructions\n\n## Sermon help\nAsk about my week first.\n',
        'AGENTS.md': '# My church choices\nPreserve my preferences.\n',
        'skills/local-newsletter/SKILL.md': '# Local newsletter\nUse our local template.\n',
        'skills/local-newsletter/template.md': '# Parish news\n',
    }.items():
        path = church / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (church / 'START-HERE.md').unlink()
    host = base / 'host'
    for relative in ('tools', 'skills', 'scaffold', 'handbook', '.codex-plugin', '.claude-plugin'):
        shutil.copytree(bridge.ROOT / relative, host / relative, ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('requirements.txt', 'LICENSE'):
        shutil.copy(bridge.ROOT / name, host)
    host_version = updates.package_version(host)
    major, minor, patch = updates.version(host_version)
    next_version = f'{major}.{minor + 1}.0'
    source = base / 'source'
    shutil.copytree(host, source)
    for name in ('.codex-plugin', '.claude-plugin'):
        manifest = source / name / 'plugin.json'
        data = json.loads(manifest.read_text())
        data['version'] = next_version
        manifest.write_text(json.dumps(data))
    subprocess.run(['git', 'init', str(source)], capture_output=True, check=True)
    subprocess.run(['git', '-C', str(source), 'add', '.'], capture_output=True, check=True)
    package = build_package(source, base / 'distribution')
    metadata = {'tag_name': 'v' + next_version, 'assets': [{'name': name, 'browser_download_url': f'https://github.com/{updates.REPOSITORY}/releases/download/v{next_version}/{name}'} for name in (updates.PACKAGE, updates.CHECKSUM)]}
    def download(url, limit):
        if url == updates.LATEST_URL:
            return json.dumps(metadata).encode()
        return (base / 'distribution' / url.rsplit('/', 1)[1]).read_bytes()
    actual = updates.select_release
    def select(current, store, validate):
        return actual(current, store, validate, download=download)
    before = {p.relative_to(church): p.read_bytes() for p in church.rglob('*') if p.is_file() and p.name != 'handbuilt.py'}
    with mock.patch.object(bridge, 'ROOT', host), mock.patch('tools.handbuilt_runtime.default_runtime_root', return_value=base/'support/runtime'), mock.patch.object(updates, 'select_release', side_effect=select):
        bridge.connect(church)
        result, code = bridge._start(church, 'bulletin')
    assert code == 0, result
    assert result['installation']['plugin_version'] == next_version, result
    assert result['app_loaded_identity']['version'] == host_version, result
    assert all((church / name).read_bytes() == data for name, data in before.items())
    assert not (church / 'START-HERE.md').exists()
    history = subprocess.run(result['launcher'] + ['recovery', 'history'], capture_output=True, text=True)
    assert history.returncode == 0, history.stdout + history.stderr
    assert json.loads(history.stdout)['snapshots'], history.stdout
    # Run a real workflow using the fixed returned prefix, outside the church cwd.
    process = subprocess.run(result['launcher'] + ['sermon-research', 'orient', '--date', '2026-09-13'], cwd=base, capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr
    # An offline start through the old host must retain the selected release.
    def offline(current, store, validate):
        def unavailable(*args):
            raise OSError('offline rehearsal')
        return actual(current, store, validate, download=unavailable, force=True)
    with mock.patch.object(bridge, 'ROOT', host), mock.patch('tools.handbuilt_runtime.default_runtime_root', return_value=base/'support/runtime'), mock.patch.object(updates, 'select_release', side_effect=offline):
        restarted, code = bridge._start(church, 'bulletin')
    assert code == 0 and restarted['installation']['plugin_version'] == next_version, restarted
    report = {'offline_retained_version': restarted['installation']['plugin_version'], 'status': 'passed', 'app_version': result['app_loaded_identity']['version'], 'workflow_version': result['installation']['plugin_version'], 'updated': result['updates']['status'], 'church_source_files_unchanged': len(before), 'real_workflow_exit': process.returncode, 'package_sha256': package['zip_sha256']}
    print(json.dumps(report, indent=2))
