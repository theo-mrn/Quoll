from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from quoll.languages.base import Detection, DockerDefaults, DockerImage
from quoll.languages.php.detect import composer_packages
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig

# composer.json name -> install-php-extensions name, when they differ.
_EXTENSION_NAMES = {"zend-opcache": "opcache"}


class PhpImage(DockerImage):
    """FrankenPHP: PHP and its web server (Caddy) in one process, so there's no command to run."""

    requires_command = False

    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        warnings = [] if project.is_dir("public") else ["No public/ directory: the whole project is served."]
        return DockerDefaults(port=8080, warnings=warnings)

    def writable_paths(self, cfg: DockerConfig) -> Optional[List[str]]:
        # Caddy's certificates and configuration.
        return ["/tmp", "/data/caddy", "/config/caddy"]

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        extensions = sorted(
            _EXTENSION_NAMES.get(name[4:], name[4:]) for name in composer_packages(project) if name.startswith("ext-")
        )
        return {
            "extensions": extensions,
            "lockfile": project.exists("composer.lock"),
            "public": project.is_dir("public"),
            "env": self.env(cfg),
            "post_build": self.post_build(cfg),
        }

    def env(self, cfg: DockerConfig) -> Dict[str, str]:
        """Environment of the build and the runtime."""
        return {}

    def post_build(self, cfg: DockerConfig) -> List[str]:
        """Commands run once dependencies and code are in place."""
        return []

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        return [
            "vendor",
            "node_modules",
            "var",
            ".phpunit.cache",
            ".php-cs-fixer.cache",
            ".env",
            ".env.*",
            "!.env.example",
        ]
