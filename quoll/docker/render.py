"""Turn a DockerConfig into a Dockerfile and a .dockerignore."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from quoll.docker.config import DockerConfig
from quoll.files import PlannedFile, header, planned
from quoll.project import Project
from quoll.services import DATABASE, SERVICES
from quoll.yaml_dump import dump

DOCKERFILE = Path("Dockerfile")
DOCKERIGNORE = Path(".dockerignore")
COMPOSE = Path("compose.yaml")
# A compose file under another name is the project's own: quoll doesn't add a second one.
_OTHER_COMPOSE_FILES = ("compose.yml", "docker-compose.yml", "docker-compose.yaml")

# BuildKit parser directive: must be the very first line.
_SYNTAX = "# syntax=docker/dockerfile:1\n"

# Kept out of every build context: VCS, CI, editors, the Docker files themselves.
_COMMON_IGNORE = [
    ".git",
    ".github",
    ".gitignore",
    ".dockerignore",
    "Dockerfile",
    "compose*.y*ml",
    "docker-compose*.y*ml",
    ".idea",
    ".vscode",
    "**/.DS_Store",
]


def render_dockerfile(project_dir: Path, cfg: DockerConfig) -> str:
    return _SYNTAX + header("docker") + "\n" + cfg.image.render(Project(project_dir), cfg)


def render_dockerignore(cfg: DockerConfig) -> str:
    return header("docker") + "\n".join([*_COMMON_IGNORE, *cfg.image.dockerignore(cfg)]) + "\n"


def render_compose(cfg: DockerConfig) -> str:
    """The app built from the Dockerfile, plus its services with healthchecks and persistent volumes."""
    app: Dict[str, Any] = {"build": ".", "ports": [f"{cfg.port}:{cfg.port}"]}
    # Secrets (APP_KEY, SECRET_KEY_BASE...) stay in an untracked .env.
    app["env_file"] = [{"path": ".env", "required": False}]
    env = cfg.service_environment(lambda service: service)
    if env:
        app["environment"] = env
    if cfg.services:
        app["depends_on"] = {name: {"condition": "service_healthy"} for name in cfg.services}

    doc: Dict[str, Any] = {"services": {"app": app}}
    for name in cfg.services:
        service = SERVICES[name]
        container: Dict[str, Any] = {"image": service.image}
        if service.env:
            container["environment"] = service.env
        container["volumes"] = [f"{name}-data:{service.data_dir}"]
        container["healthcheck"] = {"test": ["CMD-SHELL", service.health], "interval": "5s", "retries": 20}
        doc["services"][name] = container
    if cfg.services:
        doc["volumes"] = {f"{name}-data": None for name in cfg.services}
    return header("docker") + "\n" + dump(doc, spaced=("services",))


# Creates the missing databases of a workspace's projects in their shared instance, at every `up`: a project added
# later gets its own even though the volume already exists (the image's init scripts only run on an empty one).
_CREATE_DATABASES = {
    "postgres": (
        {"PGHOST": "postgres", "PGUSER": DATABASE, "PGPASSWORD": DATABASE, "PGDATABASE": DATABASE},
        """psql -tAc "SELECT 1 FROM pg_database WHERE datname = '{db}'" | grep -q 1 """
        """|| psql -c 'CREATE DATABASE {db}'""",
    ),
    "mysql": ({}, 'mysql -h mysql -uroot -proot -e "CREATE DATABASE IF NOT EXISTS {db}"'),
}
_CREATE_SCRIPT = "/quoll/create-databases.sh"


def database_name(member: str) -> str:
    return member.replace("-", "_")


def render_workspace_compose(members: List[Tuple[str, str, DockerConfig]]) -> str:
    """compose.yaml at a workspace's root: every project (name, directory, [docker]) on one network, each reaching
    the others at http://<name>:<port> (<NAME>_URL), and one instance of each backing service with a database per
    project."""
    doc: Dict[str, Any] = {"services": {}}
    used_ports: set = set()
    backing = [s for s in SERVICES if any(s in cfg.services for _, _, cfg in members)]
    for name, directory, cfg in members:
        port = cfg.port
        while port in used_ports:  # two projects listening on 3000: the second gets 3001 on the host
            port += 1
        used_ports.add(port)
        app: Dict[str, Any] = {"build": f"./{directory}", "ports": [f"{port}:{cfg.port}"]}
        app["env_file"] = [{"path": f"./{directory}/.env", "required": False}]
        env = cfg.service_environment(lambda service: service, database=database_name(name))
        for other, _, other_cfg in members:
            if other != name:
                env[f"{other.upper().replace('-', '_')}_URL"] = f"http://{other}:{other_cfg.port}"
        if env:
            app["environment"] = env
        depends_on: Dict[str, Any] = {s: {"condition": "service_healthy"} for s in cfg.services}
        # nginx resolves the projects it forwards to when it starts.
        for other, _, _ in members:
            if f"{other.upper().replace('-', '_')}_URL" in cfg.proxy.values():
                depends_on[other] = {"condition": "service_started"}
        if depends_on:
            app["depends_on"] = depends_on
        doc["services"][name] = app

    configs: Dict[str, Any] = {}
    for service_name in backing:
        service = SERVICES[service_name]
        container: Dict[str, Any] = {"image": service.image}
        if service.env:
            container["environment"] = service.env
        container["volumes"] = [f"{service_name}-data:{service.data_dir}"]
        container["healthcheck"] = {"test": ["CMD-SHELL", service.health], "interval": "5s", "retries": 20}
        doc["services"][service_name] = container
        if service_name in _CREATE_DATABASES:
            env, statement = _CREATE_DATABASES[service_name]
            users = [n for n, _, cfg in members if service_name in cfg.services]
            create: Dict[str, Any] = {"image": service.image}
            if env:
                create["environment"] = env
            script = "\n".join(statement.format(db=database_name(n)) for n in users)
            configs[f"{service_name}-databases"] = {"content": script + "\n"}
            create["configs"] = [{"source": f"{service_name}-databases", "target": _CREATE_SCRIPT}]
            create["command"] = ["sh", "-e", _CREATE_SCRIPT]
            create["depends_on"] = {service_name: {"condition": "service_healthy"}}
            doc["services"][f"{service_name}-databases"] = create
            for n in users:
                doc["services"][n]["depends_on"][f"{service_name}-databases"] = {
                    "condition": "service_completed_successfully"
                }
    if backing:
        doc["volumes"] = {f"{name}-data": None for name in backing}
    if configs:
        doc["configs"] = configs
    return header("docker") + "\n" + dump(doc, spaced=("services",))


def plan_workspace(root: Path, members: List[Tuple[str, str, DockerConfig]]) -> List[PlannedFile]:
    """The workspace's compose.yaml (none when the root has a compose file of its own)."""
    if any((root / name).exists() for name in _OTHER_COMPOSE_FILES):
        return []
    return [planned(root, COMPOSE, render_workspace_compose(members))]


def plan(project_dir: Path, cfg: DockerConfig) -> List[PlannedFile]:
    files = [
        planned(project_dir, DOCKERFILE, render_dockerfile(project_dir, cfg)),
        planned(project_dir, DOCKERIGNORE, render_dockerignore(cfg)),
    ]
    if not any((project_dir / name).exists() for name in _OTHER_COMPOSE_FILES):
        files.append(planned(project_dir, COMPOSE, render_compose(cfg)))
    return files
