from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from quoll.languages.php.docker import PhpImage

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig


class LaravelImage(PhpImage):
    def writable_paths(self, cfg: DockerConfig) -> Optional[List[str]]:
        # The framework writes in storage/ and bootstrap/cache/, whose tree must stay: a writable root filesystem.
        return None

    def env(self, cfg: DockerConfig) -> Dict[str, str]:
        return {"APP_ENV": "production"}

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        return [
            *super().dockerignore(cfg),
            "storage/logs/*",
            "storage/framework/cache/data/*",
            "storage/framework/sessions/*",
            "storage/framework/views/*",
            "bootstrap/cache/*.php",
            "public/hot",
            "public/storage",
        ]
