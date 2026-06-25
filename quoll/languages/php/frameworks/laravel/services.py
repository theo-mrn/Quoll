from __future__ import annotations

from typing import Dict

from quoll.services import SERVICES

_CONNECTIONS = {"postgres": "pgsql", "mysql": "mysql"}


def service_env(service: str, host: str, database: str) -> Dict[str, str]:
    """Laravel reads its database and Redis settings from DB_* and REDIS_* rather than URLs."""
    if service in _CONNECTIONS:
        user = "root" if service == "mysql" else "app"
        password = "root" if service == "mysql" else "app"
        return {
            "DB_CONNECTION": _CONNECTIONS[service],
            "DB_HOST": host,
            "DB_PORT": str(SERVICES[service].port),
            "DB_DATABASE": database,
            "DB_USERNAME": user,
            "DB_PASSWORD": password,
        }
    if service == "redis":
        return {"REDIS_HOST": host}
    return {}
