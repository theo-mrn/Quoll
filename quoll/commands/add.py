"""`quoll add service`: a new project in an existing workspace, wired into its CI, compose.yaml and delivery."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from quoll import platforms
from quoll.cd.config import load_config as load_cd_config
from quoll.ci.config import save_config
from quoll.ci.detect import configured_platform, default_config, detect
from quoll.commands import cd as cd_command
from quoll.commands import k8s as k8s_command
from quoll.commands._common import DirOption, resolve_dir
from quoll.commands._workspace import Snapshot, refresh, snapshot
from quoll.commands.new import SERVICES_DIRECTORY, Part, create_part, docker_init, parse_service, quiet
from quoll.config import quoll_toml
from quoll.config.quoll_toml import ConfigError
from quoll.console import console
from quoll.k8s.config import load_config as load_k8s_config
from quoll.workspace import (
    RepoCIConfig,
    WorkspaceConfig,
    find_root,
    load_workspace,
    member_name,
    save_workspace,
)

app = typer.Typer(help="Add a project to a workspace.", no_args_is_help=True)


@app.command()
def service(
    spec: str = typer.Argument(..., help="NAME=STARTER[@VERSION], e.g. orders=express or orders=express@4."),
    project_dir: Path = DirOption,
    within: str = typer.Option(SERVICES_DIRECTORY, "--in", help="Directory holding the services."),
    node: Optional[str] = typer.Option(None, "--node", help="Node.js version, e.g. 22."),
    python: Optional[str] = typer.Option(None, "--python", help="Python version, e.g. 3.13."),
    go: Optional[str] = typer.Option(None, "--go", help="Go version, e.g. 1.26."),
) -> None:
    """Create a service in services/<name>, and add it to the workspace's CI, compose.yaml and delivery."""
    root = find_root(resolve_dir(project_dir))
    try:
        workspace = load_workspace(root)
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    data = quoll_toml.read(root)
    if workspace is None and "project" in data and "stack" in data["project"]:
        console.print(
            "[red]Error:[/red] this repository is a single project: a workspace keeps each project in a directory "
            "of its own (move it, e.g. to back/, then run `quoll ci init`)."
        )
        raise typer.Exit(1)

    name, starter, version = parse_service(spec)
    directory = f"{within.strip('/')}/{name}" if within.strip("/") else name
    members = list(workspace.members) if workspace else []
    if directory in members or member_name(directory) in {member_name(m) for m in members}:
        console.print(f"[red]Error:[/red] the workspace already has a project named {name}.")
        raise typer.Exit(1)
    if (root / directory).exists() and any((root / directory).iterdir()):
        console.print(f"[red]Error:[/red] {directory} exists and isn't empty.")
        raise typer.Exit(1)

    platform = configured_platform(root) or platforms.detect(root, platforms.remote(root))
    before = snapshot(root, platform) if workspace else Snapshot(set(), None)
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        runtimes = {"node": node or "", "python": python or "", "go": go or ""}
        notes = create_part(root, root.name, Part(directory, starter, version, name), runtimes, progress)
        quiet("Docker", docker_init(root / directory), progress)

        task = progress.add_task("Adding it to the workspace...")
        det = detect(root / directory)
        det.platform = platform
        save_config(root / directory, default_config(det))
        if workspace is None:
            save_workspace(root, [directory], RepoCIConfig(platform=platform))
        else:
            quoll_toml.save_section(root, "workspace", WorkspaceConfig(members=[*members, directory]))
        progress.update(task, description=f"[green]✓[/green] {directory} added to the workspace")

        # The delivery too, when the workspace already publishes images.
        if any("cd" in quoll_toml.read(root / m) for m in members):
            reference = next(load_cd_config(root / m) for m in members if "cd" in quoll_toml.read(root / m))
            quiet("CD", lambda: cd_command._configure(
                root / directory, root, member_name(directory), yes=True, force=False, platform=platform,
                registry=reference.registry, image=None,
            ), progress)

        # And its chart, deployed with the others: same namespaces.
        charted = [m for m in members if "k8s" in quoll_toml.read(root / m)]
        if charted:
            like = load_k8s_config(root / charted[0])
            quiet("Kubernetes", lambda: k8s_command._init(root, root / directory, yes=True, force=False, like=like),
                  progress)

    refresh(root, platform, before, f"add {name} to it yourself")

    for note in notes:
        console.print(f"[yellow]![/yellow] {note}")
    console.print(f"\n[bold green]✓ {name}[/bold green] is in {directory}/ — reachable from the others at "
                  f"[bold]{name.upper().replace('-', '_')}_URL[/bold]. Run everything:")
    console.print("  docker compose up --build")
