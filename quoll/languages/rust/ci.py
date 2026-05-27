from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from quoll.ci.steps import ROOT, Cache, Item, Step, step
from quoll.languages.base import CISteps, TestReports
from quoll.platforms.github.actions import ACTIONS

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

_LINT = {
    "rustfmt": ("rustfmt", "cargo fmt --all --check"),
    "clippy": ("Clippy", "cargo clippy --workspace --all-targets --all-features -- -D warnings"),
}

_BINSTALL = (
    "curl -sSfL https://github.com/cargo-bins/cargo-binstall/releases/latest/download/"
    'cargo-binstall-"$(uname -m)"-unknown-linux-musl.tgz | tar -xz -C /usr/local/bin'
)

# nextest writes JUnit results with a profile setting: added by a tool config, so the project's own config applies.
_NEXTEST_CONFIG = "/tmp/quoll-nextest.toml"
_NEXTEST_JUNIT = f"""printf '[profile.default.junit]\\npath = "junit.xml"\\n' > {_NEXTEST_CONFIG}"""


class RustCI(CISteps):
    version_key = "rust-version"
    codeql_language = "rust"
    # cargo-audit is a standalone binary; cargo is preinstalled on the runners.
    audit_needs_setup = False

    def setup(self, cfg: CIConfig, version: Optional[str]) -> List[Item]:
        components = _components(cfg)
        # Without a toolchain, the action reads rust-toolchain(.toml).
        with_: Dict[str, Any] = {"toolchain": version} if version else {}
        with_["components"] = ", ".join(components)
        if not cfg.cache:
            with_["cache"] = False
        if cfg.directory != ".":
            # Where rust-toolchain(.toml) and Cargo.lock are.
            with_["rust-src-dir"] = cfg.directory
            with_["cache-workspaces"] = cfg.directory
        return [step("Set up Rust", uses=ACTIONS["setup-rust"], with_=with_)]

    def image(self, cfg: CIConfig, version: str) -> str:
        if version.startswith("nightly"):
            return "rustlang/rust:nightly"
        # The "1" tag follows the latest stable release.
        return f"rust:{'1' if version in ('stable', 'beta') else version}"

    def image_setup(self, cfg: CIConfig) -> List[Step]:
        return [step("Add components", run=f"rustup component add {' '.join(_components(cfg))}")]

    def cache(self, cfg: CIConfig) -> Optional[Cache]:
        if not cfg.cache:
            return None
        paths = (".cargo/registry", ".cargo/git", "target")
        return Cache("cargo", paths, key_files=("Cargo.lock",), env={"CARGO_HOME": f"{ROOT}/.cargo"})

    def install(self, cfg: CIConfig, packages: Sequence[str] = ()) -> List[Step]:
        steps = [step("Fetch dependencies", run=cfg.install)]
        if packages:
            steps.append(install_tools(packages))
        return steps

    def lint(self, cfg: CIConfig, tools: List[str]) -> List[Item]:
        return [*self.install(cfg), *(step(_LINT[t][0], run=_LINT[t][1]) for t in tools)]

    def test(self, cfg: CIConfig) -> List[Item]:
        t = cfg.test
        nextest = t.runner == "nextest"
        tools = (["cargo-llvm-cov"] if t.coverage else []) + (["cargo-nextest"] if nextest else [])
        if nextest:
            cmd = "cargo llvm-cov nextest" if t.coverage else "cargo nextest run"
        else:
            cmd = "cargo llvm-cov" if t.coverage else "cargo test"
        cmd += " --workspace --all-features"
        setup: List[Item] = []
        if nextest and t.reports:
            setup.append(step("JUnit output for nextest", run=_NEXTEST_JUNIT))
            cmd += f" --tool-config-file quoll:{_NEXTEST_CONFIG}"
        if t.coverage:
            cmd += f" --lcov --output-path lcov.info --fail-under-lines {t.coverage_threshold}"
        name = "Tests" + (" with coverage" if t.coverage else "")
        return [*self.install(cfg, tools), *setup, step(name, run=cmd, secrets=t.env_secrets)]

    def coverage_file(self, cfg: CIConfig) -> str:
        return "lcov.info"

    def reports(self, cfg: CIConfig) -> TestReports:
        # The lines column of cargo-llvm-cov's TOTAL row.
        regex = r"/^TOTAL(?:\s+\S+){8}\s+(\d+(?:\.\d+)?)%/"
        # `cargo test` has no stable JUnit output: nextest only.
        junit = "target/nextest/default/junit.xml" if cfg.test.runner == "nextest" else ""
        return TestReports(junit=junit, coverage_regex=regex if cfg.test.coverage else "")

    def audit(self, cfg: CIConfig) -> List[Item]:
        return [
            install_tools(["cargo-audit"], "Install cargo-audit"),
            step("Dependency vulnerability scan", run="cargo audit"),
        ]

    def build(self, cfg: CIConfig) -> List[Item]:
        return [*self.install(cfg), step("Build", run=cfg.build.command)]

    def dependabot_ecosystem(self, cfg: CIConfig) -> str:
        return "cargo"


def install_tools(tools: Sequence[str], name: str = "Install CI tools") -> Step:
    """Prebuilt binaries of cargo tools: taiki-e/install-action on GitHub, cargo-binstall elsewhere."""
    return step(
        name,
        run=f"{_BINSTALL}\ncargo binstall --no-confirm --install-path /usr/local/bin {' '.join(tools)}",
        uses=ACTIONS["install-tool"],
        with_={"tool": ",".join(tools)},
    )


def _components(cfg: CIConfig) -> List[str]:
    components = ["rustfmt", "clippy"]
    if cfg.test.enabled and cfg.test.coverage:
        components.append("llvm-tools-preview")
    return components
