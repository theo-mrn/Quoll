from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from quoll.ci.steps import ROOT, SUMMARY_FILE, Cache, Item, Step, step
from quoll.languages.base import THRESHOLD_REGEX, CISteps, TestReports
from quoll.platforms.github.actions import ACTIONS

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

# Only tracked files: container jobs keep the module cache inside the project.
_GOFMT = """unformatted=$(git ls-files -z '*.go' | xargs -0 -r gofmt -l)
if [ -n "$unformatted" ]; then
  echo "::error::These files are not gofmt-formatted:"
  echo "$unformatted"
  exit 1
fi"""

_COVERAGE_CHECK = """total=$(go tool cover -func=coverage.out | awk '/^total:/ {{ sub("%", "", $3); print $3 }}')
echo "### Coverage: ${{total}}%" >> {summary}
awk -v total="$total" -v min={threshold} 'BEGIN {{
  if (total + 0 < min) {{ printf "::error::Coverage %.1f%% is below the %d%% threshold\\n", total, min; exit 1 }}
  printf "Coverage %.1f%% (threshold %d%%)\\n", total, min
}}'"""

_GOTESTSUM = "GOTOOLCHAIN=auto go run gotest.tools/gotestsum@latest"
_COBERTURA = "GOTOOLCHAIN=auto go run github.com/boumenot/gocover-cobertura@latest < coverage.out > coverage.xml"
_GOLANGCI_LINT = """curl -sSfL https://golangci-lint.run/install.sh | sh -s -- -b "$(go env GOPATH)/bin"
"$(go env GOPATH)/bin/golangci-lint" run"""


def _working_directory(cfg: CIConfig) -> Dict[str, str]:
    return {"working-directory": cfg.directory} if cfg.directory != "." else {}


class GoCI(CISteps):
    version_key = "go-version"
    codeql_language = "go"
    codeql_build_mode = "autobuild"

    def setup(self, cfg: CIConfig, version: Optional[str]) -> List[Item]:
        with_: Dict[str, Any] = {"go-version": version} if version else {"go-version-file": cfg.path(cfg.version_file)}
        if not cfg.cache:
            with_["cache"] = False
        elif cfg.directory != ".":
            with_["cache-dependency-path"] = cfg.path("go.sum")
        return [step("Set up Go", uses=ACTIONS["setup-go"], with_=with_)]

    def image(self, cfg: CIConfig, version: str) -> str:
        if version == "oldstable":
            raise ValueError("Go 'oldstable' has no image: list explicit versions (e.g. 1.25) in [ci] versions")
        # The "1" tag follows the latest release, like setup-go's "stable".
        return f"golang:{'1' if version == 'stable' else version}"

    def cache(self, cfg: CIConfig) -> Optional[Cache]:
        if not cfg.cache:
            return None
        env = {"GOMODCACHE": f"{ROOT}/.go/mod", "GOCACHE": f"{ROOT}/.go/build"}
        return Cache("go", (".go/mod", ".go/build"), key_files=("go.sum",), env=env)

    def install(self, cfg: CIConfig, packages: Sequence[str] = ()) -> List[Step]:
        return [step("Download modules", run=cfg.install)]

    def lint(self, cfg: CIConfig, tools: List[str]) -> List[Item]:
        steps = self.install(cfg)
        for tool in tools:
            if tool == "gofmt":
                steps.append(step("gofmt", run=_GOFMT))
            elif tool == "vet":
                steps.append(step("go vet", run="go vet ./..."))
            elif tool == "golangci-lint":
                steps.append(
                    step(
                        "golangci-lint",
                        run=_GOLANGCI_LINT,
                        uses=ACTIONS["golangci-lint"],
                        with_={"version": "latest", **_working_directory(cfg)},
                    )
                )
        return steps

    def test(self, cfg: CIConfig) -> List[Item]:
        t = cfg.test
        # gotestsum runs `go test` and writes JUnit results.
        go_test = f"{_GOTESTSUM} --junitfile junit.xml --" if t.reports else "go test"
        if not t.coverage:
            return [*self.install(cfg), step("Tests", run=f"{go_test} -race ./...", secrets=t.env_secrets)]
        return [
            *self.install(cfg),
            step(
                "Tests with coverage",
                run=f"{go_test} -race -covermode=atomic -coverprofile=coverage.out ./...",
                secrets=t.env_secrets,
            ),
            *([step("Coverage report (Cobertura)", run=_COBERTURA)] if t.reports else []),
            step(
                "Coverage threshold",
                run=_COVERAGE_CHECK.format(threshold=t.coverage_threshold, summary=SUMMARY_FILE),
            ),
        ]

    def coverage_file(self, cfg: CIConfig) -> str:
        return "coverage.out"

    def reports(self, cfg: CIConfig) -> TestReports:
        coverage = cfg.test.coverage
        return TestReports(
            junit="junit.xml",
            cobertura="coverage.xml" if coverage else "",
            coverage_regex=THRESHOLD_REGEX if coverage else "",
        )

    def audit(self, cfg: CIConfig) -> List[Item]:
        # govulncheck@latest may need a newer Go than the project's: let go fetch it to build the tool, while the
        # scan itself uses the project's toolchain (setup-go and the golang images pin GOTOOLCHAIN=local).
        return [
            *self.install(cfg),
            step("govulncheck", run="GOTOOLCHAIN=auto go run golang.org/x/vuln/cmd/govulncheck@latest ./..."),
        ]

    def build(self, cfg: CIConfig) -> List[Item]:
        return [*self.install(cfg), step("Build", run=cfg.build.command)]

    def dependabot_ecosystem(self, cfg: CIConfig) -> str:
        return "gomod"
