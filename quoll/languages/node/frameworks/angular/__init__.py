"""Angular: tests run once through the CLI (headless Chrome for Karma); opt out of CLI analytics."""

from quoll.languages.base import Framework
from quoll.languages.node.frameworks.angular.ci import AngularCI
from quoll.languages.node.frameworks.angular.detect import detect
from quoll.languages.node.frameworks.angular.docker import AngularImage
from quoll.languages.node.frameworks.angular.starter import starter

framework = Framework(
    name="angular",
    language="node",
    detect=detect,
    ci=AngularCI(),
    # "angular" is the CLI's Vitest-based runner (Angular 21+), "angular-karma" the older Karma one.
    test_runners=("angular", "angular-karma"),
    docker=AngularImage(),
    starters=(starter,),
)
