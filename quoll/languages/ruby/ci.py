from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from quoll.ci.steps import ROOT, Cache, Item, Step, on_github, step
from quoll.languages.base import THRESHOLD_REGEX, CISteps, TestReports
from quoll.platforms.github.actions import ACTIONS

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

_LINT = {
    "rubocop": ("RuboCop", "bundle exec rubocop"),
    "standard": ("Standard", "bundle exec standardrb"),
}

_TEST = {"rspec": "bundle exec rspec", "minitest": "bundle exec rake test"}
_RSPEC_RUNNERS = ("rspec", "rails-rspec")
# RSpec's JUnit formatter, installed outside the bundle and loaded from its directory.
_RSPEC_JUNIT = "/tmp/quoll-rspec-junit"
_RSPEC_JUNIT_INSTALL = (
    f"gem install --no-document --install-dir {_RSPEC_JUNIT} --ignore-dependencies rspec_junit_formatter -v '~> 0.6'"
)
_RSPEC_JUNIT_FLAGS = (
    f' -I "$(echo {_RSPEC_JUNIT}/gems/rspec_junit_formatter-*/lib)" -r rspec_junit_formatter'
    " --format progress --format RspecJunitFormatter --out junit.xml"
)

# SimpleCov writes the last line coverage to coverage/.last_run.json ("line" since 0.18, "covered_percent" before).
_SIMPLECOV_CHECK = """ruby -rjson -e '
result = JSON.parse(File.read("coverage/.last_run.json"))["result"]
pct = result["line"] || result["covered_percent"]
summary = ENV["GITHUB_STEP_SUMMARY"]
File.write(summary, format("### Coverage: %.1f%%\\n", pct), mode: "a") if summary
if pct < {threshold}
  puts format("::error::Coverage %.1f%% is below the {threshold}%% threshold", pct)
  exit 1
end
puts format("Coverage %.1f%% (threshold {threshold}%%)", pct)'"""


class RubyCI(CISteps):
    version_key = "ruby-version"
    codeql_language = "ruby"

    def setup(self, cfg: CIConfig, version: Optional[str]) -> List[Item]:
        # Without a version, setup-ruby reads .ruby-version / .tool-versions.
        with_: Dict[str, Any] = {"ruby-version": version} if version else {}
        # bundler-cache runs `bundle install` and caches the gems.
        with_["bundler-cache"] = cfg.cache
        if cfg.directory != ".":
            with_["working-directory"] = cfg.directory
        return [step("Set up Ruby", uses=ACTIONS["setup-ruby"], with_=with_)]

    def image(self, cfg: CIConfig, version: str) -> str:
        return f"ruby:{version}"

    def image_setup(self, cfg: CIConfig) -> List[Step]:
        # On GitHub, setup-ruby installs the gems when caching (see install).
        return [step("Install dependencies", run=cfg.install)] if cfg.cache else []

    def cache(self, cfg: CIConfig) -> Optional[Cache]:
        if not cfg.cache:
            return None
        env = {"BUNDLE_PATH": f"{ROOT}/vendor/bundle"}
        return Cache("gems", ("vendor/bundle",), key_files=("Gemfile.lock",), env=env)

    def install(self, cfg: CIConfig, packages: Sequence[str] = ()) -> List[Item]:
        return [] if cfg.cache else [step("Install dependencies", run=cfg.install)]

    def lint(self, cfg: CIConfig, tools: List[str]) -> List[Item]:
        github = on_github(cfg, " --format github")
        return [*self.install(cfg), *(step(_LINT[t][0], run=_LINT[t][1] + github) for t in tools)]

    def test(self, cfg: CIConfig) -> List[Item]:
        return test_steps(cfg, _TEST[cfg.test.runner])

    def coverage_file(self, cfg: CIConfig) -> str:
        return "coverage/.resultset.json"

    def reports(self, cfg: CIConfig) -> TestReports:
        return TestReports(
            junit="junit.xml" if cfg.test.runner in _RSPEC_RUNNERS else "",
            coverage_regex=THRESHOLD_REGEX if cfg.test.coverage else "",
        )

    def audit(self, cfg: CIConfig) -> List[Item]:
        return [
            step("Install bundler-audit", run="gem install bundler-audit --no-document"),
            step("Dependency vulnerability scan", run="bundle-audit check --update"),
        ]

    def build(self, cfg: CIConfig) -> List[Item]:
        return [*self.install(cfg), step("Build", run=cfg.build.command)]

    def dependabot_ecosystem(self, cfg: CIConfig) -> str:
        return "bundler"


def test_steps(cfg: CIConfig, command: str) -> List[Step]:
    """Install, run `command`, then enforce the SimpleCov threshold when coverage is enabled."""
    t = cfg.test
    steps = list(RubyCI().install(cfg))
    if t.reports and t.runner in _RSPEC_RUNNERS:
        steps.append(step("JUnit formatter for RSpec", run=_RSPEC_JUNIT_INSTALL))
        command += _RSPEC_JUNIT_FLAGS
    steps.append(step("Tests", run=command, secrets=t.env_secrets))
    if t.coverage:
        steps.append(step("Coverage threshold", run=_SIMPLECOV_CHECK.format(threshold=t.coverage_threshold)))
    return steps
