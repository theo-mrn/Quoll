"""Nuxt: type-check through nuxi (plain tsc misses the generated .nuxt types) and opt out of telemetry."""

from quoll.languages.base import Framework
from quoll.languages.node.frameworks.nuxt.ci import NuxtCI
from quoll.languages.node.frameworks.nuxt.detect import detect
from quoll.languages.node.frameworks.nuxt.docker import NuxtImage

framework = Framework(
    name="nuxt", language="node", detect=detect, ci=NuxtCI(), lint_tools=("nuxt-typecheck",), docker=NuxtImage()
)
