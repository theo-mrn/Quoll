from __future__ import annotations

import re

from quoll.languages.base import Detection
from quoll.project import Project
from quoll.services import detect_services

DOTNET_DEFAULT = "10.0"
DOTNET_LTS = ("8.0", "10.0")

# NuGet packages revealing a backing service.
_SERVICE_PACKAGES = {
    "postgres": ("Npgsql",),
    "mysql": ("MySqlConnector", "MySql.Data", "Pomelo.EntityFrameworkCore.MySql"),
    "redis": ("StackExchange.Redis",),
    "mongodb": ("MongoDB.Driver",),
}
_TEST_MARKERS = ("Microsoft.NET.Test.Sdk", "<IsTestProject>true", "xunit", "NUnit", "MSTest")


def detect(project: Project) -> Detection:
    det = Detection(package_manager="dotnet", lint_tools=["dotnet-format"])
    projects = "\n".join(p.read_text() for p in project.glob("**/*.csproj", "**/*.fsproj", "**/*.vbproj"))

    locked = project.glob_any("**/packages.lock.json")
    det.lockfile = "packages.lock.json" if locked else ""
    det.install = "dotnet restore --locked-mode" if locked else "dotnet restore"
    # setup-dotnet can only cache NuGet packages keyed on lock files.
    det.cache = locked

    if project.exists("global.json"):
        det.version_file = "global.json"
        global_json = project.read_json("global.json")
        sdk = global_json.get("sdk", {}) if isinstance(global_json, dict) else {}
        m = re.search(r"(\d+\.\d+)", str(sdk.get("version", "")))
        det.version = m.group(1) if m else DOTNET_DEFAULT
    else:
        frameworks = [int(v) for v in re.findall(r"net(\d+)\.0", projects)]
        det.version = f"{max(frameworks)}.0" if frameworks else DOTNET_DEFAULT
    low = float(det.version)
    det.matrix_versions = [v for v in DOTNET_LTS if float(v) >= low] or [det.version]

    if any(marker in projects for marker in _TEST_MARKERS):
        det.test_runner = "dotnet"
        # Thresholds need coverlet.msbuild; the default coverlet.collector only reports.
        det.coverage = "coverlet.msbuild" in projects
    else:
        det.warnings.append("No test project found (Microsoft.NET.Test.Sdk) — the test job is disabled.")
    found = [p for packages in _SERVICE_PACKAGES.values() for p in packages if f'"{p}' in projects]
    det.services = detect_services(found, _SERVICE_PACKAGES)
    det.build_command = "dotnet build --no-restore --configuration Release"
    return det
