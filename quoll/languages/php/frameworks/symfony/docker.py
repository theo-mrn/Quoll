from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from quoll.languages.php.docker import PhpImage

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig


class SymfonyImage(PhpImage):
    def writable_paths(self, cfg: DockerConfig) -> Optional[List[str]]:
        # The framework writes in var/, whose tree must stay: a writable root filesystem.
        return None

    def env(self, cfg: DockerConfig) -> Dict[str, str]:
        return {"APP_ENV": "prod", "APP_DEBUG": "0"}

    def post_build(self, cfg: DockerConfig) -> List[str]:
        # Flex's auto-scripts: cache:clear (warms the prod cache) and assets:install.
        return ["composer run-script --no-dev post-install-cmd"]

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        # Symfony commits .env (defaults); secrets live in .env.local.
        return ["vendor", "node_modules", "var", ".phpunit.cache", ".env.local", ".env.local.php", ".env.*.local"]
