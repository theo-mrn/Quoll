"""Backing services (databases, caches) an app needs: containers for CI tests and for compose.yaml.

Languages detect which ones a project uses (see `detect_services`); this module knows how to run them and
which environment variables point an app at them. Credentials are throwaway: these containers only serve
tests and local development.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Union

DATABASE = "app"


@dataclass(frozen=True)
class Service:
    name: str
    image: str
    port: int
    env: Dict[str, str]
    # Shell command that succeeds once the service accepts connections.
    health: str
    # Where the container keeps its data (a named volume in compose.yaml).
    data_dir: str
    # Environment variables pointing an app at the service on `host`, using `database` (a name of its own).
    app_env: Callable[[str, str], Dict[str, str]]


def _postgres(host: str, database: str) -> Dict[str, str]:
    url = f"postgresql://{DATABASE}:{DATABASE}@{host}:5432/{database}"
    # The PG* variables are read by libpq-based clients (psycopg, pg, rails...) without any configuration.
    return {
        "DATABASE_URL": url,
        "PGHOST": host,
        "PGPORT": "5432",
        "PGUSER": DATABASE,
        "PGPASSWORD": DATABASE,
        "PGDATABASE": database,
    }


def _mysql(host: str, database: str) -> Dict[str, str]:
    # root, so test runners can create their test databases (Django, Rails...).
    return {"DATABASE_URL": f"mysql://root:root@{host}:3306/{database}"}


SERVICES: Dict[str, Service] = {
    s.name: s
    for s in (
        Service(
            name="postgres",
            image="postgres:17-alpine",
            port=5432,
            env={"POSTGRES_USER": DATABASE, "POSTGRES_PASSWORD": DATABASE, "POSTGRES_DB": DATABASE},
            health=f"pg_isready -U {DATABASE} -d {DATABASE}",
            data_dir="/var/lib/postgresql/data",
            app_env=_postgres,
        ),
        Service(
            name="mysql",
            image="mysql:8.4",
            port=3306,
            env={"MYSQL_ROOT_PASSWORD": "root", "MYSQL_DATABASE": DATABASE},
            health="mysqladmin ping -h 127.0.0.1 -uroot -proot",
            data_dir="/var/lib/mysql",
            app_env=_mysql,
        ),
        Service(
            name="redis",
            image="redis:7-alpine",
            port=6379,
            env={},
            health="redis-cli ping",
            data_dir="/data",
            app_env=lambda host, database: {"REDIS_URL": f"redis://{host}:6379"},
        ),
        Service(
            name="mongodb",
            image="mongo:8",
            port=27017,
            env={},
            health="mongosh --quiet --eval 'db.adminCommand({ping: 1})'",
            data_dir="/data/db",
            app_env=lambda host, database: {"MONGODB_URI": f"mongodb://{host}:27017/{database}"},
        ),
    )
}

# Signature of the language/framework hooks adding their own variables (Laravel's DB_*, Spring's datasource...):
# (service, host, database) -> variables.
ServiceEnv = Callable[[str, str, str], Dict[str, str]]


def no_service_env(service: str, host: str, database: str) -> Dict[str, str]:
    return {}


def detect_services(dependencies: Iterable[str], packages: Mapping[str, Iterable[str]]) -> List[str]:
    """Services whose client packages appear in `dependencies`, in catalog order."""
    names = {d.lower() for d in dependencies}
    return [service for service in SERVICES if any(p.lower() in names for p in packages.get(service, ()))]


def environment(
    services: Iterable[str], host: Union[str, Callable[[str], str]], *hooks: ServiceEnv, database: str = DATABASE
) -> Dict[str, str]:
    """Variables pointing an app at `services`, reachable on `host` (or `host(service)`), using its `database`.

    Later hooks override earlier values.
    """
    env: Dict[str, str] = {}
    for name in services:
        address = host(name) if callable(host) else host
        env.update(SERVICES[name].app_env(address, database))
        for hook in hooks:
            env.update(hook(name, address, database))
    return env
