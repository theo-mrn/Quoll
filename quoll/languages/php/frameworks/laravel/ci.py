from __future__ import annotations

from typing import TYPE_CHECKING, List

from quoll.ci.steps import Item, step
from quoll.languages.base import FrameworkCI
from quoll.languages.php.ci import report_flags

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig


class LaravelCI(FrameworkCI):
    def test(self, cfg: CIConfig) -> List[Item]:
        t = cfg.test
        cmd = "php artisan test"
        if t.coverage:
            cmd += f" --coverage --min={t.coverage_threshold} --coverage-clover coverage.xml"
        cmd += report_flags(cfg)
        return [
            *cfg.language.ci.install(cfg),
            step("Prepare environment", run="[ -f .env ] || cp .env.example .env\nphp artisan key:generate"),
            step("Tests" + (" with coverage" if t.coverage else ""), run=cmd, secrets=t.env_secrets),
        ]
