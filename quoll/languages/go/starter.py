"""A new Go API: the standard library's net/http (Go 1.22+ routing), graceful shutdown, tested with httptest.

Copied from templates/http/: no dependency to resolve. The Go version goes to go.mod, which the CI and the Dockerfile
follow (`--go 1.26` for another one).
"""
from __future__ import annotations

from pathlib import Path

from quoll.languages.base import Starter
from quoll.starters import from_template

# Go version when none is asked for: the latest release.
GO_DEFAULT = "1.27"

starter = Starter(
    name="go",
    label="Go (net/http)",
    role="back",
    create=from_template(
        Path(__file__).parent / "templates" / "http",
        runtime_default=GO_DEFAULT,
        # Stored under another name: it would make the template a module of quoll's repository.
        renamed={"go.mod.tmpl": "go.mod"},
    ),
    dev="go run .",
    runtime="go",
    runtime_default=GO_DEFAULT,
)
