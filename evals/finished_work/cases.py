"""Every finished-work case the runner knows. Adding a workflow means adding one entry.

A case says how to seed the invented church, what the pastor asks, how to grade the
files left behind, and which judges read what a program cannot. A case with a
`persona` is a conversation: a stand-in pastor answers from that fact sheet.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Case:
    name: str
    prompt: str | Callable[[Path], str]  # formatted with {church}, or built from the seeded church path
    seed: Callable[[Path], Path]     # builds the church folder at <run>/riverbend; may also prepare <run>
    grade: Callable[..., dict]       # (church, stream=..., fetch=...) -> {"checks": [...], ...}
    judges: Callable[..., dict]      # (church, graded, final, conversation, model, run_dir) -> {name: verdict}
    timeout: int = 2400              # seconds for one agent turn
    persona: str = ""                # fact sheet for the stand-in pastor; empty means one message
    max_exchanges: int = 8
    extra: dict = field(default_factory=dict)


# Each module defines CASE. Order here is the order of a full run.
MODULES = ("case_bulletin", "case_brief", "case_brand", "case_onboarding", "case_reflection", "case_video")


def load() -> dict[str, Case]:
    found = {}
    for name in MODULES:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name == name:
                continue
            raise
        found[module.CASE.name] = module.CASE
    return found
