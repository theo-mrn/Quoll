"""Run the generated .gitlab-ci.yml of real projects with gitlab-ci-local (jobs in Docker, services included).

Slow (downloads images and dependencies), so opt-in:

    QUOLL_GITLAB_TESTS=run pytest tests/platforms/test_gitlab_run.py

gitlab-ci-local is taken from $GITLAB_CI_LOCAL, else run through npx.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, List

import pytest
import yaml
from typer.testing import CliRunner

from quoll.main import app

pytestmark = pytest.mark.skipif(
    os.environ.get("QUOLL_GITLAB_TESTS") != "run", reason="set QUOLL_GITLAB_TESTS=run to run real GitLab pipelines"
)

GITLAB_CI_LOCAL = os.environ.get("GITLAB_CI_LOCAL", "")


def _write(root: Path, files: Dict[str, object]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=2) if isinstance(content, (dict, list)) else str(content))


def _sh(cmd: List[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _in_container(image: str, script: str, root: Path) -> None:
    _sh(["docker", "run", "--rm", "-v", f"{root}:/work", "-w", "/work", image, "sh", "-c", script], root)


# --------------------------------------------------------------------------- projects (lint and tests pass)


def python_uv_postgres(root: Path) -> None:
    _write(root, {
        "pyproject.toml": '[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
        'dependencies = ["psycopg[binary]>=3.2"]\n\n[dependency-groups]\ndev = ["pytest>=8", "pytest-cov>=5", '
        '"ruff>=0.6"]\n\n[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/app"]\n',
        ".python-version": "3.13\n",
        "src/app/__init__.py": "import os\n\nimport psycopg\n\n\ndef db_ping() -> int:\n"
        '    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:\n'
        '        return conn.execute("SELECT 1").fetchone()[0]\n',
        # Reaches the Postgres service through the exported DATABASE_URL.
        "tests/test_app.py": "from app import db_ping\n\n\ndef test_db() -> None:\n    assert db_ping() == 1\n",
    })
    _sh(["uv", "lock"], root)


def go_module(root: Path) -> None:
    _write(root, {
        "go.mod": "module example.com/calc\n\ngo 1.25\n",
        "go.sum": "",
        "calc/calc.go": "// Package calc adds numbers.\npackage calc\n\n// Add returns a+b.\n"
        "func Add(a, b int) int {\n\treturn a + b\n}\n",
        "calc/calc_test.go": 'package calc\n\nimport "testing"\n\nfunc TestAdd(t *testing.T) {\n'
        '\tif Add(1, 2) != 3 {\n\t\tt.Fatal("1+2")\n\t}\n}\n',
    })


def node_pnpm(root: Path) -> None:
    _write(root, {
        "package.json": {
            "name": "calc",
            "private": True,
            "type": "module",
            "packageManager": "pnpm@10.18.0",
            "devDependencies": {"vitest": "^3.2.0", "@vitest/coverage-v8": "^3.2.0"},
        },
        "src/calc.js": "export const add = (a, b) => a + b;\n",
        "src/calc.test.js": 'import { expect, test } from "vitest";\nimport { add } from "./calc.js";\n\n'
        'test("add", () => expect(add(1, 2)).toBe(3));\n',
    })
    _sh(["pnpm", "install", "--lockfile-only"], root)


def php_intl(root: Path) -> None:
    _write(root, {
        "composer.json": {
            "name": "acme/calc",
            "require": {"php": ">=8.2", "ext-intl": "*", "psr/log": "^3.0"},
            "require-dev": {"phpunit/phpunit": "^11.5"},
            "autoload": {"psr-4": {"Acme\\": "src/"}},
        },
        "phpunit.xml": '<?xml version="1.0"?>\n<phpunit bootstrap="vendor/autoload.php">\n'
        '  <testsuites><testsuite name="unit"><directory>tests</directory></testsuite></testsuites>\n'
        "  <source><include><directory>src</directory></include></source>\n</phpunit>\n",
        # Needs ext-intl, which the php image lacks: installed from the lock file's requirements.
        "src/Calc.php": "<?php\n\nnamespace Acme;\n\nfinal class Calc\n{\n    public static function format(int $n): "
        "string\n    {\n        return (new \\NumberFormatter('en', \\NumberFormatter::DECIMAL))->format($n);\n"
        "    }\n}\n",
        "tests/CalcTest.php": "<?php\n\nuse Acme\\Calc;\nuse PHPUnit\\Framework\\TestCase;\n\n"
        "final class CalcTest extends TestCase\n{\n    public function testFormat(): void\n    {\n"
        "        $this->assertSame('1,234', Calc::format(1234));\n    }\n}\n",
    })
    _in_container("composer:2", "composer update --no-install --ignore-platform-reqs --no-interaction", root)


def ruby_rspec(root: Path) -> None:
    _write(root, {
        "Gemfile": "# frozen_string_literal: true\n\nsource 'https://rubygems.org'\n\ngem 'rspec', '~> 3.13'\n"
        "gem 'rubocop', '~> 1.75', require: false\ngem 'simplecov', require: false\n",
        ".rubocop.yml": "AllCops:\n  NewCops: enable\n  SuggestExtensions: false\n  Exclude: ['vendor/**/*']\n",
        "lib/calc.rb": "# frozen_string_literal: true\n\n# Adds numbers.\nmodule Calc\n  def self.add(left, right)\n"
        "    left + right\n  end\nend\n",
        "spec/spec_helper.rb": "# frozen_string_literal: true\n\nrequire 'simplecov'\nSimpleCov.start\n",
        "spec/calc_spec.rb": "# frozen_string_literal: true\n\nrequire 'spec_helper'\n"
        "require_relative '../lib/calc'\n\nRSpec.describe Calc do\n  it 'adds' do\n"
        "    expect(described_class.add(1, 2)).to eq(3)\n  end\nend\n",
        ".rspec": "--require spec_helper\n",
    })
    _in_container("ruby:3.4", "bundle lock", root)


def rust_crate(root: Path) -> None:
    _write(root, {
        "Cargo.toml": '[package]\nname = "calc"\nversion = "0.1.0"\nedition = "2021"\n',
        "Cargo.lock": '# This file is automatically @generated by Cargo.\n# It is not intended for manual editing.\n'
        'version = 4\n\n[[package]]\nname = "calc"\nversion = "0.1.0"\n',
        "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n\n#[cfg(test)]\nmod tests {\n"
        "    #[test]\n    fn adds() {\n        assert_eq!(super::add(1, 2), 3);\n    }\n}\n",
    })


def rust_nextest(root: Path) -> None:
    rust_crate(root)
    _write(root, {".config/nextest.toml": "[profile.default]\nslow-timeout = \"60s\"\n"})


def node_jest(root: Path) -> None:
    _write(root, {
        "package.json": {"name": "calc", "private": True, "scripts": {"test": "jest"},
                         "devDependencies": {"jest": "^30.0.0"}},
        "calc.js": "exports.add = (a, b) => a + b;\n",
        "calc.test.js": 'const { add } = require("./calc");\n\ntest("add", () => expect(add(1, 2)).toBe(3));\n',
    })
    _sh(["npm", "install", "--package-lock-only", "--silent"], root)


def dotnet_xunit(root: Path) -> None:
    _in_container(
        "mcr.microsoft.com/dotnet/sdk:9.0",
        "dotnet new sln -n Calc && dotnet new xunit -o Calc.Tests && dotnet sln add Calc.Tests "
        "&& dotnet restore --use-lock-file && rm -rf Calc.Tests/bin Calc.Tests/obj",
        root,
    )


def java_maven(root: Path) -> None:
    _write(root, {
        "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.acme</groupId>
  <artifactId>calc</artifactId>
  <version>0.1.0</version>
  <properties>
    <maven.compiler.release>21</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.13.4</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.5.3</version>
      </plugin>
    </plugins>
  </build>
</project>
""",
        # The private constructor of a utility class doesn't count against coverage (JaCoCo filters it out).
        "src/main/java/com/acme/Calc.java": "package com.acme;\n\npublic final class Calc {\n"
        "    private Calc() {}\n\n    public static int add(int a, int b) {\n        return a + b;\n    }\n}\n",
        "src/test/java/com/acme/CalcTest.java": "package com.acme;\n\nimport static org.junit.jupiter.api.Assertions"
        ".assertEquals;\n\nimport org.junit.jupiter.api.Test;\n\nclass CalcTest {\n    @Test\n    void adds() {\n"
        "        assertEquals(3, Calc.add(1, 2));\n    }\n}\n",
    })


