"""The plugin mechanism: a language or framework added from outside quoll works end to end."""
from __future__ import annotations

from typing import List, Optional, Sequence

import pytest
import yaml
from typer.testing import CliRunner

from quoll import languages
from quoll.ci.config import load_config
from quoll.ci.detect import detect
from quoll.ci.steps import step
from quoll.languages.base import CISteps, Detection, Framework, FrameworkCI, Language, Step
from quoll.main import app
from quoll.platforms.github import ci as render
from quoll.project import Project
from tests.helpers import actionlint, gitlab_lint, load, runs


class ElixirCI(CISteps):
    version_key = "elixir-version"

    def setup(self, cfg, version: Optional[str]) -> List[Step]:
        return [step("Set up Elixir", run=f"echo elixir {version or 'from .tool-versions'}")]

    def image(self, cfg, version: str) -> str:
        return f"elixir:{version}"

    def install(self, cfg, packages: Sequence[str] = ()) -> List[Step]:
        return [step("Install dependencies", run=cfg.install)]

    def lint(self, cfg, tools: List[str]) -> List[Step]:
        return [*self.install(cfg), *(step(tool, run=f"mix {tool}") for tool in tools)]

    def test(self, cfg) -> List[Step]:
        return [*self.install(cfg), step("Tests", run="mix test")]

    def coverage_file(self, cfg) -> str:
        return "cover/lcov.info"

    def audit(self, cfg) -> List[Step]:
        return [step("Audit", run="mix deps.audit")]

    def build(self, cfg) -> List[Step]:
        return [step("Build", run=cfg.build.command)]

    def dependabot_ecosystem(self, cfg) -> str:
        return "mix"


def _detect_elixir(project: Project) -> Detection:
    return Detection(
        package_manager="mix",
        lockfile="mix.lock" if project.exists("mix.lock") else "",
        install="mix deps.get",
        version="1.18",
        lint_tools=["format"],
        test_runner="exunit",
        build_command="mix compile --warnings-as-errors",
    )


class PhoenixCI(FrameworkCI):
    def env(self, cfg):
        return {"MIX_ENV": "test"}

    def lint(self, cfg, tool):
        return [step("Unused dependencies", run="mix deps.unlock --check-unused")]


def _detect_phoenix(project: Project, det: Detection) -> bool:
    if ":phoenix" not in project.read_text("mix.exs"):
        return False
    det.lint_tools.append("phoenix-deps")
    return True


PHOENIX = Framework(
    name="phoenix", language="elixir", detect=_detect_phoenix, ci=PhoenixCI(), lint_tools=("phoenix-deps",)
)

ELIXIR = Language(
    name="elixir",
    markers=("mix.exs",),
    package_managers=("mix",),
    lint_tools=("format", "credo"),
    test_runners=("exunit",),
    detect=_detect_elixir,
    ci=ElixirCI(),
)


@pytest.fixture()
def registry(monkeypatch):
    """An isolated copy of the registry, so tests can register plugins freely."""
    languages.available()
    monkeypatch.setattr(languages, "_languages", dict(languages._languages))
    monkeypatch.setattr(languages, "_frameworks", {k: list(v) for k, v in languages._frameworks.items()})


def test_registered_language_and_framework_work_end_to_end(registry, make_project, tmp_path) -> None:
    languages.register(ELIXIR)
    languages.register_framework(PHOENIX)
    root = make_project({"mix.exs": 'defp deps, do: [{:phoenix, "~> 1.8"}]\n', "mix.lock": ""})

    det = detect(root)
    assert (det.stack, det.framework) == ("elixir", "phoenix")
    assert det.lint_tools == ["format", "phoenix-deps"]

    result = CliRunner().invoke(app, ["ci", "init", "-y", "-d", str(root)])
    assert result.exit_code == 0, result.output
    cfg = load_config(root)
    assert cfg.language is ELIXIR and cfg.get_framework() is PHOENIX

    text = (root / render.WORKFLOW_PATH).read_text()
    doc = load(text)
    assert doc["env"] == {"MIX_ENV": "test"}
    assert "mix format" in runs(doc, "lint") and "mix deps.unlock --check-unused" in runs(doc, "lint")
    assert "mix compile --warnings-as-errors" in runs(doc, "build")
    assert 'package-ecosystem: "mix"' in (root / render.DEPENDABOT_PATH).read_text()
    actionlint(tmp_path, text)


