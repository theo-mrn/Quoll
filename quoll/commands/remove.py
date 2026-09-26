"""`quoll remove service`: take a project out of a workspace, and out of its CI, compose.yaml and delivery."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import questionary
import typer

from quoll import platforms
from quoll.ci.detect import configured_platform
from quoll.commands._common import DirOption, ask, resolve_dir
from quoll.commands._workspace import refresh, remove_empty_parents, snapshot
from quoll.config import quoll_toml
from quoll.config.quoll_toml import ConfigError
from quoll.console import console
from quoll.workspace import WorkspaceConfig, find_root, load_workspace, member_name

app = typer.Typer(help="Remove a project from a workspace.", no_args_is_help=True)


@app.command()
def service(
    name: str = typer.Argument(..., help="The project's name or directory, e.g. billing or services/billing."),
    project_dir: Path = DirOption,
    keep_files: bool = typer.Option(
        False, "--keep-files", help="Leave its directory in place: only take it out of the workspace."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask before deleting its directory."),
) -> None:
    """Delete a project of the workspace, and remove it from the pipeline, compose.yaml and delivery."""
    root = find_root(resolve_dir(project_dir))
    try:
        workspace = load_workspace(root)
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    if workspace is None:
        console.print("[red]Error:[/red] not a workspace: there is no project to remove.")
        raise typer.Exit(1)
    directory = next((m for m in workspace.members if name.strip("/") in (m, member_name(m))), None)
    if directory is None:
        console.print(f"[red]Error:[/red] no project named {name} (members: {', '.join(workspace.members)}).")
        raise typer.Exit(1)
    if len(workspace.members) == 1:
        console.print(f"[red]Error:[/red] {directory} is the workspace's only project.")
        raise typer.Exit(1)

    delete = not keep_files and (root / directory).exists()
    if delete and _uncommitted(root, directory):
        console.print(f"[red]Error:[/red] {directory} has uncommitted changes: commit them first (git keeps the "
                      "project in its history), or use --keep-files.")
        raise typer.Exit(1)
    if delete and not yes and not ask(questionary.confirm(f"Delete {directory}/ and everything in it?", default=False)):
        raise typer.Exit(1)

    platform = configured_platform(root) or platforms.detect(root, platforms.remote(root))
    before = snapshot(root, platform)
    members = [m for m in workspace.members if m != directory]
    quoll_toml.save_section(root, "workspace", WorkspaceConfig(members=members))
    if delete:
        shutil.rmtree(root / directory)
        remove_empty_parents(root, root / directory)
    console.print(f"[green]✓[/green] {directory} " + ("deleted" if delete else "taken out of the workspace"))
    refresh(root, platform, before, f"remove {member_name(directory)} from it yourself")

    variable = f"{member_name(directory).upper().replace('-', '_')}_URL"
    console.print(f"\n[bold green]✓ {member_name(directory)}[/bold green] removed. The others no longer get "
                  f"[bold]{variable}[/bold]: check that their code doesn't use it.")


def _uncommitted(root: Path, directory: str) -> bool:
    """True when git would lose changes to `directory` (modified or untracked files)."""
    done = subprocess.run(
        ["git", "status", "--porcelain", "--", directory], cwd=root, capture_output=True, text=True
    )
    return done.returncode == 0 and bool(done.stdout.strip())

