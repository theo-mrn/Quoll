"""Regenerating a workspace's shared files once its members changed (`quoll add service`, `quoll remove service`)."""
from __future__ import annotations

from pathlib import Path
from typing import List, NamedTuple, Optional, Set

from quoll import platforms
from quoll.commands import cd as cd_command
from quoll.commands import docker as docker_command
from quoll.config.quoll_toml import ConfigError
from quoll.console import console
from quoll.files import MARKER, PlannedFile, write
from quoll.platforms.github.ci import DEPENDABOT_PATH, render_dependabot
from quoll.workspace import load_deliveries, load_repo


class Snapshot(NamedTuple):
    """What quoll generated for the members before they changed."""

    paths: Set[Path]
    dependabot: Optional[str]


def generated(root: Path, platform: str) -> List[PlannedFile]:
    """Every file quoll generates from the members: the pipeline, the root compose.yaml, the deliveries, the charts
    (which know the other members' URLs)."""
    from quoll.commands.k8s import chart_files  # it refreshes the workspace too

    files = [*platforms.get(platform).ci_files(root, load_repo(root)), *docker_command._workspace_files(root)]
    files += chart_files(root)
    try:
        files += cd_command._plan(root, load_deliveries(root))
    except ConfigError:  # no member publishes an image
        pass
    return files


def snapshot(root: Path, platform: str) -> Snapshot:
    return Snapshot({f.path for f in generated(root, platform)}, _dependabot(root, platform))


def refresh(root: Path, platform: str, before: Snapshot, by_hand: str, members_changed: bool = True) -> None:
    """Write the files the change affects, delete the ones it made useless (a member's delivery...). Files written
    by hand are left alone: `by_hand` says what to change in them. Dependabot's config only follows the members."""
    files = generated(root, platform)
    for f in files:
        if f.changed and f.managed and not (f.create_only and f.existing is not None):
            write(root, [f])
            console.print(f"[green]✓[/green] {f.path}")
        elif f.changed and not f.managed:
            console.print(f"[yellow]![/yellow] {f.path} was written by hand: {by_hand}.")
    for path in sorted(before.paths - {f.path for f in files}):
        target = root / path
        if target.exists() and MARKER in target.read_text():
            target.unlink()
            remove_empty_parents(root, target)
            console.print(f"[green]✓[/green] {path} removed")

    # Dependabot's config is the project's once created: updated only if nobody changed it since.
    target = root / DEPENDABOT_PATH
    if members_changed and before.dependabot is not None and target.exists():
        current = _dependabot(root, platform)
        if target.read_text() != before.dependabot:
            console.print(f"[yellow]![/yellow] {DEPENDABOT_PATH} was edited: {by_hand}.")
        elif current is not None and current != before.dependabot:
            target.write_text(current)
            console.print(f"[green]✓[/green] {DEPENDABOT_PATH}")


def _dependabot(root: Path, platform: str) -> Optional[str]:
    """.github/dependabot.yml as quoll writes it for the current members (GitHub only)."""
    if platform != "github" or not (root / DEPENDABOT_PATH).exists():
        return None
    repo = load_repo(root)
    docker = [m.directory for m in repo.members if (root / m.directory / "Dockerfile").exists()]
    return render_dependabot(repo, docker)


def remove_empty_parents(root: Path, path: Path) -> None:
    directory = path.parent
    while directory != root and directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent
