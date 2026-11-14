"""A new Next.js application, from its own generator (create-next-app: TypeScript, App Router, ESLint, Tailwind), at
the chosen major (`nextjs@15`), the latest by default; a standalone build for a small image, a Vitest test of the
home page, Prettier."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from quoll.languages.base import Starter, StarterOptions
from quoll.languages.node.ci import QUOLL_FILES
from quoll.languages.node.starter import NODE_DEFAULT
from quoll.starters import StarterError, install_locally, run, write

TEST_DEPENDENCIES = ["vitest", "@vitest/coverage-v8", "@vitejs/plugin-react", "jsdom", "@testing-library/react"]

_VITEST_CONFIG = """import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom" },
});
"""

_PAGE_TEST = """import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import Home from "./page";

test("renders the home page", () => {
  render(<Home />);
  expect(screen.getByRole("heading", { level: 1 })).toBeDefined();
});
"""

# Next.js 16 calls its request interceptor "proxy" (src/proxy.ts); before, "middleware".
_PROXY = """import {{ NextResponse, type NextRequest }} from "next/server";

// {path} goes to the API: {variable} in the containers (compose.yaml, Kubernetes), the local one otherwise. Read on
// each request, so one build runs everywhere.
export function {function}(request: NextRequest) {{
  const target = new URL(
    request.nextUrl.pathname + request.nextUrl.search,
    process.env.{variable} ?? "{url}",
  );
  return NextResponse.rewrite(target);
}}

export const config = {{ matcher: "{path}/:path*" }};
"""


def create(directory: Path, options: StarterOptions) -> List[str]:
    runtime = options.runtime

    def npm(*args: str) -> None:
        run(["npm", *args], directory, "node", runtime)

    generator = f"create-next-app@{options.version or 'latest'}"
    run(["npx", "-y", generator, ".", "--ts", "--eslint", "--app", "--src-dir", "--tailwind", "--import-alias", "@/*",
         "--use-npm", "--disable-git", "--yes"], directory, "node", runtime)
    # Notes for coding assistants some versions add: not part of the project.
    for extra in ("AGENTS.md", "CLAUDE.md"):
        (directory / extra).unlink(missing_ok=True)

    package = json.loads((directory / "package.json").read_text())
    package["name"] = options.name
    package["scripts"]["test"] = "vitest run"
    (directory / "package.json").write_text(json.dumps(package, indent=2) + "\n")
    _standalone(directory)

    npm("install", "--save-dev", *TEST_DEPENDENCIES, "prettier", f"@types/node@{runtime or NODE_DEFAULT}")
    write(directory, {
        "vitest.config.mts": _VITEST_CONFIG,
        "src/app/page.test.tsx": _PAGE_TEST,
        ".nvmrc": f"{runtime or NODE_DEFAULT}\n",
        # quoll's files keep quoll's format when the project's Prettier runs.
        ".prettierignore": "# Written by quoll: their format is quoll's.\n" + "\n".join(QUOLL_FILES) + "\n.next/\n",
    })
    run(["npx", "prettier", "--write", "."], directory, "node", runtime)
    return install_locally(directory, runtime, ["npm", "ci"], "node_modules")


def proxy(directory: Path, path: str, url: str, variable: str = "BACK_URL") -> None:
    """The app forwards `path` to the API at runtime: to `variable`'s URL, `url` when it isn't set."""
    major = int(re.match(r"\D*(\d+)", json.loads((directory / "package.json").read_text())["dependencies"]["next"])[1])
    name = "proxy" if major >= 16 else "middleware"
    write(directory, {f"src/{name}.ts": _PROXY.format(path=path, url=url, variable=variable, function=name)})


def _standalone(directory: Path) -> None:
    """output: "standalone": the image ships the server with only the dependencies it uses."""
    config = next((directory / name for name in ("next.config.ts", "next.config.mjs", "next.config.js")
                   if (directory / name).exists()), None)
    if config is None:
        raise StarterError("create-next-app wrote no next.config")
    text, count = re.subn(r"(const nextConfig(?:: NextConfig)? = \{\n)", r'\1  output: "standalone",\n',
                          config.read_text(), count=1)
    if not count:
        raise StarterError(f"{config.name}: no `const nextConfig = {{` to set output: standalone in")
    config.write_text(text)


starter = Starter(
    name="nextjs", label="Next.js", role="front", create=create, dev="npm run dev", runtime="node",
    runtime_default=NODE_DEFAULT,
    proxy=proxy,
)
