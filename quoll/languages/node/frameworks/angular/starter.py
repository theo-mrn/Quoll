"""A new Angular application, from the official CLI of the chosen major (`angular@18`), the latest by default."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List

from quoll.languages.base import Starter, StarterOptions
from quoll.languages.node.ci import QUOLL_FILES
from quoll.languages.node.starter import NODE_DEFAULT
from quoll.starters import install_locally, run, write

LATEST = "22"
# Angular supports its current major and the two before it (https://angular.dev/reference/releases).
SUPPORTED = 3


def create(directory: Path, options: StarterOptions) -> List[str]:
    major = options.version or LATEST
    cli = f"@angular/cli@{major}"

    def ng(*args: str) -> None:
        # Run with the asked Node.js: the CLI checks it supports it, the lockfile matches it.
        run(["npx", "-y", *args], directory, "node", options.runtime)

    new = [cli, "new", options.name, "--directory", ".", "--defaults", "--skip-git", "--style", "css",
           "--ssr", "false", "--package-manager", "npm"]
    if int(major) >= 20:
        # Options of recent CLIs: no AI tools configuration; Vitest is the default runner since 21.
        new += ["--ai-config", "none"]
    ng(*new)
    # ESLint with Angular's rules: the CI's lint job runs `ng lint`.
    ng(f"@angular/cli@{major}", "add", f"angular-eslint@{major}", "--skip-confirmation")
    # The CLI's own files aren't all formatted the way its Prettier config says (when it has one).
    if "prettier" in (directory / "package.json").read_text():
        ng("prettier", "--write", ".")
    ignore = directory / ".prettierignore"
    existing = ignore.read_text() if ignore.exists() else ""
    write(directory, {
        ".nvmrc": f"{options.runtime or NODE_DEFAULT}\n",
        # quoll's files keep quoll's format when the project's Prettier runs.
        ".prettierignore": existing + "# Written by quoll: their format is quoll's.\n" + "\n".join(QUOLL_FILES) + "\n",
    })
    notes = install_locally(directory, options.runtime, ["npm", "ci"], "node_modules")
    if int(major) <= int(LATEST) - SUPPORTED:
        notes.append(
            f"Angular {major} no longer gets security fixes: the CI's dependency audit will fail on its known "
            f"vulnerabilities. Supported: {int(LATEST) - SUPPORTED + 1} to {LATEST}."
        )
    return notes


def proxy(directory: Path, path: str, url: str, variable: str = "") -> None:
    """`ng serve` forwards `path` to the API (https://angular.dev/tools/cli/serve#proxying-to-a-backend-server)."""
    write(directory, {"proxy.conf.json": json.dumps({path: {"target": url, "secure": False}}, indent=2) + "\n"})
    config = directory / "angular.json"
    workspace = json.loads(config.read_text())
    for project in workspace["projects"].values():
        serve = project.get("architect", {}).get("serve")
        if serve:
            serve.setdefault("options", {})["proxyConfig"] = "proxy.conf.json"
    config.write_text(json.dumps(workspace, indent=2) + "\n")
    # In the project's format when it uses Prettier (a dependency, or only its config in package.json): the CI
    # checks it.
    if "prettier" in (directory / "package.json").read_text():
        local = directory / "node_modules" / ".bin" / "prettier"
        command = [str(local)] if local.exists() else ["npx", "-y", "prettier"]
        subprocess.run([*command, "--write", "angular.json", "proxy.conf.json"], cwd=directory,
                       capture_output=True, check=True)


starter = Starter(
    name="angular", label="Angular", role="front", create=create, runtime="node", runtime_default=NODE_DEFAULT,
    proxy=proxy,
)
