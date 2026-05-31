from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from quoll.ci.steps import ROOT, SUMMARY_FILE, Cache, Item, Step, step
from quoll.ci.tools import install_osv_scanner
from quoll.languages.base import THRESHOLD_REGEX, CISteps, TestReports
from quoll.platforms.github.actions import ACTIONS

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig
    from quoll.languages.base import Detection

_BUILD_TOOL = {
    "maven": "mvn -B -ntp",
    "maven-wrapper": "./mvnw -B -ntp",
    "gradle": "gradle",
    "gradle-wrapper": "./gradlew",
}

# tool: (step name, maven goal, gradle tasks). Static analysis runs on Maven without any pom.xml change (the full
# plugin coordinates); on Gradle, its plugin must be applied in the build.
_LINT = {
    "spotless": ("Spotless", "spotless:check", "spotlessCheck"),
    "checkstyle": ("Checkstyle", "checkstyle:check", "checkstyleMain checkstyleTest"),
    "ktlint": ("ktlint", "ktlint:check", "ktlintCheck"),
    "detekt": ("detekt", "detekt:check", "detekt"),
    # SpotBugs analyses the compiled classes.
    "spotbugs": ("SpotBugs", "compile com.github.spotbugs:spotbugs-maven-plugin:4.10.5.0:check", "spotbugsMain"),
    "pmd": ("PMD", "org.apache.maven.plugins:maven-pmd-plugin:3.28.0:check", "pmdMain"),
}

# JaCoCo, without any build file change: Maven runs the plugin's goals around `verify`, Gradle applies the plugin
# from an init script.
_JACOCO = "org.jacoco:jacoco-maven-plugin:0.8.16"
_JACOCO_INIT = "/tmp/quoll-jacoco.gradle"
_JACOCO_GRADLE = f"""cat > {_JACOCO_INIT} <<'EOF'
allprojects {{
    pluginManager.withPlugin("java") {{
        apply plugin: "jacoco"
        jacocoTestReport {{ reports {{ xml.required = true }} }}
        test {{ finalizedBy jacocoTestReport }}
    }}
}}
EOF"""
# The line coverage of every module: the last LINE counter of a JaCoCo report is its total.
_COVERAGE_CHECK = """reports=$(find . -path '*/target/site/jacoco/jacoco.xml' \\
  -o -path '*/build/reports/jacoco/test/jacocoTestReport.xml')
if [ -z "$reports" ]; then
  echo "::error::No JaCoCo report: does the build override the test JVM arguments (argLine)?"
  exit 1
fi
total=$(for f in $reports; do grep -o '<counter type="LINE" missed="[0-9]*" covered="[0-9]*"/>' "$f" | tail -1; done \\
  | sed 's/[^0-9 ]//g' | awk '{{ m += $1; c += $2 }} END {{ printf "%.1f", (m + c) ? c * 100 / (m + c) : 100 }}')
echo "### Coverage: ${{total}}%" >> {summary}
awk -v total="$total" -v min={threshold} 'BEGIN {{
  if (total + 0 < min) {{ printf "::error::Coverage %.1f%% is below the %d%% threshold\\n", total, min; exit 1 }}
  printf "Coverage %.1f%% (threshold %d%%)\\n", total, min
}}'"""

def build_tool(package_manager: str) -> str:
    return _BUILD_TOOL[package_manager]


