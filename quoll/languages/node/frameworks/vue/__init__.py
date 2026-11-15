"""Vue: single-page apps with Vite, type-checked with vue-tsc."""
from __future__ import annotations

from quoll.languages.base import Framework
from quoll.languages.node.frameworks.vue.ci import VueCI
from quoll.languages.node.frameworks.vue.detect import detect
from quoll.languages.node.frameworks.vue.docker import VueImage
from quoll.languages.node.frameworks.vue.starter import starter

framework = Framework(
    name="vue",
    language="node",
    detect=detect,
    ci=VueCI(),
    lint_tools=("vue-tsc",),
    docker=VueImage(),
    starters=(starter,),
)
