from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Union

from quoll.platforms.base import Platform, PlatformAPI, Remote

if TYPE_CHECKING:
    from quoll.cd.config import CDConfig
    from quoll.ci.config import CIConfig
    from quoll.files import PlannedFile
    from quoll.workspace import Delivery, Repo


# The aggregate job of ci.yml to mark as required in branch protection: one stable name,
# whatever jobs or matrix entries the workflow contains.
GATE_CHECK = "CI result"


class GitHub(Platform):
    name = "github"
    label = "GitHub"
    secrets_label = "secrets"
    registries = ("ghcr", "dockerhub")
    required_checks = (GATE_CHECK,)

    def ci_files(self, project_dir: Path, cfg: Union[CIConfig, Repo]) -> List[PlannedFile]:
        from quoll.platforms.github import ci

        return ci.plan(project_dir, cfg)

    def cd_files(self, project_dir: Path, cfg: Union[CDConfig, List[Delivery]]) -> List[PlannedFile]:
        from quoll.platforms.github import cd

        return cd.plan(project_dir, cfg)

    def default_image(self, remote: Optional[Remote], registry: str, fallback_name: str, member: str = "") -> str:
        path = (remote.path if remote else f"your-org/{fallback_name}").lower()
        if member:
            path += f"-{member}"
        return f"ghcr.io/{path}" if registry == "ghcr" else path

    def registry_secrets(self, registry: str) -> List[str]:
        return ["DOCKERHUB_USERNAME", "DOCKERHUB_TOKEN"] if registry == "dockerhub" else []

    def merge_gate(self) -> str:
        return f"Required status check for branch protection: {GATE_CHECK}"

    def api(self, host: Optional[str] = None) -> PlatformAPI:
        from quoll.platforms.github.api import GitHubAPI

        return GitHubAPI()
