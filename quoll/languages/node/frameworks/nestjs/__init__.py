"""NestJS: CI is plain Node; the framework matters for packaging (nest build → dist/main.js)."""

from quoll.languages.base import Framework
from quoll.languages.node.frameworks.nestjs.detect import detect
from quoll.languages.node.frameworks.nestjs.docker import NestjsImage

framework = Framework(name="nestjs", language="node", detect=detect, docker=NestjsImage())
