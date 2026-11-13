from __future__ import annotations

import re

from quoll.languages.base import Detection
from quoll.project import Project
from quoll.services import detect_services

RUBY_DEFAULT = "3.4"
RUBY_SUPPORTED = ("3.2", "3.3", "3.4")

# Gems revealing a backing service.
_SERVICE_GEMS = {
    "postgres": ("pg",),
    "mysql": ("mysql2", "trilogy"),
    "redis": ("redis", "redis-client"),
    "mongodb": ("mongoid", "mongo"),
}
# (file, pattern capturing major.minor), by priority.
_VERSION_SOURCES = (
    (".ruby-version", r"(\d+\.\d+)"),
    (".tool-versions", r"^ruby\s+(\d+\.\d+)"),
    ("Gemfile", r"^\s*ruby\s+[\"'](\d+\.\d+)"),
)


def detect(project: Project) -> Detection:
    det = Detection(package_manager="bundler", install="bundle install")
    det.lockfile = "Gemfile.lock" if project.exists("Gemfile.lock") else ""
    if not det.lockfile:
        det.warnings.append("No Gemfile.lock found — commit it for reproducible builds.")

    # setup-ruby reads .ruby-version and .tool-versions itself.
    for name, pattern in _VERSION_SOURCES:
        m = re.search(pattern, project.read_text(name), re.M)
        if m:
            det.version_file = name if name != "Gemfile" else ""
            det.version = m.group(1)
            break
    else:
        det.version = RUBY_DEFAULT
    det.matrix_versions = [v for v in RUBY_SUPPORTED if _key(v) >= _key(det.version)] or [det.version]

    det.lint_tools = [tool for tool in ("rubocop", "standard") if has_gem(project, tool)]
    if has_gem(project, "rspec-core") or has_gem(project, "rspec-rails") or project.exists(".rspec"):
        det.test_runner = "rspec"
    elif project.is_dir("test"):
        det.test_runner = "minitest"
    else:
        det.warnings.append("No tests found (spec/ with RSpec or test/) — the test job is disabled.")
    # The threshold is read from SimpleCov's results; without SimpleCov there is nothing to check.
    det.coverage = has_gem(project, "simplecov")

    det.services = detect_services(
        [gem for gems in _SERVICE_GEMS.values() for gem in gems if has_gem(project, gem)], _SERVICE_GEMS
    )
    if project.glob_any("*.gemspec"):
        det.build_command = "gem build ./*.gemspec"
    return det


def has_gem(project: Project, name: str) -> bool:
    """True when `name` is declared in the Gemfile or resolved in Gemfile.lock."""
    gem = re.escape(name)
    return bool(
        re.search(rf"^\s*gem\s+[\"']{gem}[\"']", project.read_text("Gemfile"), re.M)
        or re.search(rf"^\s{{4}}{gem} \(", project.read_text("Gemfile.lock"), re.M)
    )


def _key(version: str) -> tuple:
    return tuple(int(p) for p in version.split(".")[:2])
