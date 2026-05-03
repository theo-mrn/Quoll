"""Language-independent detection. Per-language detection is tested in tests/languages/."""
from __future__ import annotations

import subprocess

import pytest

from quoll.ci.detect import default_config, detect, parse_env_file
from tests.samples import GO


def test_mixed_repository_warns(make_project) -> None:
    det = detect(make_project({**GO, "package.json": {"name": "tools"}}))
    assert det.stack == "go"
    assert det.other_stacks == ["node"]
    assert any("one stack" in w for w in det.warnings)


def test_nothing_detected(make_project) -> None:
    det = detect(make_project({"README.md": "hi"}))
    assert det.stack is None
    with pytest.raises(ValueError):
        default_config(det)


@pytest.mark.parametrize(
    "url, host, path, platform",
    [
        ("git@github.com:theo-mrn/Quoll.git", "github.com", "theo-mrn/Quoll", "github"),
        ("https://github.com/acme/api", "github.com", "acme/api", "github"),
        ("https://gitlab.com/acme/backend/api.git", "gitlab.com", "acme/backend/api", "gitlab"),
        ("ssh://git@gitlab.acme.io:2222/team/api.git", "gitlab.acme.io", "team/api", "gitlab"),
        ("https://git.acme.io/team/api.git", "git.acme.io", "team/api", "github"),
    ],
)
def test_remote_and_platform(make_project, url, host, path, platform) -> None:
    root = make_project({"go.mod": "module x\n\ngo 1.22\n"})
    subprocess.run(["git", "init", "-q", "-b", "trunk"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", url], cwd=root, check=True)
    det = detect(root)
    assert (det.remote.host, det.remote.path, det.platform) == (host, path, platform)
    assert det.default_branch == "trunk"


def test_platform_without_remote(make_project) -> None:
    assert detect(make_project(GO)).platform == "github"
    assert detect(make_project({**GO, ".gitlab-ci.yml": ""})).platform == "gitlab"


def test_quoll_toml_platform_wins(make_project) -> None:
    root = make_project({**GO, "quoll.toml": '[project]\nplatform = "gitlab"\n'})
    assert detect(root).platform == "gitlab"


def test_gitlab_config_pins_the_version(make_project) -> None:
    # GitLab jobs run in images chosen by version: a version file can't be read there.
    det = detect(make_project({**GO, ".gitlab-ci.yml": ""}))
    cfg = default_config(det)
    assert (cfg.platform, cfg.versions, cfg.version_file) == ("gitlab", ["1.23"], "")


def test_parse_env_file(tmp_path) -> None:
    env = tmp_path / ".env.example"
    env.write_text('# comment\nDATABASE_URL=\nexport DEBUG="1"\n\nEMPTY\n')
    assert parse_env_file(env) == {"DATABASE_URL": "", "DEBUG": "1", "EMPTY": ""}
