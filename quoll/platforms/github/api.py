"""GitHub REST API: repositories, Actions secrets, branch protection."""
from __future__ import annotations

import base64
from typing import Dict, List, Sequence, Tuple

import httpx

from quoll.config.settings import settings
from quoll.platforms.base import PlatformAPI, PlatformError, Repo

GITHUB_API = "https://api.github.com"

_ERROR_HINTS = {
    401: "The token is invalid or expired (QUOLL_GITHUB_TOKEN, `gh auth login`, or ~/.config/quoll/config.toml).",
    403: "The token lacks permissions: it needs the 'repo' scope.",
    422: "The repository may already exist on GitHub.",
}


class GitHubError(PlatformError):
    pass


def github_client() -> httpx.Client:
    return httpx.Client(
        base_url=GITHUB_API,
        headers={
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )


class GitHubAPI(PlatformAPI):
    def create_repo(self, name: str, private: bool = True) -> Repo:
        with github_client() as client:
            endpoint = f"/orgs/{settings.github_org}/repos" if settings.github_org else "/user/repos"
            response = client.post(
                endpoint,
                json={"name": name, "private": private, "auto_init": False, "description": "Scaffolded by quoll"},
            )
            _raise_for_status(response, "create the repository")
            data = response.json()
            return Repo(path=data.get("full_name", name), clone_url=data["clone_url"], web_url=data.get("html_url", ""))

    def set_secrets(self, repo: str, secrets: Dict[str, str]) -> None:
        """Encrypt and upload Actions secrets."""
        repo = self._full_path(repo)
        with github_client() as client:
            key_id, public_key = _repo_public_key(client, repo)
            for name, value in secrets.items():
                response = client.put(
                    f"/repos/{repo}/actions/secrets/{name}",
                    json={"encrypted_value": _encrypt_secret(public_key, value), "key_id": key_id},
                )
                _raise_for_status(response, f"save the secret {name}")

    def protect_branch(
        self, repo: str, branch: str, required_checks: Sequence[str] = (), required_reviews: int = 0
    ) -> List[str]:
        repo = self._full_path(repo)
        # Changes go through a pull request; approvals are on top (GitHub doesn't let authors approve their own:
        # one required approval would lock a project with a single developer out of its default branch).
        reviews = {"required_approving_review_count": required_reviews, "dismiss_stale_reviews": True}
        with github_client() as client:
            response = client.put(
                f"/repos/{repo}/branches/{branch}/protection",
                json={
                    "required_status_checks": {"strict": True, "contexts": list(required_checks)},
                    "enforce_admins": True,
                    "required_pull_request_reviews": reviews,
                    "restrictions": None,
                    "required_linear_history": True,
                    "allow_force_pushes": False,
                    "allow_deletions": False,
                },
            )
            if response.is_error:
                raise GitHubError(f"GitHub {response.status_code} while protecting the branch {branch}.")
        return []

    def allow_release_prs(self, repo: str) -> List[str]:
        repo = self._full_path(repo)
        with github_client() as client:
            # The token stays read-only by default (workflows ask for what they need); it may open pull requests.
            response = client.put(
                f"/repos/{repo}/actions/permissions/workflow",
                json={"default_workflow_permissions": "read", "can_approve_pull_request_reviews": True},
            )
        if response.is_error:
            # An organization's policy may forbid it.
            return [
                f"GitHub {response.status_code} while letting Actions open pull requests: turn on Settings → Actions "
                "→ General → Allow GitHub Actions to create and approve pull requests, for the release PR."
            ]
        return []

    def _full_path(self, repo: str) -> str:
        """owner/repo; a bare name belongs to the configured organization, or to the authenticated user."""
        if "/" in repo:
            return repo
        return f"{settings.github_org or _authenticated_user()}/{repo}"


def _authenticated_user() -> str:
    with github_client() as client:
        response = client.get("/user")
        if response.is_error:
            raise GitHubError(f"GitHub {response.status_code} while reading the authenticated user.")
        return response.json()["login"]


def _repo_public_key(client: httpx.Client, repo: str) -> Tuple[str, str]:
    response = client.get(f"/repos/{repo}/actions/secrets/public-key")
    _raise_for_status(response, "read the secrets' public key")
    data = response.json()
    return data["key_id"], data["key"]


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Encrypt a secret using the repo's public key (libsodium sealed box)."""
    try:
        from nacl import public
    except ImportError as exc:
        raise RuntimeError("PyNaCl is required for secret encryption: pip install PyNaCl") from exc

    sealed_box = public.SealedBox(public.PublicKey(base64.b64decode(public_key_b64)))
    return base64.b64encode(sealed_box.encrypt(secret_value.encode("utf-8"))).decode("utf-8")


def _raise_for_status(response: httpx.Response, action: str) -> None:
    if response.is_error:
        hint = _ERROR_HINTS.get(response.status_code, "")
        msg = f"GitHub {response.status_code} while trying to {action}."
        if hint:
            msg += f" {hint}"
        raise GitHubError(msg)
