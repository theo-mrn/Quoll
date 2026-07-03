from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from quoll.languages.base import Detection, DockerDefaults, DockerImage
from quoll.languages.node.detect import dependencies, package_json, scripts_of
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig

PNPM_DEFAULT = "10"

# (frozen install, plain install)
_INSTALL = {
    "npm": ("npm ci", "npm install"),
    "pnpm": ("pnpm install --frozen-lockfile", "pnpm install"),
    "yarn": ("yarn install --immutable", "yarn install"),
    "yarn-classic": ("yarn install --frozen-lockfile", "yarn install"),
    "bun": ("bun install --frozen-lockfile", "bun install"),
}
# Removes devDependencies after the build. Yarn Berry has no equivalent without a plugin.
_PRUNE = {
    "npm": "npm prune --omit=dev",
    "pnpm": "pnpm prune --prod",
    "yarn-classic": "yarn install --production --ignore-scripts --prefer-offline",
    "bun": "rm -rf node_modules && bun install --production --ignore-scripts",
}
_CACHE = {
    "npm": "/root/.npm",
    "pnpm": "/root/.local/share/pnpm/store",
    "yarn": "/root/.yarn/berry/cache",
    "yarn-classic": "/usr/local/share/.cache/yarn",
    "bun": "/root/.bun/install/cache",
}
_LOCKFILES = {
    "npm": ("package-lock.json",),
    "pnpm": ("pnpm-lock.yaml",),
    "yarn": ("yarn.lock",),
    "yarn-classic": ("yarn.lock",),
    "bun": ("bun.lock", "bun.lockb"),
}
# Files and directories the install reads besides package.json and the lockfile.
_INSTALL_FILES = (".npmrc", "pnpm-workspace.yaml", ".yarnrc.yml", ".yarnrc", "bunfig.toml")
_INSTALL_DIRS = (".yarn/releases", ".yarn/plugins", ".yarn/patches", "patches")
# A Vite project without one of these is a static single-page app.
_SERVER_DEPS = {"express", "fastify", "koa", "hono", "@hono/node-server", "@nestjs/core", "next", "nuxt"}


class NodeImage(DockerImage):
    # Static sites: unknown paths fall back to index.html (single-page apps) or to 404.html.
    spa = True

    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        pkg = package_json(project)
        deps = dependencies(pkg)
        scripts = scripts_of(pkg)
        if "vite" in deps and det.build_command and "start" not in scripts and not _SERVER_DEPS & deps.keys():
            return DockerDefaults(port=8080, build_command=det.build_command, output_dir="dist", static=True)
        command = _start_command(project, pkg, scripts)
        warnings = [] if command else ["Couldn't infer how to start the app — set docker.command in quoll.toml."]
        return DockerDefaults(port=3000, command=command, build_command=det.build_command, warnings=warnings)

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        pm = cfg.package_manager
        lockfile = next((f for f in _LOCKFILES[pm] if project.exists(f)), "")
        bun = pm == "bun"
        return {
            "build_image": "oven/bun:1" if bun else f"node:{cfg.version}-slim",
            "runtime_image": "oven/bun:1-slim" if bun else f"node:{cfg.version}-slim",
            "user": "bun" if bun else "node",
            # Both images' user has uid and gid 1000.
            "uid": "1000:1000",
            "setup": _setup(project, cfg),
            "install": _INSTALL[pm][0 if lockfile else 1],
            "install_files": ["package.json", *([lockfile] if lockfile else []), *_present(project, _INSTALL_FILES)],
            "install_dirs": _present(project, _INSTALL_DIRS),
            "cache": _CACHE[pm],
            "prune": _PRUNE.get(pm, ""),
            "spa": self.spa,
            "build_env": self.build_env(cfg),
            "env": {"NODE_ENV": "production", "PORT": str(cfg.port), "HOST": "0.0.0.0", **self.env(cfg)},
        }

    def writable_paths(self, cfg: DockerConfig) -> Optional[List[str]]:
        if not cfg.static:
            return ["/tmp"]
        # nginx's temporary files; with a proxy, the configuration its entrypoint writes from the template.
        return ["/tmp", "/var/cache/nginx", *(["/etc/nginx/conf.d"] if cfg.proxy else [])]

    def build_env(self, cfg: DockerConfig) -> Dict[str, str]:
        """Environment of the build step."""
        return {}

    def env(self, cfg: DockerConfig) -> Dict[str, str]:
        """Extra runtime environment variables."""
        return {}

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        return [
            "**/node_modules",
            ".next",
            ".nuxt",
            ".output",
            ".svelte-kit",
            ".astro",
            ".angular",
            "dist",
            "build",
            "coverage",
            "npm-debug.log*",
            ".env",
            ".env.*",
            "!.env.example",
        ]


def _setup(project: Project, cfg: DockerConfig) -> str:
    """Command installing the package manager in the build image."""
    declared = str(package_json(project).get("packageManager", "")).split("+")[0]
    if cfg.package_manager == "pnpm":
        version = declared.split("@")[1] if declared.startswith("pnpm@") else cfg.package_manager_version
        return f"npm install --global pnpm@{version or PNPM_DEFAULT}"
    if cfg.package_manager == "yarn":
        return "corepack enable"
    return ""


def _start_command(project: Project, pkg: dict, scripts: Dict[str, str]) -> str:
    if scripts.get("start"):
        return scripts["start"]
    if pkg.get("main"):
        return f"node {pkg['main']}"
    for name in ("server.js", "index.js", "src/server.js", "src/index.js"):
        if project.exists(name):
            return f"node {name}"
    return ""


def _present(project: Project, names: tuple) -> List[str]:
    return [n for n in names if project.exists(n)]
