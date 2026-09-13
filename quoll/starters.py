"""Templates and generators (`ng new`, `npm install`...) behind the starters of `quoll new`.

A generator runs with the local tool when it is installed and no runtime version is asked for; otherwise in a
container of that runtime's image, so that the project and its lockfile match the version it will run on.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

from quoll.languages.base import StarterOptions

# Runtimes' container images, by runtime and version.
IMAGES = {"node": "node:{version}"}


class StarterError(Exception):
    pass


def run(command: List[str], cwd: Path, runtime: str = "", version: str = "") -> None:
    """Run `command` in `cwd`: in the `runtime:version` image when a version is asked for or the tool is missing."""
    image = IMAGES[runtime].format(version=version or "latest") if runtime else ""
    if shutil.which(command[0]) and not version:
        full = command
    elif image and shutil.which("docker"):
        # The project's files stay the user's; caches go to the container's /tmp.
        user = ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []
        full = ["docker", "run", "--rm", "-v", f"{cwd}:/work", "-w", "/work", *user, "-e", "HOME=/tmp", image, *command]
    else:
        needed = f"Docker (to run {image})" if version else f"`{command[0]}` (or Docker)"
        raise StarterError(f"{needed} is needed to create this project")
    result = subprocess.run(full, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip().splitlines()
        raise StarterError(f"`{' '.join(command)}` failed:\n  " + "\n  ".join(output[-15:]))


def in_container(command: str, version: str) -> bool:
    """Whether `run` runs `command` in a container (a runtime version is asked for, or the tool is missing)."""
    return bool(version) or not shutil.which(command)


def install_locally(directory: Path, version: str, command: Sequence[str], folder: str) -> List[str]:
    """Dependencies installed in a (Linux) container hold its native binaries: reinstall them for this machine
    from the lock file, or leave `folder` out. Returns a note for the user, if any."""
    if not in_container(command[0], version):
        return []
    shutil.rmtree(directory / folder, ignore_errors=True)
    if shutil.which(command[0]):
        result = subprocess.run(list(command), cwd=directory, capture_output=True, text=True)
        if result.returncode == 0:
            return []
    return [f"{directory.name}: run `{' '.join(command)}` there before working locally."]


def write(directory: Path, files: dict) -> None:
    for rel, content in files.items():
        path = directory / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def from_template(
    template: Path,
    commands: Sequence[Sequence[str]] = (),
    *,
    runtime: str = "",
    runtime_default: str = "",
    version_default: str = "latest",
    local_install: Sequence[str] = (),
    local_folder: str = "",
    renamed: Optional[dict] = None,
):
    """A starter's `create` copying `template`, then running `commands` in the project.

    In files and commands, {{name}}, {{version}} (the framework's) and {{runtime}} (the runtime's) are replaced.
    When the commands ran in a container, `local_install` reinstalls `local_folder` for this machine.
    Templates live next to their plugin, in templates/<starter>/. Dot files are stored without their dot (see
    `renamed`), so they don't apply to quoll's own repository.
    """
    renamed = {
        "gitignore": ".gitignore",
        "env.example": ".env.example",
        "nvmrc": ".nvmrc",
        "prettierignore": ".prettierignore",
        **(renamed or {}),
    }

    def create(directory: Path, options: StarterOptions) -> List[str]:
        values = {
            "{{name}}": options.name,
            "{{version}}": options.version or version_default,
            "{{runtime}}": options.runtime or runtime_default,
        }

        def fill(text: str) -> str:
            for key, value in values.items():
                text = text.replace(key, value)
            return text

        files = {}
        for path in sorted(template.rglob("*")):
            if path.is_file():
                rel = path.relative_to(template).as_posix()
                files[renamed.get(rel, rel)] = fill(path.read_text())
        write(directory, files)
        for command in commands:
            run([fill(part) for part in command], directory, runtime, options.runtime)
        if local_install:
            return install_locally(directory, options.runtime, local_install, local_folder)
        return []

    return create
