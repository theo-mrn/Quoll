"""Backing services: detected per language, run next to the CI tests and in compose.yaml."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest
import yaml
from typer.testing import CliRunner

from quoll.ci.config import ConfigError, load_config
from quoll.ci.detect import detect
from quoll.docker.render import render_compose
from quoll.main import app
from quoll.platforms.github import ci as render
from tests.helpers import actionlint, config, load
from tests.samples import DJANGO, GO, JAVA_MAVEN, LARAVEL, RAILS, SPRING_BOOT


@pytest.mark.parametrize(
    "files, services",
    [
        ({"requirements.txt": "django\npsycopg[binary]\ncelery\nredis\n"}, ["postgres", "redis"]),
        ({"requirements.txt": "django-redis-sessions-extra\n"}, []),  # not the redis client
        ({"package.json": {"dependencies": {"ioredis": "5", "mongoose": "8"}}}, ["redis", "mongodb"]),
        (
            {"package.json": {"dependencies": {"@prisma/client": "6"}},
             "prisma/schema.prisma": 'datasource db {\n  provider = "postgresql"\n}\n'},
            ["postgres"],
        ),
        ({"go.mod": "module x\n\ngo 1.25\n\nrequire github.com/jackc/pgx/v5 v5.7.0\n"}, ["postgres"]),
        ({"Cargo.toml": '[dependencies]\nsqlx = { version = "0.8", features = ["mysql"] }\nredis = "0.27"\n'},
         ["mysql", "redis"]),
        ({"pom.xml": "<artifactId>postgresql</artifactId><groupId>org.postgresql</groupId>"}, ["postgres"]),
        ({"composer.json": {"require": {"ext-pdo_mysql": "*", "predis/predis": "2"}}}, ["mysql", "redis"]),
        ({"composer.json": {"require": {}}, ".env": "DATABASE_URL=\"postgresql://app@127.0.0.1/app\"\n"}, ["postgres"]),
        ({"Gemfile": 'gem "pg"\ngem "redis"\n'}, ["postgres", "redis"]),
        ({"App.csproj": '<PackageReference Include="Npgsql.EntityFrameworkCore.PostgreSQL" />'}, ["postgres"]),
    ],
)
def test_detection(make_project, files, services) -> None:
    assert detect(make_project(files)).services == services


def test_ci_runs_services_next_to_the_tests(make_project, tmp_path) -> None:
    files = {**DJANGO, "requirements.txt": "django\npsycopg\nredis\n"}
    cfg = config(make_project, files, test__env_secrets=["DATABASE_URL", "STRIPE_KEY"])
    text = render.render_workflow(cfg)
    test = load(text)["jobs"]["test"]
    assert set(test["services"]) == {"postgres", "redis"}
    assert test["services"]["postgres"]["ports"] == ["5432:5432"]
    assert "--health-cmd" in test["services"]["postgres"]["options"]
    assert test["env"]["DATABASE_URL"] == "postgresql://app:app@127.0.0.1:5432/app"
    assert test["env"]["REDIS_URL"] == "redis://127.0.0.1:6379"
    # The test database wins over a secret of the same name; other secrets stay.
    step_env = next(s for s in test["steps"] if s.get("name", "").startswith("Tests"))["env"]
    assert step_env == {"STRIPE_KEY": "${{ secrets.STRIPE_KEY }}"}
    actionlint(tmp_path, text)


def test_no_services_no_containers(make_project) -> None:
    assert "services" not in load(render.render_workflow(config(make_project, GO)))["jobs"]["test"]


@pytest.mark.parametrize(
    "files, expected",
    [
        ({**LARAVEL, ".env.example": "DB_CONNECTION=pgsql\n"}, {"DB_CONNECTION": "pgsql", "DB_HOST": "127.0.0.1"}),
        (
            {**SPRING_BOOT, "pom.xml": SPRING_BOOT["pom.xml"] + "<groupId>org.postgresql</groupId>"},
            {"SPRING_DATASOURCE_URL": "jdbc:postgresql://127.0.0.1:5432/app"},
        ),
        (
            {**RAILS, "Gemfile": RAILS["Gemfile"] + 'gem "mysql2"\n'},
            {"DATABASE_URL": "mysql2://root:root@127.0.0.1:3306/app"},
        ),
    ],
)
def test_frameworks_add_their_own_variables(make_project, files, expected) -> None:
    env = load(render.render_workflow(config(make_project, files)))["jobs"]["test"]["env"]
    assert expected.items() <= env.items()


def test_compose(make_project) -> None:
    pom = JAVA_MAVEN["pom.xml"] + "<artifactId>jedis</artifactId><groupId>com.mysql</groupId>"
    files = {**JAVA_MAVEN, "pom.xml": pom}
    root = make_project(files)
    result = CliRunner().invoke(app, ["docker", "init", "-y", "-d", str(root)])
    assert result.exit_code == 0, result.output
    doc = yaml.safe_load((root / "compose.yaml").read_text())
    app_service = doc["services"]["app"]
    assert app_service["build"] == "."
    assert app_service["environment"]["DATABASE_URL"] == "mysql://root:root@mysql:3306/app"
    assert app_service["environment"]["REDIS_URL"] == "redis://redis:6379"
    healthy = {"condition": "service_healthy"}
    assert app_service["depends_on"] == {"mysql": healthy, "redis": healthy}
    assert doc["services"]["mysql"]["healthcheck"]["test"][0] == "CMD-SHELL"
    assert doc["volumes"] == {"mysql-data": None, "redis-data": None}
    if os.environ.get("QUOLL_DOCKER_TESTS") and shutil.which("docker"):
        check = subprocess.run(["docker", "compose", "config", "-q"], cwd=root, capture_output=True, text=True)
        assert check.returncode == 0, check.stderr


def test_hand_written_compose_file_is_left_alone(make_project) -> None:
    root = make_project({**RAILS, "docker-compose.yml": "services: {}\n"})
    assert CliRunner().invoke(app, ["docker", "init", "-y", "-d", str(root)]).exit_code == 0
    assert not (root / "compose.yaml").exists()


def test_compose_without_services(make_project) -> None:
    from quoll.docker.detect import default_config, image_defaults

    root = make_project(RAILS)
    cfg, _ = default_config(detect(root), image_defaults(root, detect(root)))
    doc = yaml.safe_load(render_compose(cfg))
    assert set(doc) == {"services"} and "depends_on" not in doc["services"]["app"]


def test_unknown_service(make_project) -> None:
    root = make_project({"quoll.toml": '[project]\nstack = "go"\npackage_manager = "go"\nservices = ["oracle"]\n'
                                       '[ci]\ninstall = "go mod download"\n[ci.test]\nrunner = "go"\n'})
    with pytest.raises(ConfigError, match="project.services.*unknown service 'oracle'"):
        load_config(root)
