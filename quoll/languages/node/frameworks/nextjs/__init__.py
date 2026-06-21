"""Next.js: persist the build cache between runs and opt out of telemetry."""

from quoll.languages.base import Framework
from quoll.languages.node.frameworks.nextjs.ci import NextjsCI
from quoll.languages.node.frameworks.nextjs.detect import detect
from quoll.languages.node.frameworks.nextjs.docker import NextjsImage

framework = Framework(name="nextjs", language="node", detect=detect, ci=NextjsCI(), docker=NextjsImage())