def test_registered_language_runs_on_gitlab(registry, make_project, tmp_path) -> None:
    languages.register(ELIXIR)
    languages.register_framework(PHOENIX)
    root = make_project({"mix.exs": 'defp deps, do: [{:phoenix, "~> 1.8"}]\n', "mix.lock": ""})

    result = CliRunner().invoke(app, ["ci", "init", "-y", "--platform", "gitlab", "-d", str(root)])
    assert result.exit_code == 0, result.output
    doc = yaml.safe_load((root / ".gitlab/quoll-ci.yml").read_text())
    assert doc["variables"] == {"MIX_ENV": "test"}
    assert doc["lint"]["image"] == "elixir:1.18"
    assert "mix deps.unlock --check-unused" in doc["lint"]["script"]
    gitlab_lint(tmp_path, (root / ".gitlab/quoll-ci.yml").read_text())


def test_config_is_validated_against_the_plugins(registry, make_project) -> None:
    languages.register(ELIXIR)
    languages.register_framework(PHOENIX)
    root = make_project({"mix.exs": ":phoenix"})
    assert CliRunner().invoke(app, ["ci", "init", "-y", "-d", str(root)]).exit_code == 0
    config = root / "quoll.toml"
    text = config.read_text()

    config.write_text(text.replace('"format"', '"eslint"'))
    with pytest.raises(Exception, match=r"unknown lint tool 'eslint' for elixir/phoenix \(expected one of: "):
        load_config(root)

    config.write_text(text.replace('framework = "phoenix"', 'framework = "rails"'))
    with pytest.raises(Exception, match="unknown framework 'rails' for elixir"):
        load_config(root)


def test_unknown_stack_lists_available_languages(make_project) -> None:
    root = make_project({"quoll.toml": '[ci]\nstack = "cobol"\npackage_manager = "x"\ninstall = "x"\n'})
    with pytest.raises(Exception, match=r"unknown stack 'cobol' \(expected one of: go, rust, java, dotnet"):
        load_config(root)


def test_register_rejects_duplicates_and_bad_plugins(registry) -> None:
    with pytest.raises(ValueError, match="already registered"):
        languages.register(languages.get("python"))
    with pytest.raises(ValueError, match="already registered for python"):
        languages.register_framework(languages.get_framework("python", "django"))
    with pytest.raises(ValueError, match="unknown language 'elixir'"):
        languages.register_framework(PHOENIX)
    with pytest.raises(TypeError):
        languages.register(object())  # type: ignore[arg-type]


def test_builtin_priority(make_project) -> None:
    project = Project(make_project({"Gemfile": "", "package.json": "{}", "requirements.txt": ""}))
    assert [lang.name for lang in languages.matching(project)] == ["ruby", "python", "node"]


def test_framework_without_implementation_fails_clearly() -> None:
    with pytest.raises(NotImplementedError, match="declares lint tool 'x'"):
        FrameworkCI().lint(None, "x")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- entry points


class _EntryPoint:
    def __init__(self, name: str, target) -> None:
        self.name, self.value, self._target = name, f"{name}_plugin:plugin", target

    def load(self):
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


@pytest.fixture()
def fresh_registry(monkeypatch):
    monkeypatch.setattr(languages, "_languages", {})
    monkeypatch.setattr(languages, "_frameworks", {})
    monkeypatch.setattr(languages, "_loaded", False)


def test_entry_point_plugins_are_loaded_after_builtins(fresh_registry, monkeypatch) -> None:
    plugins = {
        languages.LANGUAGES_GROUP: [_EntryPoint("elixir", ELIXIR)],
        languages.FRAMEWORKS_GROUP: [_EntryPoint("phoenix", PHOENIX)],
    }
    monkeypatch.setattr(languages, "_entry_points", lambda group: plugins[group])
    assert languages.names()[-1] == "elixir"
    assert languages.frameworks("elixir") == [PHOENIX]


def test_broken_plugin_names_the_culprit(fresh_registry, monkeypatch) -> None:
    broken = {languages.LANGUAGES_GROUP: [_EntryPoint("elixir", ImportError("no module"))]}
    monkeypatch.setattr(languages, "_entry_points", lambda group: broken.get(group, []))
    with pytest.raises(RuntimeError, match="plugin 'elixir' .* failed to load: no module"):
        languages.available()