def cpp_cmake(root: Path) -> None:
    _write(root, {
        "CMakeLists.txt": "cmake_minimum_required(VERSION 3.25)\nproject(calc CXX)\nset(CMAKE_CXX_STANDARD 20)\n"
        "add_library(calclib src/calc.cpp)\ntarget_include_directories(calclib PUBLIC src)\n"
        "add_executable(calc src/main.cpp)\ntarget_link_libraries(calc calclib)\n"
        "enable_testing()\nadd_executable(calc_tests tests/test_calc.cpp)\n"
        "target_link_libraries(calc_tests calclib)\nadd_test(NAME calc COMMAND calc_tests)\n"
        "add_test(NAME smoke COMMAND calc)\n",
        ".clang-format": "BasedOnStyle: Google\n",
        ".clang-tidy": "Checks: 'bugprone-*,performance-*,-bugprone-easily-swappable-parameters'\n"
        "WarningsAsErrors: '*'\n",
        "src/calc.hpp": "#pragma once\n\nnamespace calc {\nint add(int a, int b);\n}  // namespace calc\n",
        "src/calc.cpp": '#include "calc.hpp"\n\nnamespace calc {\nint add(int a, int b) { return a + b; }\n'
        "}  // namespace calc\n",
        "src/main.cpp": '#include "calc.hpp"\n\nint main() { return calc::add(1, 1) == 2 ? 0 : 1; }\n',
        "tests/test_calc.cpp": '#include "calc.hpp"\n\nint main() { return calc::add(2, 3) == 5 ? 0 : 1; }\n',
    })
    # Formatted by the same clang-format as the CI's.
    _in_container(
        "ubuntu:24.04",
        "apt-get update -qq && apt-get install -y -qq clang-format >/dev/null && clang-format -i src/* tests/*",
        root,
    )


