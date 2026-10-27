"""Rehearse runtime migration and recovery with isolated synthetic state.

Run with an already prepared, security-patched interpreter. The rehearsal
downloads the pinned production packages into temporary runtime generations.
It never selects the user's runtime or reads a private church folder.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.handbuilt_runtime import ACTIVE_RUNTIME_POINTER, RuntimeManager


def fingerprint(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob('*') if path.is_file() and not path.is_symlink()
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='handbuilt-runtime-rehearsal-') as temporary:
        support = Path(temporary).resolve() / 'support' / 'runtime'
        legacy = support / 'python'
        subprocess.run([sys.executable, '-I', '-m', 'venv', '--without-pip', str(legacy)], check=True)
        # Metadata only: no affected pip code is downloaded or executed.
        site = next(legacy.glob('lib/python*/site-packages'), legacy / 'Lib' / 'site-packages')
        metadata = site / 'pip-26.2.1.dist-info' / 'METADATA'
        metadata.parent.mkdir(parents=True)
        metadata.write_text('Metadata-Version: 2.1\nName: pip\nVersion: 26.2.1\n')
        (legacy / 'keep-this-runtime.txt').write_text('Synthetic recovery marker\n')
        before_legacy = fingerprint(legacy)
        manager = RuntimeManager(repo_root=Path(__file__).resolve().parents[1],
                                 runtime_root=support, bootstrap_python=sys.executable)
        assert manager.doctor(capability='workspace')['status'] != 'ready'
        prepared = manager.setup()
        assert prepared['status'] == 'ready', prepared
        assert prepared['migration']['verified'], prepared
        assert prepared['migration']['retained_previous'] == str(legacy), prepared
        assert manager.paths.environment != legacy
        assert fingerprint(legacy) == before_legacy
        selected = manager.paths.environment
        pointer = support / ACTIVE_RUNTIME_POINTER
        pointer_before_failure = pointer.read_bytes()

        def fail_requirements(command, **kwargs):
            if '--requirement' in command:
                return subprocess.CompletedProcess(command, 1, '', 'Synthetic install failure')
            return subprocess.run(command, **kwargs)

        failing = RuntimeManager(repo_root=manager.repo_root, runtime_root=support,
                                 bootstrap_python=sys.executable, runner=fail_requirements)
        failure = failing.install_requirements()
        assert failure['status'] == 'install-failed', failure
        assert not failure['migration'].get('recovery_required', False), failure
        assert pointer.read_bytes() == pointer_before_failure
        assert selected.is_dir() and fingerprint(legacy) == before_legacy

        refused = manager.rollback()
        assert refused['status'] == 'install-failed', refused
        assert pointer.read_bytes() == pointer_before_failure
        replacement = manager.install_requirements()
        assert replacement['status'] == 'ready', replacement
        assert manager.paths.environment != selected
        recovered = manager.rollback()
        assert recovered['status'] == 'ready', recovered
        assert manager.paths.environment == selected
        assert manager.verify()['status'] == 'ready'
        assert fingerprint(legacy) == before_legacy
        print(json.dumps({
            'status': 'passed', 'legacy_files_unchanged': True,
            'failed_install_kept_pointer': True,
            'rollback_to_incomplete_legacy_refused': True,
            'rollback_to_verified_generation': True,
            'python_version': prepared['python']['managed_version'],
        }, indent=2))


if __name__ == '__main__':
    main()
