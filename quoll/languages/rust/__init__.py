"""Rust: cargo projects and workspaces."""

from quoll.languages.base import Language
from quoll.languages.rust.ci import RustCI
from quoll.languages.rust.detect import detect
from quoll.languages.rust.docker import RustImage

language = Language(
    name="rust",
    markers=("Cargo.toml",),
    package_managers=("cargo",),
    lint_tools=("rustfmt", "clippy"),
    test_runners=("cargo", "nextest"),
    detect=detect,
    ci=RustCI(),
    docker=RustImage(),
)
