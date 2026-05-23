from __future__ import annotations

import re

from quoll.languages.base import Detection
from quoll.project import Project
from quoll.services import detect_services

# Modules revealing a backing service.
_SERVICE_MODULES = {
    "postgres": ("github.com/lib/pq", "github.com/jackc/pgx", "gorm.io/driver/postgres"),
    "mysql": ("github.com/go-sql-driver/mysql", "gorm.io/driver/mysql"),
    "redis": ("github.com/redis/go-redis", "github.com/go-redis/redis", "github.com/gomodule/redigo"),
    "mongodb": ("go.mongodb.org/mongo-driver",),
}


def detect(project: Project) -> Detection:
    det = Detection(package_manager="go", install="go mod download", version_file="go.mod")
    det.lockfile = "go.sum" if project.exists("go.sum") else ""
    det.cache = bool(det.lockfile)
    m = re.search(r"^go\s+(\d+\.\d+)", project.read_text("go.mod"), re.M)
    det.version = m.group(1) if m else "stable"
    det.matrix_versions = ["oldstable", "stable"]
    det.lint_tools = ["gofmt", "vet", "golangci-lint"]
    det.test_runner = "go"
    det.build_command = "go build ./..."
    go_mod = project.read_text("go.mod")
    det.services = detect_services([m for ms in _SERVICE_MODULES.values() for m in ms if m in go_mod], _SERVICE_MODULES)
    return det
