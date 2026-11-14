"""The project's own steps from quoll.toml ([[ci.steps]]), merged into the generated jobs."""
from __future__ import annotations

from typing import TYPE_CHECKING, List

from quoll.ci.steps import Item, Step, step

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig, CustomStep


def extend(cfg: CIConfig, job: str, items: List[Item]) -> List[Item]:
    """`items` of a generated job with the custom steps of `job`: "before" ones right after the dependency
    installation (the language's `install` steps), "after" ones at the end."""
    before = [_step(s) for s in cfg.steps if s.job == job and s.when == "before"]
    after = [_step(s) for s in cfg.steps if s.job == job and s.when == "after"]
    if not before and not after:
        return items
    # By name: a job may run its own variant of the install step (C/C++ configures the test build with
    # coverage and sanitizers, the release build optimised), still the step that installs the dependencies.
    installed = {item.name for item in cfg.language.ci.install(cfg)} - {""}
    last = max((i for i, item in enumerate(items) if item.name in installed), default=-1)
    return [*items[: last + 1], *before, *items[last + 1 :], *after]


def _step(custom: CustomStep) -> Step:
    return step(
        custom.name,
        run=custom.run.strip(),
        uses=custom.uses,
        with_=custom.with_,
        env=custom.env,
        secrets=custom.secrets,
    )
