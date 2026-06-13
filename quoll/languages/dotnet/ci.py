from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from quoll.ci.steps import ROOT, Cache, Item, step
from quoll.languages.base import CISteps, TestReports
from quoll.platforms.github.actions import ACTIONS

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

# `dotnet list package --vulnerable` always exits 0: fail on high or critical advisories ourselves.
_AUDIT = """dotnet list package --vulnerable --include-transitive 2>&1 | tee vulnerable.txt
if grep -qE "\\b(High|Critical)\\b" vulnerable.txt; then
  echo "::error::Packages with high or critical vulnerabilities found"
  exit 1
fi"""

# dotnet test writes TRX results; trx2junit, installed outside the project, converts them for the platforms. Tests
# that fail still get their report: the status is kept until the conversion is done.
_JUNIT = """status=0
{test} || status=$?
dotnet tool install --tool-path /tmp/quoll-trx2junit trx2junit >/dev/null
/tmp/quoll-trx2junit/trx2junit TestResults/*.trx
exit $status"""


class DotnetCI(CISteps):
    version_key = "dotnet-version"
    codeql_language = "csharp"

    def setup(self, cfg: CIConfig, version: Optional[str]) -> List[Item]:
        with_: Dict[str, Any] = (
            {"dotnet-version": version} if version else {"global-json-file": cfg.path(cfg.version_file)}
        )
        if cfg.cache:
            with_["cache"] = True
            with_["cache-dependency-path"] = cfg.path("**/packages.lock.json")
        return [step("Set up .NET", uses=ACTIONS["setup-dotnet"], with_=with_)]

    def image(self, cfg: CIConfig, version: str) -> str:
        return f"mcr.microsoft.com/dotnet/sdk:{version}"

    def cache(self, cfg: CIConfig) -> Optional[Cache]:
        if not cfg.cache:
            return None
        return Cache("nuget", (".nuget/packages",), env={"NUGET_PACKAGES": f"{ROOT}/.nuget/packages"})

    def install(self, cfg: CIConfig, packages: Sequence[str] = ()) -> List[Item]:
        return [step("Restore dependencies", run=cfg.install)]

    def lint(self, cfg: CIConfig, tools: List[str]) -> List[Item]:
        steps = self.install(cfg)
        if "dotnet-format" in tools:
            steps.append(step("dotnet format", run="dotnet format --verify-no-changes --no-restore"))
        return steps

    def test(self, cfg: CIConfig) -> List[Item]:
        t = cfg.test
        cmd = "dotnet test --no-restore"
        if t.coverage:
            cmd += (
                " -p:CollectCoverage=true -p:CoverletOutputFormat=cobertura"
                f" -p:Threshold={t.coverage_threshold} -p:ThresholdType=line"
            )
        if t.reports:
            cmd = _JUNIT.format(test=cmd + " --logger trx --results-directory TestResults")
        name = "Tests" + (" with coverage" if t.coverage else "")
        return [*self.install(cfg), step(name, run=cmd, secrets=t.env_secrets)]

    def coverage_file(self, cfg: CIConfig) -> str:
        return "**/coverage.cobertura.xml"

    def reports(self, cfg: CIConfig) -> TestReports:
        if not cfg.test.coverage:
            return TestReports(junit="TestResults/*.xml")
        # coverlet's summary table: | Total | 85.5% | ...
        regex = r"/\|\s*Total\s*\|\s*(\d+(?:\.\d+)?)%/"
        return TestReports(junit="TestResults/*.xml", cobertura="**/coverage.cobertura.xml", coverage_regex=regex)

    def audit(self, cfg: CIConfig) -> List[Item]:
        return [*self.install(cfg), step("Dependency vulnerability scan", run=_AUDIT)]

    def build(self, cfg: CIConfig) -> List[Item]:
        return [*self.install(cfg), step("Build", run=cfg.build.command)]

    def dependabot_ecosystem(self, cfg: CIConfig) -> str:
        return "nuget"
