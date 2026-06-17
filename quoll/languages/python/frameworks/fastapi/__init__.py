"""FastAPI: CI is plain Python; the framework matters for how the app is served."""

from quoll.languages.base import Framework
from quoll.languages.python.frameworks.fastapi.detect import detect
from quoll.languages.python.frameworks.fastapi.docker import FastapiImage

framework = Framework(name="fastapi", language="python", detect=detect, docker=FastapiImage())
