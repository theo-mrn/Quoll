from __future__ import annotations

from typer.testing import CliRunner

from quoll.main import app
from tests.samples import GO, NODE_YARN_BERRY, PYTHON_UV, RAILS

runner = CliRunner()


def _quoll(*args: str):
    return runner.invoke(app, list(args))


def test_init_writes_config_dockerfile_and_dockerignore(make_project) -> None:
    root = make_project(RAILS)
    result = _quoll("docker", "init", "-y", "-d", str(root))
    assert result.exit_code == 0, result.output
    assert '[docker]\nversion = "3.4"\nport = 3000' in (root / "quoll.toml").read_text()
    assert (root / "Dockerfile").read_text().startswith("# syntax=docker/dockerfile:1")
    assert "log/*" in (root / ".dockerignore").read_text()
    assert "docker compose up --build" in result.output


def test_ci_and_docker_share_the_project_section(make_project) -> None:
    root = make_project(PYTHON_UV)
    assert _quoll("ci", "init", "-y", "-d", str(root)).exit_code == 0
    result = _quoll("docker", "init", "-y", "-d", str(root), "--command", "python -m app")
    assert result.exit_code == 0, result.output
    text = (root / "quoll.toml").read_text()
    assert text.count('stack = "python"') == 1
    assert text.index("[project]") < text.index("[ci]") < text.index("[docker]")
    assert "build.docker = true" in result.output  # hint to build the image in CI
    assert _quoll("ci", "check", "-d", str(root)).exit_code == 0


def test_command_is_required_when_it_cannot_be_inferred(make_project) -> None:
    root = make_project(NODE_YARN_BERRY)
    result = _quoll("docker", "init", "-y", "-d", str(root))
    assert result.exit_code == 1
    assert "--command" in result.output
    assert not (root / "Dockerfile").exists()
    assert _quoll("docker", "init", "-y", "-d", str(root), "--command", "node lib/cli.js").exit_code == 0
    assert 'CMD ["node", "lib/cli.js"]' in (root / "Dockerfile").read_text()


def test_check_and_update_cycle(make_project) -> None:
    root = make_project(GO)
    (root / "Dockerfile").unlink()  # the sample ships a hand-written one
    assert _quoll("docker", "init", "-y", "-d", str(root)).exit_code == 0
    assert _quoll("docker", "check", "-d", str(root)).exit_code == 0

    config = root / "quoll.toml"
    config.write_text(config.read_text().replace("port = 8080", "port = 9000"))
    result = _quoll("docker", "check", "-d", str(root))
    assert result.exit_code == 1 and "out of date" in result.output

    assert _quoll("docker", "update", "-y", "-d", str(root)).exit_code == 0
    assert "EXPOSE 9000" in (root / "Dockerfile").read_text()
    assert "up to date" in _quoll("docker", "update", "-y", "-d", str(root)).output


def test_refuses_to_overwrite_a_hand_written_dockerfile(make_project) -> None:
    root = make_project(GO)  # ships "FROM golang"
    result = _quoll("docker", "init", "-y", "-d", str(root))
    assert result.exit_code == 1 and "--force" in result.output
    assert (root / "Dockerfile").read_text() == "FROM golang\n"
    assert _quoll("docker", "init", "-y", "--force", "-d", str(root)).exit_code == 0
    assert "distroless" in (root / "Dockerfile").read_text()


def test_check_without_config(make_project) -> None:
    result = _quoll("docker", "check", "-d", str(make_project(GO)))
    assert result.exit_code == 1 and "quoll docker init" in result.output


def test_invalid_docker_section(make_project) -> None:
    root = make_project(GO)
    (root / "quoll.toml").write_text(
        '[project]\nstack = "go"\npackage_manager = "go"\n\n[docker]\nversion = "1.23"\nstatic = true\n'
    )
    result = _quoll("docker", "check", "-d", str(root))
    assert result.exit_code == 1
    assert "output_dir is required when static is true" in result.output
