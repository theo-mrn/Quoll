from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

from quoll.ci.steps import Item, step
from quoll.languages.base import FrameworkCI

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig


class NuxtCI(FrameworkCI):
    def env(self, cfg: CIConfig) -> Dict[str, str]:
        return {"NUXT_TELEMETRY_DISABLED": "1"}

    def lint(self, cfg: CIConfig, tool: str) -> List[Item]:
        return [step("Type check", run=cfg.language.ci.exec(cfg, "nuxi typecheck"))]
