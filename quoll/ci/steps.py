"""Platform-neutral CI steps.

Languages and frameworks describe their jobs with `Step` and `Cache`; each platform (see quoll/platforms) renders
them. GitHub Actions runs a step's `uses` action when it has one; GitLab CI runs its `run` command in the
language's container image.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Tuple, Union

# Stands for the absolute project directory in `Cache.env` values.
ROOT = "{root}"
# The job summary file in shell commands: GitHub's, or /dev/null on platforms without one.
SUMMARY_FILE = '"${GITHUB_STEP_SUMMARY:-/dev/null}"'


@dataclass(frozen=True)
class Step:
    name: str
    # Shell command. Required unless the step is a GitHub-only setup step (see CISteps.setup).
    run: str = ""
    # GitHub Action doing the same as `run`, used instead of it on GitHub.
    uses: str = ""
    with_: Mapping[str, Any] = field(default_factory=dict)
    id: str = ""
    env: Mapping[str, str] = field(default_factory=dict)
    # CI secrets (GitHub) / variables (GitLab) the step reads, as environment variables of the same name.
    secrets: Tuple[str, ...] = ()
    # Also runs when an earlier step failed (reports, uploads).
    always: bool = False
    # Its failure does not fail the job.
    optional: bool = False
    # Only feeds the job summary page: dropped on platforms without one.
    summary: bool = False


@dataclass(frozen=True)
class Cache:
    """Directories kept between runs, invalidated when `key_files` change."""

    key: str
    paths: Tuple[str, ...]
    # At most two on GitLab.
    key_files: Tuple[str, ...] = ()
    # GitHub caches are immutable: a change in these files saves a fresh one (restored from the previous).
    revision_files: Tuple[str, ...] = ()
    # Variables pointing the tools at `paths`; ROOT stands for the project directory.
    env: Mapping[str, str] = field(default_factory=dict)
    name: str = ""


Item = Union[Step, Cache]


def step(
    name: str,
    run: str = "",
    *,
    uses: str = "",
    with_: Optional[Mapping[str, Any]] = None,
    id_: str = "",
    env: Optional[Mapping[str, str]] = None,
    secrets: Sequence[str] = (),
    always: bool = False,
    optional: bool = False,
    summary: bool = False,
) -> Step:
    return Step(
        name=name,
        run=run,
        uses=uses,
        with_=dict(with_ or {}),
        id=id_,
        env=dict(env or {}),
        secrets=tuple(secrets),
        always=always,
        optional=optional,
        summary=summary,
    )


def on_github(cfg: Any, text: str) -> str:
    """`text` when the project's CI runs on GitHub, e.g. a linter flag printing GitHub annotations."""
    return text if cfg.platform == "github" else ""
