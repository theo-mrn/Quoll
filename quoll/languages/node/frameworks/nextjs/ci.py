from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

from quoll.ci.steps import Cache, Item
from quoll.languages.base import FrameworkCI
from quoll.languages.node.ci import LOCKFILES

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

_SOURCES = ("**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx", "!node_modules/**")


class NextjsCI(FrameworkCI):
    def env(self, cfg: CIConfig) -> Dict[str, str]:
        return {"NEXT_TELEMETRY_DISABLED": "1"}

    def before_build(self, cfg: CIConfig) -> List[Item]:
        # https://nextjs.org/docs/app/guides/ci-build-caching
        return [
            Cache(
                "nextjs",
                (".next/cache",),
                key_files=(LOCKFILES[cfg.package_manager],),
                revision_files=_SOURCES,
                name="Cache Next.js build",
            )
        ]
