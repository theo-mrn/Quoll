from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from quoll import platforms
from quoll.config.settings import settings
from quoll.main import app


def test_add_secret_goes_to_the_remote_platform(tmp_path, monkeypatch) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@gitlab.acme.io:team/api.git"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "gitlab_token", "token")
    calls = {}

    class FakeAPI:
        def set_secrets(self, repo, secrets):
            calls["secrets"] = (repo, secrets)

    monkeypatch.setattr(platforms.get("gitlab"), "api", lambda host=None: calls.update(host=host) or FakeAPI())
    result = CliRunner().invoke(app, ["add-secret", "-k", "API_KEY", "-v", "s3cret-value"])

    assert result.exit_code == 0, result.output
    assert calls == {"host": "gitlab.acme.io", "secrets": ("team/api", {"API_KEY": "s3cret-value"})}
    assert (tmp_path / ".env").read_text() == "API_KEY=s3cret-value\n"
    assert "GitLab repo 'team/api'" in result.output


def test_add_secret_local_only(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["add-secret", "-k", "A", "-v", "b", "--local"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".env").read_text() == "A=b\n"
