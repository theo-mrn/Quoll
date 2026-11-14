"""`quoll new`: a project from nothing — a front-end, a back-end, services, or several of them in one repository
(front/, back/, services/<name>/) — with its CI, Dockerfiles and, optionally, its delivery and its GitHub/GitLab
repository."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import questionary
import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from quoll import languages, platforms
from quoll.commands import cd as cd_command
from quoll.commands import ci as ci_command
from quoll.commands import docker as docker_command
from quoll.commands import k8s as k8s_command
from quoll.commands._common import ask, check_platform, ensure_token, platform_option
from quoll.console import console
from quoll.docker.config import save_config as save_docker_config
from quoll.languages.base import Starter, StarterOptions
from quoll.platforms import PlatformError
from quoll.starters import StarterError
from quoll.workspace import member_name

# Where each part goes when the repository holds several.
DIRECTORIES = {"front": "front", "back": "back"}
SERVICES_DIRECTORY = "services"
# Runtime versions offered when none is given: (label, versions), the default first.
RUNTIME_CHOICES = {
    "node": ("Node.js", ["24", "22", "20"]),
    "python": ("Python", ["3.14", "3.13", "3.12"]),
    "go": ("Go", ["1.27", "1.26"]),
}

@dataclass
class Part:
    """A project of the repository to create: where, from which starter."""

    directory: str
    starter: Starter
    version: str
    package: str

    @property
    def label(self) -> str:
        return self.starter.label + (f" {self.version}" if self.version else "")


_GITIGNORE = """# Each project ignores its own files (front/.gitignore, back/.gitignore...).
.env
.DS_Store
.idea/
.vscode/
"""


def new(
    name: Optional[str] = typer.Argument(None, help="Project name: lowercase letters, digits and dashes."),
    parent: Path = typer.Option(Path("."), "--dir", "-d", help="Where to create the project's directory."),
    front: Optional[str] = typer.Option(
        None, help="Front-end starter, e.g. angular, or angular@18 for a version ('none' for no front-end)."
    ),
    back: Optional[str] = typer.Option(
        None, help="Back-end starter, e.g. express, or express@4 ('none' for no back-end)."
    ),
    services: List[str] = typer.Option(
        [], "--service", help="A service in services/<name>: NAME=STARTER[@VERSION], e.g. orders=express (repeatable)."
    ),
    node: Optional[str] = typer.Option(None, "--node", help="Node.js version of the Node-based parts, e.g. 22."),
    python: Optional[str] = typer.Option(None, "--python", help="Python version of the Python parts, e.g. 3.13."),
    go: Optional[str] = typer.Option(None, "--go", help="Go version of the Go parts, e.g. 1.26."),
    platform: Optional[str] = platform_option(),
    delivery: Optional[bool] = typer.Option(None, "--cd/--no-cd", help="Also publish the images (quoll cd)."),
    kubernetes: Optional[bool] = typer.Option(
        None, "--k8s/--no-k8s", help="A Helm chart per project, deployed by the delivery (quoll k8s)."
    ),
    remote: Optional[bool] = typer.Option(
        None, "--remote/--local", help="Create the GitHub/GitLab repository, push, protect the default branch."
    ),
    private: bool = typer.Option(True, "--private/--public", help="Visibility of the created repository."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask: use the options and defaults."),
) -> None:
    """Create a project from nothing: front/, back/, services/<name>/ (or one of them), CI, Dockerfiles, delivery,
    repository."""
    check_platform(platform)
    console.print("\n[bold]quoll new[/bold]\n")

    if name is None:
        name = "app" if yes else ask(questionary.text("Project name", validate=_valid_name))
    if _valid_name(name) is not True:
        console.print(f"[red]Error:[/red] {_valid_name(name)}")
        raise typer.Exit(1)
    root = parent.resolve() / name
    if root.exists() and any(root.iterdir()):
        console.print(f"[red]Error:[/red] {root} exists and isn't empty.")
        raise typer.Exit(1)

    picked = [p for p in (_pick("front", front, yes), _pick("back", back, yes)) if p]
    picked_services = [parse_service(spec) for spec in services]
    if not picked and not picked_services:
        console.print("[red]Error:[/red] nothing to create: choose a front-end, a back-end or services.")
        raise typer.Exit(1)
    several = len(picked) + len(picked_services) > 1
    parts = [
        Part(DIRECTORIES[role] if several else ".", starter, version, f"{name}-{role}" if several else name)
        for role, starter, version in picked
    ] + [Part(f"{SERVICES_DIRECTORY}/{n}" if several else ".", s, v, n) for n, s, v in picked_services]
    runtimes = {"node": node, "python": python, "go": go}
    for runtime, version in runtimes.items():
        used = [p.starter for p in parts if p.starter.runtime == runtime]
        if version is None and not yes and used:
            label, choices = RUNTIME_CHOICES[runtime]
            runtimes[runtime] = ask(questionary.select(f"{label} version", choices=choices,
                                                       default=used[0].runtime_default or choices[0]))
    runtimes = {runtime: version or "" for runtime, version in runtimes.items()}
    if platform is None:
        platform = "github" if yes else ask(questionary.select(
            "Hosting platform",
            choices=[questionary.Choice(platforms.get(n).label, n) for n in platforms.NAMES],
        ))
    if delivery is None:
        delivery = not yes and ask(questionary.confirm("Publish the images (build, scan, push)?", default=True))
    if kubernetes is None:
        kubernetes = not yes and ask(questionary.confirm(
            "Deploy to Kubernetes (Helm charts; staging on each push, production on v* tags)?", default=delivery
        ))
    if remote is None:
        label = platforms.get(platform).label
        remote = not yes and ask(questionary.confirm(f"Create the {label} repository and push?", default=True))

    # One part: the repository is the project. Several: a workspace, one directory each.
    notes: List[str] = []
    root.mkdir(parents=True, exist_ok=True)
    target = platforms.get(platform)
    repo = None

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=False) as progress:
        for part in parts:
            notes += create_part(root, name, part, runtimes, progress)

        if several:
            (root / ".gitignore").write_text(_GITIGNORE)
            (root / "README.md").write_text(_readme(name, parts))
        _git(root, "init", "-q", "-b", "main")

        if remote:
            task = progress.add_task(f"Creating the {target.label} repository...")
            if not ensure_token(platform):
                progress.stop()
                console.print(f"[red]Error:[/red] no {target.label} token.")
                raise typer.Exit(1)
            try:
                repo = target.api().create_repo(name, private=private)
            except PlatformError as e:
                progress.stop()
                console.print(f"[red]{target.label} error:[/red] {e}")
                raise typer.Exit(1)
            # Before the CI and the delivery: their defaults (image names...) come from the remote.
            _git(root, "remote", "add", "origin", repo.clone_url)
            progress.update(task, description=f"[green]✓[/green] {target.label} repository: {repo.web_url}")

        task = progress.add_task("Generating the CI, the Dockerfiles" + (" and the delivery..." if delivery else "..."))
        # Docker first: the CI then builds and scans the images.
        steps: List[Tuple[str, Callable[[], None]]] = [("Docker", docker_init(root / p.directory)) for p in parts]
        by_role = {p.starter.role: p for p in parts if p.directory in DIRECTORIES.values()}
        if "front" in by_role and "back" in by_role:
            steps.append(("Docker", proxy_api(root, by_role["front"], by_role["back"])))
        steps.append(
            ("CI", lambda: ci_command.init(project_dir=root, yes=True, force=True, platform=platform, local=True))
        )
        if several:
            # Now a workspace: the compose.yaml running every project.
            steps.append(("Docker", docker_init(root)))
        if kubernetes:
            # Before the delivery: it deploys the charts.
            steps.append(("Kubernetes", lambda: k8s_command.init(project_dir=root, yes=True, force=False)))
        if delivery:
            steps.append(("CD", lambda: cd_command.init(
                project_dir=root, yes=True, force=False, platform=platform, registry=None, image=None
            )))
        for label, run in steps:
            quiet(label, run, progress)
        done = "CI, Dockerfiles" + (", Helm charts" if kubernetes else "") + (", delivery" if delivery else "")
        progress.update(task, description=f"[green]✓[/green] {done}")

        _git(root, "add", "-A")
        committed = _git(root, "commit", "-q", "-m", f"chore: create {name} with quoll", check=False)
        if remote and repo and committed:
            task = progress.add_task("Pushing and protecting the default branch...")
            pushed = _git(root, "push", "-q", "-u", "origin", "main", check=False)
            warnings = []
            if pushed:
                try:
                    api = target.api()
                    warnings = api.protect_branch(repo.path, "main", required_checks=target.required_checks)
                    if target.schedules_via_api:
                        api.ensure_schedule(repo.path, "main", "0 6 * * 1")
                except PlatformError as e:
                    warnings.append(str(e))
            progress.update(task, description="[green]✓[/green] Pushed, main protected" if pushed
                            else "[yellow]![/yellow] Push failed: push the main branch yourself")
            for warning in warnings:
                progress.console.print(f"[yellow]![/yellow] {warning}")

    for note in notes:
        console.print(f"[yellow]![/yellow] {note}")
    if not committed:
        console.print("[yellow]![/yellow] Nothing committed (is git's user.name / user.email set?): commit yourself.")
    _summary(root, name, parts, repo)


def create_part(root: Path, name: str, part: Part, runtimes: Dict[str, str], progress: Progress) -> List[str]:
    """Run `part`'s starter in its directory; the starter's notes."""
    where = root / part.directory
    where.mkdir(parents=True, exist_ok=True)
    runtime = runtimes.get(part.starter.runtime, "")
    details = f" ({RUNTIME_CHOICES[part.starter.runtime][0]} {runtime})" if runtime else ""
    shown = f"{name}/" if part.directory == "." else f"{name}/{part.directory}/"
    task = progress.add_task(f"Creating {part.label}{details} in {shown}...")
    try:
        notes = part.starter.create(where, StarterOptions(part.package, part.version, runtime)) or []
    except StarterError as e:
        progress.stop()
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    progress.update(task, description=f"[green]✓[/green] {part.label}{details} in {shown}")
    return notes


def docker_init(directory: Path) -> Callable[[], None]:
    return lambda: docker_command.init(project_dir=directory, yes=True, force=False, command="")


def proxy_api(root: Path, front: Part, back: Part) -> Callable[[], None]:
    """The front-end calls the back-end at /api/, on its own origin (no CORS): in development, through its dev
    server; deployed, to BACK_URL (set by the workspace's compose.yaml and charts) — through nginx for a static
    site, the app's own server otherwise."""

    def run() -> None:
        variable = f"{member_name(back.directory).upper().replace('-', '_')}_URL"
        if front.starter.proxy:
            port = docker_command._load(root / back.directory).port
            front.starter.proxy(root / front.directory, "/api", f"http://localhost:{port}", variable)
        docker = docker_command._load(root / front.directory)
        if docker.static:
            docker.proxy = {"/api/": variable}
            save_docker_config(root / front.directory, docker)
            docker_command.update(project_dir=root / front.directory, yes=True, force=False)

    return run


def quiet(label: str, run: Callable[[], None], progress: Progress) -> None:
    """Run another quoll command; its own report would drown this one: shown only when something goes wrong."""
    with console.capture() as captured:
        try:
            run()
            failed = False
        except typer.Exit as e:
            failed = bool(e.exit_code)
    if failed:
        progress.stop()
        console.print(captured.get())
        console.print(f"[red]Error:[/red] quoll {label.lower()} failed.")
        raise typer.Exit(1)


def parse_service(spec: str) -> Tuple[str, Starter, str]:
    """NAME=STARTER[@VERSION] -> (name, starter, version)."""
    service, _, choice = spec.partition("=")
    if _valid_name(service) is not True or not choice:
        console.print(f"[red]Error:[/red] --service {spec}: expected NAME=STARTER, e.g. orders=express")
        raise typer.Exit(1)
    starter_name, _, version = choice.partition("@")
    by_name = {s.name: s for s in languages.starters()}
    if starter_name not in by_name:
        console.print(f"[red]Error:[/red] unknown starter '{starter_name}' (expected one of: {', '.join(by_name)}).")
        raise typer.Exit(1)
    return service, by_name[starter_name], version


def _pick(role: str, choice: Optional[str], yes: bool) -> Optional[Tuple[str, Starter, str]]:
    """(role, starter, version) for `role`: from `choice` ("angular", "angular@18"), else asked."""
    starters = languages.starters(role)
    by_name = {s.name: s for s in starters}
    asked = choice is None and not yes
    if asked:
        choice = ask(questionary.select(
            f"{role.capitalize()}-end",
            choices=[*(questionary.Choice(s.label, s.name) for s in starters), questionary.Choice("None", "none")],
        ))
    if choice in (None, "none"):
        return None
    starter_name, _, version = choice.partition("@")
    if starter_name not in by_name:
        console.print(f"[red]Error:[/red] unknown {role}-end '{starter_name}' (expected one of: {', '.join(by_name)}).")
        raise typer.Exit(1)
    starter = by_name[starter_name]
    if asked:
        version = ask(questionary.text(f"{starter.label} version (Enter: the latest)", default=""))
    return role, starter, version.strip()


def _valid_name(value: str):
    if re.fullmatch(r"[a-z][a-z0-9-]*", value or ""):
        return True
    return "lowercase letters, digits and dashes, starting with a letter"


def _git(root: Path, *args: str, check: bool = True) -> bool:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode != 0 and check:
        console.print(f"[red]Error:[/red] git {args[0]} failed: {result.stderr.strip()}")
        raise typer.Exit(1)
    return result.returncode == 0


def _readme(name: str, parts: List[Part]) -> str:
    listed = "\n".join(f"- [`{p.directory}/`]({p.directory}/): {p.label}" for p in parts)
    return f"""# {name}

{listed}

`docker compose up --build` runs them all, with their databases: each reaches the others at `<NAME>_URL`
(e.g. `BACK_URL=http://back:3000`). Each project also has its own README, Dockerfile and `compose.yaml`.

The CI, the Docker files and the delivery are generated by [quoll](https://github.com/theo-mrn/Quoll)
from the `quoll.toml` files: change them, then run `quoll ci update` (or `quoll docker update`, `quoll cd update`).
Add a service with `quoll add service <name>=express` (it lands in `services/<name>/`).
"""


def _summary(root: Path, name: str, parts: List[Part], repo) -> None:
    console.print(f"\n[bold green]✓ {name} is ready:[/bold green] {root}")
    if repo:
        console.print(f"  {repo.web_url}")
    console.print("\n[dim]Next steps:[/dim]")
    for part in parts:
        where = name if part.directory == "." else f"{name}/{part.directory}"
        run = "npm start" if part.starter.role == "front" else "npm run dev"
        console.print(f"  cd {where} && {run}")
    if len(parts) > 1:
        console.print(f"  cd {name} && docker compose up --build   # everything, with the databases")
    else:
        console.print("  docker compose up --build")
