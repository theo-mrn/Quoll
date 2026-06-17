"""Flask: CI is plain Python; the framework matters for how the app is served."""

from quoll.languages.base import Framework
from quoll.languages.python.frameworks.flask.detect import detect
from quoll.languages.python.frameworks.flask.docker import FlaskImage

framework = Framework(name="flask", language="python", detect=detect, docker=FlaskImage())
