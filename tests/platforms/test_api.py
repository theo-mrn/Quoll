import base64
import json

import httpx
import pytest
import respx

from quoll.platforms.base import PlatformError
from quoll.platforms.github.api import GITHUB_API, GitHubAPI
from quoll.platforms.gitlab.api import GitLabAPI

GITLAB_API = "https://gitlab.com/api/v4"


@pytest.fixture()
def settings(monkeypatch):
    import quoll.config.settings as cfg

    for name, value in {
        "github_token": "gh-token",
        "github_org": "",
        "gitlab_token": "gl-token",
        "gitlab_url": "https://gitlab.com",
        "gitlab_group": "",
    }.items():
        monkeypatch.setattr(cfg.settings, name, value)
    return cfg.settings


# --------------------------------------------------------------------------- GitHub


@respx.mock
def test_github_create_repo_user(settings) -> None:
    respx.post(f"{GITHUB_API}/user/repos").mock(
        return_value=httpx.Response(
            201, json={"clone_url": "https://github.com/user/app.git", "full_name": "user/app"}
        )
    )
    repo = GitHubAPI().create_repo("app", private=True)
    assert (repo.path, repo.clone_url) == ("user/app", "https://github.com/user/app.git")


@respx.mock
def test_github_create_repo_org(settings) -> None:
    settings.github_org = "my-org"
    route = respx.post(f"{GITHUB_API}/orgs/my-org/repos").mock(
        return_value=httpx.Response(201, json={"clone_url": "https://github.com/my-org/app.git"})
    )
    assert GitHubAPI().create_repo("app").clone_url == "https://github.com/my-org/app.git"
    assert json.loads(route.calls[0].request.content)["private"] is True


@respx.mock
def test_github_create_repo_error_explains(settings) -> None:
    respx.post(f"{GITHUB_API}/user/repos").mock(return_value=httpx.Response(422))
    with pytest.raises(PlatformError, match="may already exist"):
        GitHubAPI().create_repo("app")


@respx.mock
def test_github_protect_branch(settings) -> None:
    route = respx.put(f"{GITHUB_API}/repos/my-org/app/branches/main/protection").mock(
        return_value=httpx.Response(200, json={})
    )
    assert GitHubAPI().protect_branch("my-org/app", "main", required_checks=["CI result"]) == []
    body = json.loads(route.calls[0].request.content)
    assert body["required_status_checks"]["contexts"] == ["CI result"]


@respx.mock
def test_github_bare_repo_name_belongs_to_the_user(settings) -> None:
    respx.get(f"{GITHUB_API}/user").mock(return_value=httpx.Response(200, json={"login": "theo"}))
    route = respx.put(f"{GITHUB_API}/repos/theo/app/branches/main/protection").mock(
        return_value=httpx.Response(200, json={})
    )
    GitHubAPI().protect_branch("app", "main")
    assert route.called


@respx.mock
def test_github_set_secrets(settings) -> None:
    pytest.importorskip("nacl")
    from nacl.public import PrivateKey

    public_key = base64.b64encode(bytes(PrivateKey.generate().public_key)).decode()
    respx.get(f"{GITHUB_API}/repos/my-org/app/actions/secrets/public-key").mock(
        return_value=httpx.Response(200, json={"key_id": "123", "key": public_key})
    )
    route = respx.put(f"{GITHUB_API}/repos/my-org/app/actions/secrets/MY_SECRET").mock(
        return_value=httpx.Response(201, json={})
    )
    GitHubAPI().set_secrets("my-org/app", {"MY_SECRET": "super-secret"})
    body = json.loads(route.calls[0].request.content)
    assert body["key_id"] == "123" and body["encrypted_value"] != "super-secret"


# --------------------------------------------------------------------------- GitLab


@respx.mock
def test_gitlab_create_project_in_group(settings) -> None:
    settings.gitlab_group = "acme/backend"
    respx.get(f"{GITLAB_API}/groups/acme%2Fbackend").mock(return_value=httpx.Response(200, json={"id": 42}))
    route = respx.post(f"{GITLAB_API}/projects").mock(
        return_value=httpx.Response(
            201,
            json={
                "path_with_namespace": "acme/backend/app",
                "http_url_to_repo": "https://gitlab.com/acme/backend/app.git",
                "web_url": "https://gitlab.com/acme/backend/app",
            },
        )
    )
    repo = GitLabAPI().create_repo("app", private=False)
    assert repo.path == "acme/backend/app"
    body = json.loads(route.calls[0].request.content)
    assert (body["namespace_id"], body["visibility"]) == (42, "public")
    assert route.calls[0].request.headers["PRIVATE-TOKEN"] == "gl-token"


@respx.mock
def test_gitlab_self_managed_instance(settings) -> None:
    route = respx.post("https://gitlab.acme.io/api/v4/projects").mock(
        return_value=httpx.Response(
            201, json={"path_with_namespace": "theo/app", "http_url_to_repo": "x", "web_url": "y"}
        )
    )
    GitLabAPI("https://gitlab.acme.io").create_repo("app")
    assert route.called


@respx.mock
def test_gitlab_set_secrets_creates_or_updates_masked_variables(settings) -> None:
    project = f"{GITLAB_API}/projects/acme%2Fapp/variables"
    update_existing = respx.put(f"{project}/SONAR_TOKEN").mock(return_value=httpx.Response(200, json={}))
    respx.put(f"{project}/SHORT").mock(return_value=httpx.Response(404, json={}))
    create = respx.post(project).mock(return_value=httpx.Response(201, json={}))

    GitLabAPI().set_secrets("acme/app", {"SONAR_TOKEN": "squ_0123456789abcdef", "SHORT": "abc"})

    assert json.loads(update_existing.calls[0].request.content)["masked"] is True
    # GitLab refuses to mask values shorter than 8 characters.
    created = json.loads(create.calls[0].request.content)
    assert (created["key"], created["masked"]) == ("SHORT", False)


@respx.mock
def test_gitlab_protect_branch(settings) -> None:
    project = f"{GITLAB_API}/projects/acme%2Fapp"
    respx.delete(f"{project}/protected_branches/main").mock(return_value=httpx.Response(204))
    protect = respx.post(f"{project}/protected_branches").mock(return_value=httpx.Response(201, json={}))
    settings_route = respx.put(project).mock(return_value=httpx.Response(200, json={}))
    respx.post(f"{project}/approval_rules").mock(return_value=httpx.Response(403, json={}))

    warnings = GitLabAPI().protect_branch("acme/app", "main")

    assert json.loads(protect.calls[0].request.content)["push_access_level"] == 0
    assert json.loads(settings_route.calls[0].request.content)["only_allow_merge_if_pipeline_succeeds"] is True
    # Approval rules need GitLab Premium: a warning, not a failure.
    assert len(warnings) == 1 and "Premium" in warnings[0]


@respx.mock
def test_gitlab_error_explains(settings) -> None:
    respx.post(f"{GITLAB_API}/projects").mock(return_value=httpx.Response(403))
    with pytest.raises(PlatformError, match="the 'api' scope"):
        GitLabAPI().create_repo("app")
