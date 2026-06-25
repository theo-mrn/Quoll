from __future__ import annotations

from typing import Dict


def service_env(service: str, host: str, database: str) -> Dict[str, str]:
    """Spring Boot binds SPRING_* variables to its datasource, Redis and MongoDB properties."""
    if service == "postgres":
        return {
            "SPRING_DATASOURCE_URL": f"jdbc:postgresql://{host}:5432/{database}",
            "SPRING_DATASOURCE_USERNAME": "app",
            "SPRING_DATASOURCE_PASSWORD": "app",
        }
    if service == "mysql":
        return {
            "SPRING_DATASOURCE_URL": f"jdbc:mysql://{host}:3306/{database}",
            "SPRING_DATASOURCE_USERNAME": "root",
            "SPRING_DATASOURCE_PASSWORD": "root",
        }
    if service == "redis":
        return {"SPRING_DATA_REDIS_HOST": host}
    if service == "mongodb":
        return {"SPRING_DATA_MONGODB_URI": f"mongodb://{host}:27017/{database}"}
    return {}
