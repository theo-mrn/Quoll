"""CI steps for Vue: type-check with vue-tsc."""
from __future__ import annotations

from typing import TYPE_CHECKING, List

from quoll.ci.steps import Item, step
from quoll.languages.base import FrameworkCI

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig


class VueCI(FrameworkCI):
    def lint(self, cfg: CIConfig, tool: str) -> List[Item]:
        if tool == "vue-tsc":
            return [step("Type check", run=cfg.language.ci.exec(cfg, "vue-tsc --noEmit"))]
        raise NotImplementedError(f"VueCI declares lint tool '{tool}' but does not implement it")
