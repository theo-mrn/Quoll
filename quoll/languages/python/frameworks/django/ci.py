from __future__ import annotations

from typing import TYPE_CHECKING, List

from quoll.ci.steps import Item, step
from quoll.languages.base import FrameworkCI
from quoll.languages.python.ci import coverage_summary

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

# tool: (step name, command)
_LINT = {
    "django-check": ("Django system checks", "python manage.py check"),
    "django-migrations": ("Missing migrations", "python manage.py makemigrations --check --dry-run"),
}


class DjangoCI(FrameworkCI):
    def lint(self, cfg: CIConfig, tool: str) -> List[Item]:
        name, cmd = _LINT[tool]
        return [step(name, run=cfg.language.ci.exec(cfg, cmd))]

    def test(self, cfg: CIConfig) -> List[Item]:
        t = cfg.test
        ci = cfg.language.ci
        if not t.coverage:
            return [*ci.install(cfg), step("Tests", run=ci.exec(cfg, "python manage.py test"), secrets=t.env_secrets)]
        return [
            *ci.install(cfg, ["coverage"]),
            step(
                "Tests with coverage",
                run=ci.exec(cfg, f"coverage run --source={cfg.source_dir} manage.py test"),
                secrets=t.env_secrets,
            ),
            step(
                "Coverage threshold",
                run="\n".join(
                    [ci.exec(cfg, "coverage xml"), ci.exec(cfg, f"coverage report --fail-under={t.coverage_threshold}")]
                ),
            ),
            coverage_summary(cfg),
        ]