class JavaCI(CISteps):
    version_key = "java-version"
    codeql_language = "java-kotlin"
    # osv-scanner reads the build files directly.
    audit_needs_setup = False

    def setup(self, cfg: CIConfig, version: Optional[str]) -> List[Item]:
        maven = _is_maven(cfg)
        with_: Dict[str, Any] = {"distribution": "temurin"}
        if version:
            with_["java-version"] = version
        else:
            with_["java-version-file"] = cfg.path(cfg.version_file)
        if maven and cfg.cache:
            with_["cache"] = "maven"
        steps = [step("Set up Java", uses=ACTIONS["setup-java"], with_=with_)]
        if not maven:
            # setup-gradle caches Gradle's dependencies and build outputs.
            with_gradle = None if cfg.cache else {"cache-disabled": True}
            steps.append(step("Set up Gradle", uses=ACTIONS["setup-gradle"], with_=with_gradle))
        return steps

    def image(self, cfg: CIConfig, version: str) -> str:
        if cfg.package_manager == "maven":
            return f"maven:3-eclipse-temurin-{version}"
        if cfg.package_manager == "gradle":
            return f"gradle:jdk{version}"
        return f"eclipse-temurin:{version}-jdk"

    def cache(self, cfg: CIConfig) -> Optional[Cache]:
        if not cfg.cache:
            return None
        if _is_maven(cfg):
            env = {"MAVEN_OPTS": f"-Dmaven.repo.local={ROOT}/.m2/repository"}
            return Cache("maven", (".m2/repository",), key_files=("pom.xml",), env=env)
        return Cache("gradle", (".gradle/caches", ".gradle/wrapper"), env={"GRADLE_USER_HOME": f"{ROOT}/.gradle"})

    def install(self, cfg: CIConfig, packages: Sequence[str] = ()) -> List[Step]:
        # Maven and Gradle resolve dependencies as part of each command.
        return [step("Resolve dependencies", run=cfg.install)] if cfg.install else []

    def lint(self, cfg: CIConfig, tools: List[str]) -> List[Item]:
        steps = self.install(cfg)
        for tool in tools:
            name, goal, tasks = _LINT[tool]
            steps.append(step(name, run=f"{build_tool(cfg.package_manager)} {goal if _is_maven(cfg) else tasks}"))
        return steps

    def test(self, cfg: CIConfig) -> List[Item]:
        t = cfg.test
        tool = build_tool(cfg.package_manager)
        if not t.coverage:
            cmd = f"{tool} {'verify' if _is_maven(cfg) else 'check'}"
            return [*self.install(cfg), step("Tests", run=cmd, secrets=t.env_secrets)]
        steps: List[Item] = list(self.install(cfg))
        if _is_maven(cfg):
            cmd = f"{tool} {_JACOCO}:prepare-agent verify {_JACOCO}:report"
        else:
            steps.append(step("JaCoCo for Gradle", run=_JACOCO_GRADLE))
            cmd = f"{tool} check --init-script {_JACOCO_INIT}"
        return [
            *steps,
            step("Tests with coverage", run=cmd, secrets=t.env_secrets),
            step(
                "Coverage threshold",
                run=_COVERAGE_CHECK.format(threshold=t.coverage_threshold, summary=SUMMARY_FILE),
            ),
        ]

    def coverage_file(self, cfg: CIConfig) -> str:
        if _is_maven(cfg):
            return "target/site/jacoco/jacoco.xml"
        return "build/reports/jacoco/test/jacocoTestReport.xml"

    def reports(self, cfg: CIConfig) -> TestReports:
        # Surefire and Gradle write JUnit results by themselves.
        regex = THRESHOLD_REGEX if cfg.test.coverage else ""
        if _is_maven(cfg):
            return TestReports(junit="target/surefire-reports/TEST-*.xml", coverage_regex=regex)
        return TestReports(junit="build/test-results/test/TEST-*.xml", coverage_regex=regex)

    def audit(self, cfg: CIConfig) -> List[Item]:
        return [
            install_osv_scanner(),
            step("Dependency vulnerability scan", run="osv-scanner scan source --recursive ."),
        ]

    def build(self, cfg: CIConfig) -> List[Item]:
        return [*self.install(cfg), step("Build", run=cfg.build.command)]

    def build_artifacts(self, det: Detection) -> List[str]:
        return ["target/*.jar"] if det.package_manager.startswith("maven") else ["build/libs/*.jar"]

    def dependabot_ecosystem(self, cfg: CIConfig) -> str:
        return "maven" if _is_maven(cfg) else "gradle"


def _is_maven(cfg: CIConfig) -> bool:
    return cfg.package_manager.startswith("maven")