PROJECTS: Dict[str, Callable[[Path], None]] = {
    "python-uv-postgres": python_uv_postgres,
    "go": go_module,
    "node-pnpm": node_pnpm,
    "php-intl": php_intl,
    "ruby-rspec": ruby_rspec,
    "rust": rust_crate,
    "rust-nextest": rust_nextest,
    "node-jest": node_jest,
    "dotnet": dotnet_xunit,
    "java-maven": java_maven,
    "cpp-cmake": cpp_cmake,
}


def _gitlab_ci_local() -> List[str]:
    if GITLAB_CI_LOCAL:
        return [GITLAB_CI_LOCAL]
    if not shutil.which("npx"):
        pytest.skip("gitlab-ci-local not available (set GITLAB_CI_LOCAL or install npx)")
    return ["npx", "--yes", "gitlab-ci-local@4.77.1"]


def test_workspace_pipeline_passes(tmp_path) -> None:
    """A monorepo: a Python back-end with Postgres and a Node front-end, one pipeline, jobs per project."""
    root = tmp_path / "shop"
    (root / "backend").mkdir(parents=True)
    (root / "frontend").mkdir()
    python_uv_postgres(root / "backend")
    node_pnpm(root / "frontend")
    # rules:changes compares with origin/main: a real (local) remote holding a first commit.
    origin = tmp_path / "origin.git"
    _sh(["git", "init", "-q", "--bare", "-b", "main", str(origin)], tmp_path)
    _sh(["git", "init", "-q", "-b", "main"], root)
    _sh(["git", "-c", "user.name=quoll", "-c", "user.email=quoll@example.com", "commit", "-q", "--allow-empty",
         "-m", "base"], root)
    _sh(["git", "remote", "add", "origin", str(origin)], root)
    _sh(["git", "push", "-q", "origin", "main"], root)
    result = CliRunner().invoke(app, ["ci", "init", "-y", "--platform", "gitlab", "-d", str(root)])
    assert result.exit_code == 0, result.output
    assert (root / "backend/quoll.toml").exists() and (root / "frontend/quoll.toml").exists()
    _sh(["git", "add", "-A"], root)
    _sh(["git", "-c", "user.name=quoll", "-c", "user.email=quoll@example.com", "commit", "-qm", "init"], root)

    run = subprocess.run(
        [*_gitlab_ci_local(), "--concurrency", "2"], cwd=root, capture_output=True, text=True, timeout=1500
    )
    output = run.stdout + run.stderr
    assert run.returncode == 0, output[-6000:]
    for job in ("backend-test", "frontend-test", "backend-lint", "secrets", "sast"):
        assert f" PASS  {job}" in output, output[-3000:]


