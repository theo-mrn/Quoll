from __future__ import annotations

from typing import TYPE_CHECKING, List

from quoll.ci.steps import Item, step
from quoll.languages.base import FrameworkCI

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig


class SvelteKitCI(FrameworkCI):
    def lint(self, cfg: CIConfig, tool: str) -> List[Item]:
        exec_ = cfg.language.ci.exec
        return [step("svelte-check", run=f"{exec_(cfg, 'svelte-kit sync')}\n{exec_(cfg, 'svelte-check')}")]
