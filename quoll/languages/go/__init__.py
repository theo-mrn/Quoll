"""Go modules."""

from quoll.languages.base import Language
from quoll.languages.go.ci import GoCI
from quoll.languages.go.detect import detect
from quoll.languages.go.docker import GoImage
from quoll.languages.go.starter import starter

language = Language(
    name="go",
    markers=("go.mod",),
    package_managers=("go",),
    lint_tools=("gofmt", "vet", "golangci-lint"),
    test_runners=("go",),
    detect=detect,
    ci=GoCI(),
    docker=GoImage(),
    starters=(starter,),
)
