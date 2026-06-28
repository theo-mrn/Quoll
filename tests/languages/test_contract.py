"""Checks every built-in language and framework against the plugin contract.

A new language or framework gets these tests for free once it has a sample project in tests/samples.py.
"""
from __future__ import annotations

import pytest
import yaml

from quoll import languages
from quoll.ci.detect import detect
from quoll.platforms.github import ci as render
from quoll.platforms.github.ci import render_setup_action
from quoll.platforms.gitlab.ci import render_pipeline
from tests.helpers import action_lint, actionlint, config, gitlab_lint, load
from tests.samples import SAMPLE_BY_FRAMEWORK, SAMPLE_BY_LANGUAGE

ALL_FRAMEWORKS = [fw for lang in languages.available() for fw in languages.frameworks(lang.name)]


def _language_options():
    for lang in languages.available():
        for pm in lang.package_managers:
            for runner in lang.test_runners:
                yield pytest.param(lang, pm, runner, id=f"{lang.name}-{pm}-{runner}")


def _framework_options():
    for fw in ALL_FRAMEWORKS:
        for runner in (*languages.get(fw.language).test_runners, *fw.test_runners):
            yield pytest.param(fw, runner, id=f"{fw.name}-{runner}")


def _render_everything(make_project, files, platform: str = "github", **overrides) -> str:
    """Every job enabled, a version matrix and Codecov, so each code path of the plugin runs."""
    lang = languages.get(detect(make_project(files)).stack)
    codeql = platform == "github" and bool(lang.ci.codeql_language)
    cfg = config(
        make_project,
        files,
        platform=platform,
        build={"enabled": True, "command": "make build", "docker": True},
        security={"audit": True, "secrets": True, "sast": True, "codeql": codeql, "sbom": True, "licenses": True},
        versions=["1", "2"],
        **overrides,
    )
    if platform == "gitlab":
        text = render_pipeline(cfg)
        assert {"lint", "test", "audit", "build", "docker", "secrets", "sast", "sbom"} <= set(yaml.safe_load(text))
        return text
    text = render.render_workflow(cfg)
    expected = {"lint", "test", "audit", "build", "docker", "secrets", "sast", "sbom", "ci-result"}
    if codeql:
        expected.add("codeql")
    assert set(load(text)["jobs"]) == expected
    return text


def test_every_language_and_framework_has_a_sample() -> None:
    assert set(languages.names()) == set(SAMPLE_BY_LANGUAGE)
    assert {fw.name for fw in ALL_FRAMEWORKS} == set(SAMPLE_BY_FRAMEWORK)


@pytest.mark.parametrize("name", list(SAMPLE_BY_LANGUAGE))
def test_language_sample_is_detected(make_project, name) -> None:
    det = detect(make_project(SAMPLE_BY_LANGUAGE[name]))
    assert (det.stack, det.framework) == (name, "")


@pytest.mark.parametrize("fw", ALL_FRAMEWORKS, ids=lambda fw: fw.name)
def test_framework_sample_is_detected(make_project, fw) -> None:
    det = detect(make_project(SAMPLE_BY_FRAMEWORK[fw.name]))
    assert (det.stack, det.framework) == (fw.language, fw.name)


PLATFORMS = pytest.mark.parametrize("platform", ["github", "gitlab"])


def _validate(tmp_path, platform: str, text: str) -> None:
    if platform == "github":
        actionlint(tmp_path, text)
    else:
        gitlab_lint(tmp_path, text)


@PLATFORMS
@pytest.mark.parametrize("lang, package_manager, runner", list(_language_options()))
def test_every_language_option_renders_a_valid_pipeline(
    make_project, tmp_path, platform, lang, package_manager, runner
) -> None:
    text = _render_everything(
        make_project,
        SAMPLE_BY_LANGUAGE[lang.name],
        platform,
        package_manager=package_manager,
        lint={"enabled": True, "tools": list(lang.lint_tools)},
        test={"enabled": True, "runner": runner, "codecov": True},
    )
    _validate(tmp_path, platform, text)


@PLATFORMS
@pytest.mark.parametrize("fw, runner", list(_framework_options()))
def test_every_framework_option_renders_a_valid_pipeline(make_project, tmp_path, platform, fw, runner) -> None:
    lang = languages.get(fw.language)
    text = _render_everything(
        make_project,
        SAMPLE_BY_FRAMEWORK[fw.name],
        platform,
        framework=fw.name,
        lint={"enabled": True, "tools": [*lang.lint_tools, *fw.lint_tools]},
        test={"enabled": True, "runner": runner, "codecov": True},
    )
    _validate(tmp_path, platform, text)


@pytest.mark.parametrize("name", [*SAMPLE_BY_LANGUAGE, *SAMPLE_BY_FRAMEWORK])
def test_setup_action_is_valid(make_project, tmp_path, name) -> None:
    """The quoll-setup action your own workflows use, for every language and framework."""
    files = SAMPLE_BY_LANGUAGE.get(name) or SAMPLE_BY_FRAMEWORK[name]
    action_lint(tmp_path, render_setup_action(config(make_project, files)))


@pytest.mark.parametrize("lang", languages.available(), ids=lambda lang: lang.name)
def test_language_declares_its_metadata(lang) -> None:
    assert lang.markers and lang.package_managers and lang.test_runners
    assert lang.ci.version_key
    assert all(fw.language == lang.name for fw in lang.frameworks)


@pytest.mark.parametrize("lang", languages.available(), ids=lambda lang: lang.name)
def test_language_ships_a_docker_image(lang) -> None:
    assert lang.docker is not None
