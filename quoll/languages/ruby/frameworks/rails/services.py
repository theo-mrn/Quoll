from __future__ import annotations

from typing import Dict


def service_env(service: str, host: str, database: str) -> Dict[str, str]:
    """Rails picks its adapter from the DATABASE_URL scheme: mysql2:// for MySQL."""
    if service == "mysql":
        return {"DATABASE_URL": f"mysql2://root:root@{host}:3306/{database}"}
    return {}
