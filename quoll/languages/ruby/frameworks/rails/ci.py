from __future__ import annotations

from typing import TYPE_CHECKING, List

from quoll.ci.steps import Item, step
from quoll.languages.base import FrameworkCI
from quoll.languages.ruby.ci import test_steps

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

_TEST = {
    "rails": "bin/rails db:test:prepare test",
    "rails-rspec": "bin/rails db:test:prepare\nbundle exec rspec",
}


class RailsCI(FrameworkCI):
    def env(self, cfg: CIConfig) -> dict:
        return {"RAILS_ENV": "test"}

    def lint(self, cfg: CIConfig, tool: str) -> List[Item]:
        return [step("Brakeman", run="bundle exec brakeman --no-pager")]

    def test(self, cfg: CIConfig) -> List[Item]:
        return test_steps(cfg, _TEST[cfg.test.runner])
