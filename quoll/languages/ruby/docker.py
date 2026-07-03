from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from quoll.languages.base import Detection, DockerDefaults, DockerImage
from quoll.languages.ruby.detect import has_gem
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig

# gem: (build packages, runtime packages) on Debian.
_NATIVE_GEMS = {
    "pg": ("libpq-dev", "libpq5"),
    "mysql2": ("default-libmysqlclient-dev", "libmariadb3"),
    "ruby-vips": ("", "libvips42t64"),
}


class RubyImage(DockerImage):
    def writable_paths(self, cfg: DockerConfig) -> Optional[List[str]]:
        # Ruby refuses a temporary directory anyone can write to without the sticky bit — what Kubernetes' emptyDir
        # volumes are: the root filesystem stays writable.
        return None

    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        m = re.search(r"^web:\s*(.+)$", project.read_text("Procfile"), re.M)
        if m:
            return DockerDefaults(port=3000, command=m.group(1).strip())
        if project.exists("config.ru"):
            return DockerDefaults(port=9292, command="bundle exec rackup --host 0.0.0.0 --port 9292")
        return DockerDefaults(
            port=3000, warnings=["Couldn't infer how to start the app (Procfile or config.ru) — set docker.command."]
        )

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        build, runtime = native_packages(project)
        lockfile = project.exists("Gemfile.lock")
        env = {"BUNDLE_DEPLOYMENT": "1"} if lockfile else {}
        return {
            "workdir": "/app",
            "env": {**env, "BUNDLE_PATH": "/usr/local/bundle", "BUNDLE_WITHOUT": "development:test"},
            "lockfile": lockfile,
            "gemspec": bool(re.search(r"^\s*gemspec", project.read_text("Gemfile"), re.M)),
            "ruby_version_file": project.exists(".ruby-version"),
            "build_packages": build,
            "runtime_packages": runtime,
            "bundle_install": ["bundle install", 'rm -rf ~/.bundle/ "${BUNDLE_PATH}"/ruby/*/cache'],
            "after_copy": [],
        }

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        return [".bundle", "vendor/bundle", "log", "tmp", "coverage", ".env", ".env.*", "!.env.example"]


def native_packages(project: Project) -> Tuple[List[str], List[str]]:
    build, runtime = [], []
    for gem, (dev, lib) in _NATIVE_GEMS.items():
        if has_gem(project, gem):
            build += [dev] if dev else []
            runtime += [lib] if lib else []
    return build, runtime
