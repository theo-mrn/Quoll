"""A new React application, from Vite's own generator (create-vite, TypeScript), tested with Vitest and Testing
Library, formatted with Prettier. React's major can be chosen: `react@18`."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from quoll.languages.base import Starter, StarterOptions
from quoll.languages.node.ci import QUOLL_FILES
from quoll.languages.node.starter import NODE_DEFAULT
from quoll.starters import StarterError, install_locally, run, write

TEST_DEPENDENCIES = ["vitest", "@vitest/coverage-v8", "jsdom", "@testing-library/react", "prettier"]

_SMOKE_TEST = """// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import App from "./App";

test("counts clicks", () => {
  render(<App />);
  const button = screen.getByRole("button", { name: /count is 0/i });
  fireEvent.click(button);
  expect(button.textContent).toMatch(/count is 1/i);
});
"""


def create(directory: Path, options: StarterOptions) -> List[str]:
    runtime = options.runtime

    def npm(*args: str) -> None:
        run(["npm", *args], directory, "node", runtime)

    run(["npx", "-y", "create-vite@latest", ".", "--template", "react-ts", "--no-interactive"], directory, "node",
        runtime)
    package = json.loads((directory / "package.json").read_text())
    package["name"] = options.name
    package["scripts"]["test"] = "vitest run"
    (directory / "package.json").write_text(json.dumps(package, indent=2) + "\n")
    if options.version:
        major = options.version
        npm("install", "--save", f"react@{major}", f"react-dom@{major}")
        npm("install", "--save-dev", f"@types/react@{major}", f"@types/react-dom@{major}")
    npm("install", "--save-dev", *TEST_DEPENDENCIES, f"@types/node@{runtime or NODE_DEFAULT}")
    write(directory, {
        "src/App.test.tsx": _SMOKE_TEST,
        ".nvmrc": f"{runtime or NODE_DEFAULT}\n",
        # quoll's files keep quoll's format when the project's Prettier runs.
        ".prettierignore": "# Written by quoll: their format is quoll's.\n" + "\n".join(QUOLL_FILES) + "\n",
    })
    run(["npx", "prettier", "--write", "."], directory, "node", runtime)
    return install_locally(directory, runtime, ["npm", "ci"], "node_modules")


def proxy(directory: Path, path: str, url: str, variable: str = "") -> None:
    """Vite's dev server forwards `path` to the API (https://vite.dev/config/server-options#server-proxy)."""
    config = directory / "vite.config.ts"
    text = config.read_text()
    updated, count = re.subn(r"(plugins: \[[^\]]*\],\n)", rf'\1  server: {{ proxy: {{ "{path}": "{url}" }} }},\n',
                             text, count=1)
    if not count:
        raise StarterError(f"{config.name}: no `plugins: [...]` to add the dev server's proxy after")
    config.write_text(updated)


starter = Starter(
    name="react", label="React (Vite)", role="front", create=create, dev="npm run dev", runtime="node",
    runtime_default=NODE_DEFAULT,
    proxy=proxy,
)
