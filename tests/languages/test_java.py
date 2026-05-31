from __future__ import annotations

from quoll.ci.detect import detect
from tests.helpers import runs, steps, uses, workflow
from tests.samples import JAVA_GRADLE_KOTLIN, JAVA_MAVEN, SPRING_BOOT


def test_maven_wrapper(make_project) -> None:
    det = detect(make_project(JAVA_MAVEN))
    assert det.stack == "java"
    assert det.package_manager == "maven-wrapper"
    assert det.version == "17"
    assert det.matrix_versions == ["17", "21", "25"]
    assert det.lint_tools == ["spotless"]
    assert det.test_runner == "junit"
    assert det.build_command == "./mvnw -B -ntp package -DskipTests"
    doc = workflow(make_project, JAVA_MAVEN)
    assert steps(doc, "test")[1]["with"] == {"distribution": "temurin", "java-version": "17", "cache": "maven"}
    assert "./mvnw -B -ntp spotless:check" in runs(doc, "lint")
    # JaCoCo without any pom.xml change, and quoll's threshold over every module's report.
    test = runs(doc, "test")
    jacoco = "org.jacoco:jacoco-maven-plugin:0.8.16"
    assert f"./mvnw -B -ntp {jacoco}:prepare-agent verify {jacoco}:report" in test
    assert "below the %d%% threshold" in test and "min=80" in test


def test_gradle_kotlin(make_project) -> None:
    det = detect(make_project(JAVA_GRADLE_KOTLIN))
    assert det.package_manager == "gradle-wrapper"
    assert det.version == "21"
    assert det.lint_tools == ["ktlint"]
    doc = workflow(make_project, JAVA_GRADLE_KOTLIN)
    assert "gradle/actions/setup-gradle@v6" in uses(doc, "test")
    test = runs(doc, "test")
    assert "./gradlew check --init-script /tmp/quoll-jacoco.gradle" in test
    assert 'apply plugin: "jacoco"' in test


def test_static_analysis(make_project) -> None:
    """SpotBugs and PMD, when the build uses them (or when listed in [ci.lint] tools: no pom.xml change needed)."""
    pom = '<project><build><plugins><plugin><artifactId>spotbugs-maven-plugin</artifactId></plugin>' \
          '<plugin><artifactId>maven-pmd-plugin</artifactId></plugin></plugins></build></project>'
    det = detect(make_project({**JAVA_MAVEN, "pom.xml": pom}))
    assert det.lint_tools == ["spotbugs", "pmd"]
    lint = runs(workflow(make_project, {**JAVA_MAVEN, "pom.xml": pom}), "lint")
    assert "./mvnw -B -ntp compile com.github.spotbugs:spotbugs-maven-plugin:4.10.5.0:check" in lint
    assert "./mvnw -B -ntp org.apache.maven.plugins:maven-pmd-plugin:3.28.0:check" in lint


def test_without_wrapper_warns(make_project) -> None:
    det = detect(make_project({"pom.xml": "<project/>"}))
    assert det.package_manager == "maven"
    assert any("./mvnw" in w for w in det.warnings)


def test_spring_boot(make_project) -> None:
    assert detect(make_project(SPRING_BOOT)).framework == "spring-boot"
