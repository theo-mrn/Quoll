from __future__ import annotations

from quoll.ci.detect import detect
from tests.helpers import runs, steps, workflow
from tests.samples import RUST


def test_cargo(make_project) -> None:
    det = detect(make_project(RUST))
    assert det.stack == "rust"
    assert det.install == "cargo fetch --locked"
    assert det.version == "stable"
    assert det.matrix_versions == ["1.80", "stable"]  # MSRV from rust-version
    assert det.lint_tools == ["rustfmt", "clippy"]
    assert det.test_runner == "cargo"
    assert det.build_command == "cargo build --release --locked"


def test_toolchain_file_and_nextest(make_project) -> None:
    files = {**RUST, "rust-toolchain.toml": '[toolchain]\nchannel = "1.85"\n', ".config/nextest.toml": ""}
    det = detect(make_project(files))
    assert (det.version_file, det.version) == ("rust-toolchain.toml", "1.85")
    assert det.test_runner == "nextest"
    doc = workflow(make_project, files)
    # The setup action reads rust-toolchain.toml when no toolchain is given.
    assert "toolchain" not in steps(doc, "test")[1]["with"]
    assert "cargo llvm-cov nextest --workspace" in runs(doc, "test")


def test_without_lockfile(make_project) -> None:
    det = detect(make_project({"Cargo.toml": "[package]\nname = 'lib'\n"}))
    assert det.install == "cargo fetch"
    assert det.build_command == "cargo build --release"
    assert any("Cargo.lock" in w for w in det.warnings)
