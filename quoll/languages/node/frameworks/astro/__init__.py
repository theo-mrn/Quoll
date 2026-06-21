"""Astro: `astro check` type-checks .astro files too; opt out of telemetry."""

from quoll.languages.base import Framework
from quoll.languages.node.frameworks.astro.ci import AstroCI
from quoll.languages.node.frameworks.astro.detect import detect
from quoll.languages.node.frameworks.astro.docker import AstroImage

framework = Framework(
    name="astro", language="node", detect=detect, ci=AstroCI(), lint_tools=("astro-check",), docker=AstroImage()
)
