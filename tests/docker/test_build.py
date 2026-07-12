"""Build and run real applications with the generated Dockerfiles.

Slow (several minutes, downloads images and dependencies), so opt-in:

    QUOLL_DOCKER_TESTS=build pytest tests/docker/test_build.py
"""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, NamedTuple, Optional

import pytest
from typer.testing import CliRunner

from quoll.docker.config import load_config
from quoll.main import app

pytestmark = pytest.mark.skipif(
    os.environ.get("QUOLL_DOCKER_TESTS") != "build", reason="set QUOLL_DOCKER_TESTS=build to build real images"
)


def _write(root: Path, files: Dict[str, object]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=2) if isinstance(content, (dict, list)) else str(content))


def _sh(cmd: list, cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _in_container(image: str, script: str, root: Path) -> None:
    """Run `script` in `image` with the project directory mounted at /work."""
    _sh(["docker", "run", "--rm", "-v", f"{root}:/work", "-w", "/work", image, "sh", "-c", script], root)


# --------------------------------------------------------------------------- apps


def fastapi_uv(root: Path) -> None:
    _write(root, {
        "pyproject.toml": '[project]\nname = "api"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
        'dependencies = ["fastapi", "uvicorn"]\n',
        ".python-version": "3.13\n",
        "app/__init__.py": "",
        "app/main.py": 'from fastapi import FastAPI\n\napp = FastAPI()\n\n\n'
        '@app.get("/")\ndef root():\n    return {"ok": True}\n',
    })
    _sh(["uv", "lock"], root)


def flask_pip(root: Path) -> None:
    _write(root, {
        "requirements.txt": "flask\ngunicorn\n",
        "app.py": 'from flask import Flask\n\napp = Flask(__name__)\n\n\n@app.get("/")\ndef root():\n    return "ok"\n',
    })


def django_poetry(root: Path) -> None:
    _write(root, {
        "pyproject.toml": '[tool.poetry]\npackage-mode = false\n\n[tool.poetry.dependencies]\npython = "^3.12"\n'
        'django = "^5.2"\ngunicorn = "*"\n',
        "manage.py": "import os, sys\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', 'site_app.settings')\n"
        "from django.core.management import execute_from_command_line\nexecute_from_command_line(sys.argv)\n",
        "site_app/__init__.py": "",
        "site_app/settings.py": 'SECRET_KEY = "test"\nDEBUG = False\nALLOWED_HOSTS = ["*"]\n'
        'ROOT_URLCONF = "site_app.urls"\nINSTALLED_APPS = []\nMIDDLEWARE = []\n',
        "site_app/urls.py": 'from django.http import HttpResponse\nfrom django.urls import path\n\n'
        'urlpatterns = [path("", lambda request: HttpResponse("ok"))]\n',
        "site_app/wsgi.py": "import os\nfrom django.core.wsgi import get_wsgi_application\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'site_app.settings')\napplication = get_wsgi_application()\n",
    })


def express_npm(root: Path) -> None:
    _write(root, {
        "package.json": {"name": "api", "scripts": {"start": "node server.js"}, "dependencies": {"express": "^5"}},
        "server.js": "const app = require('express')();\napp.get('/', (req, res) => res.send('ok'));\n"
        "app.listen(process.env.PORT, process.env.HOST);\n",
    })
    _sh(["npm", "install", "--package-lock-only", "--silent"], root)


def vite_static(root: Path) -> None:
    _write(root, {
        "package.json": {"name": "spa", "scripts": {"build": "vite build"}, "devDependencies": {"vite": "^7"}},
        "index.html": "<!doctype html><html><body><h1>ok</h1></body></html>\n",
    })
    _sh(["npm", "install", "--package-lock-only", "--silent"], root)


def nextjs_standalone(root: Path) -> None:
    _write(root, {
        "package.json": {
            "name": "site",
            "scripts": {"build": "next build", "start": "next start"},
            "dependencies": {"next": "^16", "react": "^19", "react-dom": "^19"},
        },
        "next.config.mjs": "export default { output: 'standalone' };\n",
        "app/layout.js": "export default function Layout({ children }) {\n"
        "  return <html><body>{children}</body></html>;\n}\n",
        "app/page.js": "export default function Page() {\n  return <h1>ok</h1>;\n}\n",
        "public/robots.txt": "",
    })
    _sh(["npm", "install", "--package-lock-only", "--silent"], root)


def nuxt(root: Path) -> None:
    _write(root, {
        "package.json": {"name": "site", "scripts": {"build": "nuxt build"}, "dependencies": {"nuxt": "^4"}},
        "app/app.vue": "<template><h1>ok</h1></template>\n",
    })
    _sh(["npm", "install", "--package-lock-only", "--silent"], root)


def go_app(root: Path) -> None:
    _write(root, {
        "go.mod": "module example.com/api\n\ngo 1.25\n",
        "cmd/api/main.go": 'package main\n\nimport "net/http"\n\nfunc main() {\n'
        '\thttp.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) })\n'
        '\thttp.ListenAndServe(":8080", nil)\n}\n',
    })


def rust_app(root: Path) -> None:
    _write(root, {
        "Cargo.toml": '[package]\nname = "api"\nversion = "0.1.0"\nedition = "2021"\n',
        "src/main.rs": "use std::io::{Read, Write};\nfn main() {\n"
        '    let listener = std::net::TcpListener::bind("0.0.0.0:8080").unwrap();\n'
        "    for stream in listener.incoming() {\n        let mut s = stream.unwrap();\n"
        "        let _ = s.read(&mut [0; 1024]);\n"
        '        s.write_all(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\n\\r\\nok").unwrap();\n    }\n}\n',
    })


def cpp_http(root: Path) -> None:
    _write(root, {
        "CMakeLists.txt": "cmake_minimum_required(VERSION 3.25)\nproject(api CXX)\nadd_executable(api main.cpp)\n",
        "main.cpp": "#include <netinet/in.h>\n#include <sys/socket.h>\n#include <unistd.h>\n#include <string>\n\n"
        "int main() {\n  int server = socket(AF_INET, SOCK_STREAM, 0);\n  int yes = 1;\n"
        "  setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof yes);\n"
        "  sockaddr_in addr{};\n  addr.sin_family = AF_INET;\n  addr.sin_port = htons(8080);\n"
        "  bind(server, reinterpret_cast<sockaddr*>(&addr), sizeof addr);\n  listen(server, 16);\n"
        "  const std::string reply = \"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\nConnection: close\\r\\n\\r\\nok\";\n"
        "  for (;;) {\n    int client = accept(server, nullptr, nullptr);\n    char buf[1024];\n"
        "    read(client, buf, sizeof buf);\n    write(client, reply.data(), reply.size());\n    close(client);\n"
        "  }\n}\n",
    })


def spring_boot(root: Path) -> None:
    url = "https://start.spring.io/starter.zip?type=maven-project&dependencies=web&javaVersion=21&baseDir=."
    _sh(["curl", "-fsSL", "-o", "starter.zip", url], root)
    _sh(["unzip", "-q", "starter.zip"], root)
    (root / "starter.zip").unlink()


def php_plain(root: Path) -> None:
    _write(root, {
        "composer.json": {"name": "acme/site", "require": {"php": ">=8.2", "ext-intl": "*"}},
        "public/index.php": "<?php echo 'ok';\n",
    })


def symfony(root: Path) -> None:
    _in_container("composer:2", "composer create-project symfony/skeleton . --no-interaction --quiet", root)


def laravel(root: Path) -> None:
    _in_container("composer:2", "composer create-project laravel/laravel . --no-interaction --quiet", root)


def ruby_rack(root: Path) -> None:
    _write(root, {
        "Gemfile": 'source "https://rubygems.org"\ngem "rack"\ngem "rackup"\ngem "puma"\n',
        ".ruby-version": "3.4\n",
        "config.ru": 'run ->(env) { [200, {"content-type" => "text/plain"}, ["ok"]] }\n',
    })
    _in_container("ruby:3.4", "bundle lock", root)


def rails(root: Path) -> None:
    _in_container(
        "ruby:3.4",
        "gem install rails --no-document --quiet && rails new . --skip-git --skip-test --skip-system-test --quiet",
        root,
    )


def dotnet(root: Path) -> None:
    _in_container("mcr.microsoft.com/dotnet/sdk:8.0", "dotnet new web --name Shop --output . >/dev/null", root)


def angular(root: Path) -> None:
    _sh(["npx", "-y", "@angular/cli@latest", "new", "shop", "--defaults", "--skip-git", "--skip-install",
         "--directory", "."], root)
    _sh(["npm", "install", "--package-lock-only", "--silent"], root)


def nestjs(root: Path) -> None:
    _sh(["npx", "-y", "@nestjs/cli@latest", "new", "api", "--skip-git", "--skip-install",
         "--package-manager", "npm", "--directory", "."], root)
    _sh(["npm", "install", "--package-lock-only", "--silent"], root)


def sveltekit_node(root: Path) -> None:
    _write(root, {
        "package.json": {
            "name": "site",
            "type": "module",
            "scripts": {"build": "vite build"},
            "devDependencies": {
                "@sveltejs/adapter-node": "^5",
                "@sveltejs/kit": "^2",
                "@sveltejs/vite-plugin-svelte": "^6",
                "svelte": "^5",
                "vite": "^7",
            },
        },
        "svelte.config.js": "import adapter from '@sveltejs/adapter-node';\n"
        "export default { kit: { adapter: adapter() } };\n",
        "vite.config.js": "import { sveltekit } from '@sveltejs/kit/vite';\n"
        "export default { plugins: [sveltekit()] };\n",
        "src/app.html": "<!doctype html><html><head>%sveltekit.head%</head><body>%sveltekit.body%</body></html>\n",
        "src/routes/+page.svelte": "<h1>ok</h1>\n",
    })
    _sh(["npm", "install", "--package-lock-only", "--silent"], root)


def astro_static(root: Path) -> None:
    _write(root, {
        "package.json": {"name": "site", "type": "module", "scripts": {"build": "astro build"},
                         "dependencies": {"astro": "^5"}},
        "src/pages/index.astro": "<h1>ok</h1>\n",
    })
    _sh(["npm", "install", "--package-lock-only", "--silent"], root)


def express_pnpm(root: Path) -> None:
    express_npm(root)
    (root / "package-lock.json").unlink()
    _sh(["npx", "-y", "pnpm@10", "install", "--lockfile-only", "--silent"], root)


def express_bun(root: Path) -> None:
    _write(root, {
        "package.json": {"name": "api", "scripts": {"start": "bun server.ts"}, "dependencies": {"hono": "^4"}},
        "server.ts": "import { Hono } from 'hono';\nconst app = new Hono();\napp.get('/', (c) => c.text('ok'));\n"
        "export default { port: Number(process.env.PORT), hostname: '0.0.0.0', fetch: app.fetch };\n",
    })
    _in_container("oven/bun:1", "bun install --lockfile-only", root)


def express_yarn_berry(root: Path) -> None:
    express_npm(root)
    (root / "package-lock.json").unlink()
    _write(root, {".yarnrc.yml": "nodeLinker: node-modules\n"})
    _in_container("node:24-slim", "corepack enable && yarn set version stable && yarn install --mode update-lockfile",
                  root)


def maven_plain(root: Path) -> None:
    jar_plugin = (
        "<build><plugins><plugin><artifactId>maven-jar-plugin</artifactId><version>3.4.2</version><configuration>"
        "<archive><manifest><mainClass>app.Main</mainClass></manifest></archive></configuration></plugin>"
        "</plugins></build>"
    )
    _write(root, {
        "pom.xml": "<project><modelVersion>4.0.0</modelVersion><groupId>app</groupId><artifactId>app</artifactId>"
        "<version>1.0</version><properties><maven.compiler.release>21</maven.compiler.release></properties>"
        f"{jar_plugin}</project>",
        "src/main/java/app/Main.java": "package app;\nimport com.sun.net.httpserver.HttpServer;\n"
        "import java.net.InetSocketAddress;\n"
        "public class Main { public static void main(String[] a) throws Exception {\n"
        "  var s = HttpServer.create(new InetSocketAddress(8080), 0);\n"
        '  s.createContext("/", e -> {\n'
        "    e.sendResponseHeaders(200, 2); e.getResponseBody().write(\"ok\".getBytes()); e.close();\n"
        "  });\n"
        "  s.start(); } }\n",
    })


def spring_boot_gradle_kotlin(root: Path) -> None:
    url = ("https://start.spring.io/starter.zip?type=gradle-project-kotlin&language=kotlin"
           "&dependencies=web&javaVersion=21&baseDir=.")
    _sh(["curl", "-fsSL", "-o", "starter.zip", url], root)
    _sh(["unzip", "-q", "starter.zip"], root)
    (root / "starter.zip").unlink()


class App(NamedTuple):
    create: Callable[[Path], None]
    env: Dict[str, str] = {}
    command: str = ""


APPS = {
    "fastapi-uv": App(fastapi_uv),
    "flask-pip": App(flask_pip),
    "django-poetry": App(django_poetry),
    "express-npm": App(express_npm),
    "vite-static": App(vite_static),
    "nextjs-standalone": App(nextjs_standalone),
    "nuxt": App(nuxt),
    "go": App(go_app),
    "rust": App(rust_app),
    "spring-boot": App(spring_boot),
    "php": App(php_plain),
    "symfony": App(symfony),
    "laravel": App(laravel, env={"APP_KEY": "base64:" + "A" * 43 + "="}),
    "ruby-rack": App(ruby_rack),
    "rails": App(rails, env={"SECRET_KEY_BASE": "0" * 64}),
    "dotnet": App(dotnet),
    "angular": App(angular),
    "nestjs": App(nestjs),
    "sveltekit-node": App(sveltekit_node),
    "astro-static": App(astro_static),
    "node-pnpm": App(express_pnpm),
    "node-bun": App(express_bun),
    "node-yarn-berry": App(express_yarn_berry),
    "maven": App(maven_plain),
    "spring-boot-gradle-kotlin": App(spring_boot_gradle_kotlin),
    "cpp": App(cpp_http),
}


# --------------------------------------------------------------------------- test


@pytest.mark.parametrize("name", list(APPS))
def test_image_builds_and_serves(tmp_path, name) -> None:
    spec = APPS[name]
    root = tmp_path / name
    root.mkdir()
    spec.create(root)

    args = ["docker", "init", "-y", "--force", "-d", str(root)] + (["--command", spec.command] if spec.command else [])
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    port = load_config(root).port

    tag = f"quoll-test-{name}:{uuid.uuid4().hex[:8]}"
    build = subprocess.run(["docker", "build", "-q", "-t", tag, str(root)], capture_output=True, text=True)
    assert build.returncode == 0, (root / "Dockerfile").read_text() + build.stderr[-4000:]
    try:
        env = [arg for key, value in spec.env.items() for arg in ("-e", f"{key}={value}")]
        container = subprocess.run(
            ["docker", "run", "-d", "-p", f"127.0.0.1::{port}", *env, tag], capture_output=True, text=True, check=True
        ).stdout.strip()
        try:
            host_port = subprocess.run(
                ["docker", "port", container, str(port)], capture_output=True, text=True, check=True
            ).stdout.split(":")[-1].strip()
            status = _wait_for_http(host_port)
            logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
            assert status is not None and status < 500, f"status={status}\n{logs.stdout[-3000:]}{logs.stderr[-3000:]}"
            user = subprocess.run(
                ["docker", "inspect", "--format", "{{.Config.User}}", tag], capture_output=True, text=True
            ).stdout.strip()
            # nginx-unprivileged sets its user in the base image.
            assert user not in ("", "root", "0") or load_config(root).static
        finally:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)
    finally:
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)