@pytest.mark.parametrize("name", list(PROJECTS))
def test_pipeline_passes(tmp_path, name) -> None:
    root = tmp_path / name
    root.mkdir()
    PROJECTS[name](root)
    _sh(["git", "init", "-q", "-b", "main"], root)
    _sh(["git", "remote", "add", "origin", f"git@gitlab.com:acme/{name}.git"], root)
    result = CliRunner().invoke(app, ["ci", "init", "-y", "-d", str(root)])
    assert result.exit_code == 0, result.output
    # The reports the merge request widgets read must be there (gitlab-ci-local doesn't collect them): a step of
    # the project's own checks they are.
    test_job = yaml.safe_load((root / ".gitlab/quoll-ci.yml").read_text())["test"]
    reports = test_job.get("artifacts", {}).get("reports", {})
    paths = [*([reports["junit"]] if "junit" in reports else []),
             *([reports["coverage_report"]["path"]] if "coverage_report" in reports else [])]
    if paths:
        with open(root / "quoll.toml", "a") as config:
            config.write(f'\n[[ci.steps]]\njob = "test"\nwhen = "after"\nname = "Reports"\n'
                         f'run = "ls -l {" ".join(paths)}"\n')
        result = CliRunner().invoke(app, ["ci", "update", "-y", "-d", str(root)])
        assert result.exit_code == 0, result.output
    _sh(["git", "add", "-A"], root)
    _sh(["git", "-c", "user.name=quoll", "-c", "user.email=quoll@example.com", "commit", "-qm", "init"], root)

    run = subprocess.run(
        [*_gitlab_ci_local(), "--concurrency", "2"], cwd=root, capture_output=True, text=True, timeout=1500
    )
    output = run.stdout + run.stderr
    assert run.returncode == 0, output[-6000:]
    assert " PASS  test" in output, output[-3000:]



def test_chart_job_passes(tmp_path) -> None:
    """The chart job: helm lint, kubeconform, Trivy's misconfiguration scan, in GitLab's helm image."""
    root = tmp_path / "chart"
    root.mkdir()
    go_module(root)
    _sh(["git", "init", "-q", "-b", "main"], root)
    _sh(["git", "remote", "add", "origin", "git@gitlab.com:acme/chart.git"], root)
    for command in ("ci", "docker", "k8s"):
        result = CliRunner().invoke(app, [command, "init", "-y", "-d", str(root)])
        assert result.exit_code == 0, result.output
    _sh(["git", "add", "-A"], root)
    _sh(["git", "-c", "user.name=quoll", "-c", "user.email=quoll@example.com", "commit", "-qm", "init"], root)

    run = subprocess.run([*_gitlab_ci_local(), "--job", "chart"], cwd=root, capture_output=True, text=True,
                         timeout=900)
    output = run.stdout + run.stderr
    assert run.returncode == 0, output[-6000:]
    assert "Valid: 3, Invalid: 0" in output and " PASS  chart" in output, output[-3000:]
