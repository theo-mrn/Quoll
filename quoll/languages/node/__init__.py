"""Node.js (and front-end) projects: npm, pnpm, yarn and bun."""

from quoll.languages.base import Language
from quoll.languages.node.ci import NodeCI
from quoll.languages.node.detect import detect
from quoll.languages.node.docker import NodeImage
from quoll.languages.node.frameworks import angular, astro, nestjs, nextjs, nuxt, sveltekit
from quoll.languages.node.starter import starter as express

language = Language(
    name="node",
    markers=("package.json",),
    package_managers=("npm", "pnpm", "yarn", "yarn-classic", "bun"),
    lint_tools=("eslint", "prettier", "biome", "tsc"),
    test_runners=("jest", "vitest", "bun"),
    detect=detect,
    ci=NodeCI(),
    frameworks=(
        nextjs.framework,
        nuxt.framework,
        sveltekit.framework,
        astro.framework,
        angular.framework,
        nestjs.framework,
    ),
    scripts=True,
    docker=NodeImage(),
    starters=(express,),
)