def _wait_for_http(port: str, timeout: float = 90) -> Optional[int]:
    """Status of GET / once the server answers (redirects are not followed)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=5)
        try:
            connection.request("GET", "/")
            return connection.getresponse().status
        except (ConnectionError, OSError, http.client.HTTPException):
            time.sleep(1)
        finally:
            connection.close()
    return None


def test_compose_runs_the_app_with_its_database(tmp_path) -> None:
    """The generated compose.yaml starts Postgres, waits for it, and points the app at it."""
    root = tmp_path / "with-db"
    root.mkdir()
    _write(root, {
        "requirements.txt": "fastapi\nuvicorn\npsycopg[binary]\n",
        "main.py": "import os\n\nimport psycopg\nfrom fastapi import FastAPI\n\napp = FastAPI()\n\n\n"
        '@app.get("/")\ndef root():\n    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:\n'
        '        return {"db": conn.execute("select 1").fetchone()[0]}\n',
    })
    result = CliRunner().invoke(app, ["docker", "init", "-y", "-d", str(root)])
    assert result.exit_code == 0, result.output
    assert load_config(root).services == ["postgres"]

    project = f"quoll-test-{uuid.uuid4().hex[:8]}"
    compose = ["docker", "compose", "--project-name", project]
    try:
        up = subprocess.run([*compose, "up", "--detach", "--build", "--wait"], cwd=root, capture_output=True, text=True)
        assert up.returncode == 0, up.stderr[-4000:]
        port = subprocess.run(
            [*compose, "port", "app", "8000"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.split(":")[-1].strip()
        assert _wait_for_http(port) == 200
        connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=5)
        connection.request("GET", "/")
        assert json.loads(connection.getresponse().read()) == {"db": 1}
    finally:
        subprocess.run([*compose, "down", "--volumes", "--rmi", "local"], cwd=root, capture_output=True)


_DATABASE_APPS = {
    "postgres": (
        "psycopg[binary]",
        "import psycopg\n",
        'psycopg.connect(os.environ["DATABASE_URL"])',
        "select current_database()",
        ["psql", "-U", "app", "-d", "app", "-c", "DROP DATABASE users"],
    ),
    "mysql": (
        "pymysql",
        "from urllib.parse import urlparse\n\nimport pymysql\n",
        '(lambda u: pymysql.connect(host=u.hostname, user=u.username, password=u.password, '
        'database=u.path[1:]))(urlparse(os.environ["DATABASE_URL"]))',
        "select database()",
        ["mysql", "-uroot", "-proot", "-e", "DROP DATABASE users"],
    ),
}


@pytest.mark.parametrize("database", list(_DATABASE_APPS))
def test_workspace_compose_gives_each_service_its_database(tmp_path, database) -> None:
    """A workspace's compose.yaml: one database server, a database per service, each service reaching the other."""
    package, imports, connect, query, drop_users = _DATABASE_APPS[database]
    root = tmp_path / "platform"
    app_py = (
        f"import os\n\n{imports}from fastapi import FastAPI\n\napp = FastAPI()\n\n\n"
        f'@app.get("/")\ndef root():\n    conn = {connect}\n'
        f'    with conn.cursor() as cursor:\n        cursor.execute("{query}")\n'
        '        db = cursor.fetchone()[0]\n    conn.close()\n'
        '    return {"db": db, "peers": sorted(k for k in os.environ if k.endswith("_URL") and k != "DATABASE_URL")}\n'
    )
    for name in ("orders", "users"):
        _write(root / "services" / name, {"requirements.txt": f"fastapi\nuvicorn\n{package}\n", "main.py": app_py})
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    for args in (["ci", "init", "-y"], ["docker", "init", "-y"]):
        result = CliRunner().invoke(app, [*args, "-d", str(root)])
        assert result.exit_code == 0, result.output

    project = f"quoll-test-{uuid.uuid4().hex[:8]}"
    compose = ["docker", "compose", "--project-name", project]
    try:
        up = subprocess.run([*compose, "up", "--detach", "--build", "--wait"], cwd=root, capture_output=True, text=True)
        assert up.returncode == 0, up.stderr[-4000:]
        for service, peer in (("orders", "USERS_URL"), ("users", "ORDERS_URL")):
            port = subprocess.run(
                [*compose, "port", service, "8000"], cwd=root, capture_output=True, text=True, check=True
            ).stdout.split(":")[-1].strip()
            assert _wait_for_http(port) == 200
            connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=5)
            connection.request("GET", "/")
            assert json.loads(connection.getresponse().read()) == {"db": service, "peers": [peer]}

        # The volume exists, a database is missing (a service added later): the next `up` creates it.
        subprocess.run([*compose, "stop", "users"], cwd=root, capture_output=True, check=True)
        drop = [*compose, "exec", "-T", database, *drop_users]
        subprocess.run(drop, cwd=root, capture_output=True, check=True)
        up = subprocess.run([*compose, "up", "--detach", "--wait"], cwd=root, capture_output=True, text=True)
        assert up.returncode == 0, up.stderr[-4000:]
        port = subprocess.run(
            [*compose, "port", "users", "8000"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.split(":")[-1].strip()
        assert _wait_for_http(port) == 200
    finally:
        subprocess.run([*compose, "down", "--volumes", "--rmi", "local"], cwd=root, capture_output=True)
