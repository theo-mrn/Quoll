"""SvelteKit: svelte-check after `svelte-kit sync` (plain tsc misses the generated .svelte-kit types)."""

from quoll.languages.base import Framework
from quoll.languages.node.frameworks.sveltekit.ci import SvelteKitCI
from quoll.languages.node.frameworks.sveltekit.detect import detect
from quoll.languages.node.frameworks.sveltekit.docker import SvelteKitImage

framework = Framework(
    name="sveltekit",
    language="node",
    detect=detect,
    ci=SvelteKitCI(),
    lint_tools=("svelte-check",),
    docker=SvelteKitImage(),
)
