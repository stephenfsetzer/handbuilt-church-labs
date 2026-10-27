"""Security floors for the managed Handbuilt Python runtime.

This module is policy data only. It does not access the network or install
software. Reviewed against the official Python release notice and PyPI release
metadata on 2026-10-27.

Primary sources:
- Python expedited security releases:
  https://discuss.python.org/t/python-3-15-2-3-14-10-3-13-18-3-12-16-and-3-11-18-are-out/109678
- Python 3.10 end of support and active release branches:
  https://www.python.org/getit/
- pip 26.2.2 release and provenance:
  https://pypi.org/project/pip/26.2.2/
- certifi 2026.10.19 release and provenance:
  https://pypi.org/project/certifi/2026.10.19/
- setuptools legacy Windows wheel-installation fix and release:
  https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w
  https://pypi.org/project/setuptools/84.1.0/
- Pillow 13.0.0 release metadata:
  https://pypi.org/project/Pillow/13.0.0/
- pypdf 6.21.2 release metadata:
  https://pypi.org/project/pypdf/6.21.2/
- Brotli 1.2.1 release metadata:
  https://pypi.org/project/Brotli/1.2.1/
- PyYAML 6.0.3 release metadata and platform wheel files:
  https://pypi.org/project/PyYAML/6.0.3/
- PyYAML 6.0.3 source build requirements:
  https://github.com/yaml/pyyaml/blob/6.0.3/pyproject.toml
- zopfli 0.4.3 stable ABI wheel metadata:
  https://pypi.org/project/zopfli/0.4.3/
- cffi 2.0.0 supported-branch wheel metadata:
  https://pypi.org/project/cffi/2.0.0/
"""

from __future__ import annotations

from collections.abc import Sequence


POLICY_AS_OF = "2026-10-27"
MINIMUM_PYTHON = (3, 11)
PYTHON_SECURITY_FLOORS = {
    (3, 11): (3, 11, 18),
    (3, 12): (3, 12, 16),
    (3, 13): (3, 13, 18),
    (3, 14): (3, 14, 10),
    (3, 15): (3, 15, 2),
}
SUPPORTED_RUNTIME_BRANCHES = ((3, 11), (3, 12), (3, 13), (3, 14))
PYTHON_RUNTIME_SUPPORT_URL = "https://pypi.org/project/PyYAML/6.0.3/"

PIP_VERSION = "26.2.2"
PIP_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/3f/06/"
    "3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/"
    "pip-26.2.2-py3-none-any.whl"
)
PIP_WHEEL_SHA256 = "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
CERTIFI_MINIMUM = "2026.10.19"

PYTHON_SUPPORT_URL = "https://www.python.org/getit/"
PYTHON_SECURITY_RELEASES_URL = (
    "https://discuss.python.org/t/"
    "python-3-15-2-3-14-10-3-13-18-3-12-16-and-3-11-18-are-out/109678"
)


def python_security_error(version: object) -> str | None:
    """Return a user-safe reason that a Python version fails this policy.

    Accepts a three-integer version tuple/list or a ``sys.version_info``-like
    object. When prerelease metadata is available, only final releases pass.
    A three-integer value is treated as final because it carries no
    prerelease metadata; callers that inspect the interpreter should pass its
    full ``sys.version_info`` object when they need prerelease detection.
    """
    if isinstance(version, (str, bytes)) or not isinstance(version, Sequence):
        return "Python version information is invalid; use a supported final release."

    try:
        if len(version) < 3:
            return "Python version information is incomplete; use a supported final release."
        parts = tuple(version[index] for index in range(3))
        if any(isinstance(part, bool) or not isinstance(part, int) for part in parts):
            return "Python version information is invalid; use a supported final release."
        major, minor, patch = parts
    except (IndexError, KeyError, TypeError):
        return "Python version information is invalid; use a supported final release."

    releaselevel = getattr(version, "releaselevel", None)
    if releaselevel is None:
        try:
            if len(version) > 3:
                candidate_level = version[3]
                if isinstance(candidate_level, str):
                    releaselevel = candidate_level
        except (IndexError, KeyError, TypeError):
            pass
    if releaselevel is not None and releaselevel != "final":
        return "Python prereleases and unknown release levels are not supported."

    branch = (major, minor)
    if branch < MINIMUM_PYTHON:
        return (
            f"Python {major}.{minor} is below the supported minimum of "
            f"Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}; see {PYTHON_SUPPORT_URL}"
        )

    floor = PYTHON_SECURITY_FLOORS.get(branch)
    if floor is None:
        return (
            f"Python {major}.{minor} has no reviewed security floor; use a supported "
            f"branch listed at {PYTHON_SUPPORT_URL}"
        )
    if parts < floor:
        required = ".".join(str(part) for part in floor)
        installed = ".".join(str(part) for part in parts)
        return f"Python {installed} is below the security minimum {required}."
    return None


def python_runtime_error(version: object) -> str | None:
    """Return why a Python version cannot run the managed plugin runtime.

    Security-reviewed Python 3.15 is deliberately not enabled until every
    pinned dependency has a compatible PyPI wheel. PyYAML 6.0.3, which is
    required by the plugin, does not publish CPython 3.15 wheels. The
    installer uses binary-only dependencies and must not fall back to an
    unpinned source build.
    """
    security_error = python_security_error(version)
    if security_error is not None:
        return security_error

    branch = (version[0], version[1])
    if branch not in SUPPORTED_RUNTIME_BRANCHES:
        return (
            f"Python {branch[0]}.{branch[1]} is not yet supported by the managed "
            f"runtime because a required dependency has no compatible wheel; "
            f"see {PYTHON_RUNTIME_SUPPORT_URL}"
        )
    return None
