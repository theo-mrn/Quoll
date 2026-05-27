from __future__ import annotations

import re

from quoll.languages.base import Detection
from quoll.project import Project
from quoll.services import detect_services

# Crates (or sqlx/diesel/sea-orm features) revealing a backing service.
_SERVICE_CRATES = {
    "postgres": ("tokio-postgres", "postgres", "deadpool-postgres"),
    "mysql": ("mysql", "mysql_async"),
    "redis": ("redis", "deadpool-redis", "fred"),
    "mongodb": ("mongodb",),
}


def detect(project: Project) -> Detection:
    det = Detection(package_manager="cargo", lint_tools=["rustfmt", "clippy"])
    locked = project.exists("Cargo.lock")
    det.lockfile = "Cargo.lock" if locked else ""
    det.install = "cargo fetch --locked" if locked else "cargo fetch"
    if not locked:
        det.warnings.append("No Cargo.lock found — commit it for reproducible builds (recommended for binaries).")

    # rust-toolchain(.toml) is read by the setup action itself.
    toolchain_file = next((f for f in ("rust-toolchain.toml", "rust-toolchain") if project.exists(f)), "")
    if toolchain_file:
        det.version_file = toolchain_file
        m = re.search(r'channel\s*=\s*"([^"]+)"', project.read_text(toolchain_file))
        det.version = m.group(1) if m else project.read_text(toolchain_file).strip() or "stable"
    else:
        det.version = "stable"
    cargo = project.read_toml("Cargo.toml")
    msrv = cargo.get("package", {}).get("rust-version", "")
    det.matrix_versions = [msrv, "stable"] if isinstance(msrv, str) and msrv else ["stable", "beta"]

    crates = [*cargo.get("dependencies", {}), *cargo.get("dev-dependencies", {})]
    cargo_text = project.read_text("Cargo.toml")
    if any(orm in crates for orm in ("sqlx", "diesel", "sea-orm")):
        crates += [db for db in ("postgres", "mysql") if re.search(rf"\b{db}\b", cargo_text)]
    det.services = detect_services(crates, _SERVICE_CRATES)

    det.test_runner = "nextest" if project.exists(".config/nextest.toml") else "cargo"
    det.build_command = "cargo build --release --locked" if locked else "cargo build --release"
    return det
