from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from quoll import platforms
from quoll.ci.detect import configured_platform
from quoll.commands._common import check_platform, ensure_token, platform_option
from quoll.console import console
from quoll.platforms import PlatformError

app = typer.Typer(help="Add a secret to the GitHub/GitLab repository and the local .env file.")


@app.callback(invoke_without_command=True)
def add_secret(
    repo: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository: name or owner/name (default: the git remote)."
    ),
    key: str = typer.Option(..., "--key", "-k", help="Secret name"),
    value: str = typer.Option(..., "--value", "-v", help="Secret value", hide_input=True),
    env_file: Path = typer.Option(Path(".env"), "--env-file", help="Path to local .env file"),
    platform: Optional[str] = platform_option(),
    local: bool = typer.Option(False, "--local", "--skip-github", help="Only update local .env"),
) -> None:
    """Add a secret to GitHub Actions secrets / GitLab CI/CD variables and the local .env file."""
    check_platform(platform)

    # --- Local .env ---
    _write_env(env_file, key, value)
    console.print(f"[green]✓[/green] Added {key} to {env_file}")

    if local:
        return

    # --- Repository ---
    project_dir = Path(".")
    remote = platforms.remote(project_dir)
    target = platforms.get(platform or configured_platform(project_dir) or platforms.detect(project_dir, remote))
    repo = repo or (remote.path if remote else None)
    if not repo:
        console.print("[red]Error:[/red] no git remote found — pass --repo.")
        raise typer.Exit(1)
    host = remote.host if remote and platforms.hosting(remote) == target.name else None
    if not ensure_token(target.name, host):
        raise typer.Exit(1)

    try:
        target.api(host).set_secrets(repo, {key: value})
        console.print(f"[green]✓[/green] Added {key} to {target.label} repo '{repo}'")
    except PlatformError as e:
        console.print(f"[red]{target.label} error:[/red] {e}")
        raise typer.Exit(1)


def _write_env(env_file: Path, key: str, value: str) -> None:
    lines: list[str] = []

    if env_file.exists():
        lines = env_file.read_text().splitlines()

    # Update existing key or append
    key_found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            lines[i] = f"{key}={value}"
            key_found = True
            break

    if not key_found:
        lines.append(f"{key}={value}")

    env_file.write_text("\n".join(lines) + "\n")
