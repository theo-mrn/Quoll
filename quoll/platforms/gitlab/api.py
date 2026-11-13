"""GitLab REST API (gitlab.com or a self-managed instance): projects, CI/CD variables, protected branches."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence
from urllib.parse import quote

import httpx

from quoll.config.settings import settings
from quoll.platforms.base import PlatformAPI, PlatformError, Repo

_ERROR_HINTS = {
    401: "The token is invalid or expired (QUOLL_GITLAB_TOKEN, `glab auth login`, or ~/.config/quoll/config.toml).",
    403: "The token lacks permissions: it needs the 'api' scope and the Maintainer role on the project.",
    404: "Project or group not found (or not visible to this token).",
}
# Identifies the pipeline schedule quoll manages among the project's others.
SCHEDULE_DESCRIPTION = "quoll: security scans"
# Access levels: https://docs.gitlab.com/api/protected_branches/
_NO_ONE = 0
_MAINTAINER = 40


class GitLabError(PlatformError):
    pass


def gitlab_client(base_url: Optional[str] = None) -> httpx.Client:
    return httpx.Client(
        base_url=f"{(base_url or settings.gitlab_url).rstrip('/')}/api/v4",
        headers={"PRIVATE-TOKEN": settings.gitlab_token},
        timeout=30,
    )


class GitLabAPI(PlatformAPI):
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = base_url

    def create_repo(self, name: str, private: bool = True) -> Repo:
        with gitlab_client(self.base_url) as client:
            payload: Dict[str, object] = {
                "name": name,
                "path": name,
                "visibility": "private" if private else "public",
                "description": "Scaffolded by quoll",
                "initialize_with_readme": False,
            }
            if settings.gitlab_group:
                response = client.get(f"/groups/{_id(settings.gitlab_group)}")
                _raise_for_status(response, f"find the group {settings.gitlab_group}")
                payload["namespace_id"] = response.json()["id"]
            response = client.post("/projects", json=payload)
            _raise_for_status(response, "create the project")
            data = response.json()
            return Repo(
                path=data["path_with_namespace"], clone_url=data["http_url_to_repo"], web_url=data["web_url"]
            )

    def set_secrets(self, repo: str, secrets: Dict[str, str]) -> None:
        """Create or update CI/CD variables, masked whenever GitLab accepts to mask the value."""
        repo = self._full_path(repo)
        with gitlab_client(self.base_url) as client:
            for key, value in secrets.items():
                payload = {"key": key, "value": value, "masked": _maskable(value), "protected": False}
                response = client.put(f"/projects/{_id(repo)}/variables/{key}", json=payload)
                if response.status_code == 404:
                    response = client.post(f"/projects/{_id(repo)}/variables", json=payload)
                _raise_for_status(response, f"save the variable {key}")

    def ensure_schedule(self, repo: str, branch: str, cron: str) -> bool:
        """The pipeline schedule quoll owns (found by its description), created or updated."""
        repo = self._full_path(repo)
        payload = {"description": SCHEDULE_DESCRIPTION, "ref": branch, "cron": cron, "cron_timezone": "UTC",
                   "active": True}
        schedules = f"/projects/{_id(repo)}/pipeline_schedules"
        with gitlab_client(self.base_url) as client:
            response = client.get(schedules, params={"per_page": 100})
            _raise_for_status(response, "list the pipeline schedules")
            existing = next((s for s in response.json() if s.get("description") == SCHEDULE_DESCRIPTION), None)
            if existing:
                response = client.put(f"{schedules}/{existing['id']}", json=payload)
            else:
                response = client.post(schedules, json=payload)
            _raise_for_status(response, "save the pipeline schedule")
        return True

    def protect_branch(
        self, repo: str, branch: str, required_checks: Sequence[str] = (), required_reviews: int = 0
    ) -> List[str]:
        """No direct pushes, merge requests only once the pipeline passed, linear history."""
        repo = self._full_path(repo)
        warnings: List[str] = []
        project = f"/projects/{_id(repo)}"
        with gitlab_client(self.base_url) as client:
            # Protection settings can't be changed in place: unprotect, then protect again.
            client.delete(f"{project}/protected_branches/{quote(branch, safe='')}")
            response = client.post(
                f"{project}/protected_branches",
                json={
                    "name": branch,
                    "push_access_level": _NO_ONE,
                    "merge_access_level": _MAINTAINER,
                    "allow_force_push": False,
                },
            )
            _raise_for_status(response, f"protect the branch {branch}")
            response = client.put(
                project,
                json={
                    "only_allow_merge_if_pipeline_succeeds": True,
                    "only_allow_merge_if_all_discussions_are_resolved": True,
                    "merge_method": "ff",
                },
            )
            _raise_for_status(response, "require a successful pipeline to merge")
            if required_reviews:
                # Approval rules are a GitLab Premium feature.
                response = client.post(
                    f"{project}/approval_rules",
                    json={"name": "quoll", "approvals_required": required_reviews},
                )
                if response.is_error:
                    warnings.append(
                        f"required approvals not set (GitLab {response.status_code}): they need GitLab Premium"
                    )
        return warnings

    def _full_path(self, repo: str) -> str:
        """group/project; a bare name belongs to the configured group, or to the authenticated user."""
        if "/" in repo:
            return repo
        if settings.gitlab_group:
            return f"{settings.gitlab_group}/{repo}"
        with gitlab_client(self.base_url) as client:
            response = client.get("/user")
            _raise_for_status(response, "read the authenticated user")
            return f"{response.json()['username']}/{repo}"


def _id(path: str) -> str:
    """Projects and groups are addressed by their URL-encoded full path."""
    return quote(path, safe="")


def _maskable(value: str) -> bool:
    # https://docs.gitlab.com/ci/variables/#mask-a-cicd-variable
    return len(value) >= 8 and bool(re.fullmatch(r"[A-Za-z0-9+/=@:.~_-]+", value))


def _raise_for_status(response: httpx.Response, action: str) -> None:
    if response.is_error:
        hint = _ERROR_HINTS.get(response.status_code, "")
        msg = f"GitLab {response.status_code} while trying to {action}."
        if hint:
            msg += f" {hint}"
        raise GitLabError(msg)
