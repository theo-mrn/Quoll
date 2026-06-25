from __future__ import annotations

from typing import TYPE_CHECKING, List

from quoll.ci.steps import Item, step
from quoll.languages.base import FrameworkCI

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

# tool: (step name, command)
_LINT = {
    "symfony-container": ("Lint service container", "php bin/console lint:container"),
    "symfony-yaml": ("Lint YAML config", "php bin/console lint:yaml config --parse-tags"),
    "symfony-twig": ("Lint Twig templates", "php bin/console lint:twig templates"),
}


class SymfonyCI(FrameworkCI):
    def lint(self, cfg: CIConfig, tool: str) -> List[Item]:
        name, cmd = _LINT[tool]
        return [step(name, run=cmd)]
