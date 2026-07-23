from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Union

from quoll.platforms.base import Platform, PlatformAPI, Remote

if TYPE_CHECKING:
    from quoll.cd.config import CDConfig
    from quoll.ci.config import CIConfig
    from quoll.files import PlannedFile
    from quoll.workspace import Delivery, Repo


class GitLab(Platform):
    name = "gitlab"
    label = "GitLab"
    secrets_label = "CI/CD variables"
    registries = ("gitlab", "dockerhub")
    schedules_via_api = True

    def ci_files(self, project_dir: Path, cfg: Union[CIConfig, Repo]) -> List[PlannedFile]:
        from quoll.platforms.gitlab import ci

        return ci.plan(project_dir, cfg)

    def cd_files(self, project_dir: Path, cfg: Union[CDConfig, List[Delivery]]) -> List[PlannedFile]:
        from quoll.platforms.gitlab import cd

        return cd.plan(project_dir, cfg)

    def default_image(self, remote: Optional[Remote], registry: str, fallback_name: str, member: str = "") -> str:
        path = (remote.path if remote else f"your-group/{fallback_name}").lower()
        if registry == "dockerhub":
            # Docker Hub repositories have a single namespace level.
            parts = path.split("/")
            return f"{parts[0]}/{parts[-1]}" + (f"-{member}" if member else "")
        if member:
            # The project's registry holds one image per member: registry.gitlab.com/group/project/<member>.
            path += f"/{member}"
        # gitlab.com serves its registry on registry.gitlab.com; self-managed instances usually on registry.<host>.
        host = remote.host if remote else "gitlab.com"
        return f"registry.{host}/{path}"

    def registry_secrets(self, registry: str) -> List[str]:
        return ["DOCKERHUB_USERNAME", "DOCKERHUB_TOKEN"] if registry == "dockerhub" else []

    def merge_gate(self) -> str:
        return "Protect the branch with 'Pipelines must succeed' (Settings > Merge requests)"

    def api(self, host: Optional[str] = None) -> PlatformAPI:
        from quoll.platforms.gitlab.api import GitLabAPI

        return GitLabAPI(f"https://{host}" if host else None)
