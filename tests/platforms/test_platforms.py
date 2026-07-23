from __future__ import annotations

import pytest

from quoll import platforms
from quoll.platforms import Remote, parse_remote


@pytest.mark.parametrize(
    "url, expected",
    [
        ("git@github.com:acme/api.git", Remote("github.com", "acme/api")),
        ("https://github.com/acme/api/", Remote("github.com", "acme/api")),
        ("https://oauth2:tok@gitlab.com/acme/backend/api.git", Remote("gitlab.com", "acme/backend/api")),
        ("ssh://git@gitlab.acme.io:2222/team/api.git", Remote("gitlab.acme.io", "team/api")),
        ("/srv/git/api.git", None),
        ("", None),
    ],
)
def test_parse_remote(url, expected) -> None:
    assert parse_remote(url) == expected


@pytest.mark.parametrize(
    "platform, remote, registry, image",
    [
        ("github", Remote("github.com", "Acme/API"), "ghcr", "ghcr.io/acme/api"),
        ("github", None, "dockerhub", "your-org/svc"),
        ("gitlab", Remote("gitlab.com", "acme/backend/api"), "gitlab", "registry.gitlab.com/acme/backend/api"),
        ("gitlab", Remote("gitlab.acme.io", "team/api"), "gitlab", "registry.gitlab.acme.io/team/api"),
        ("gitlab", Remote("gitlab.com", "acme/backend/api"), "dockerhub", "acme/api"),
    ],
)
def test_default_image(platform, remote, registry, image) -> None:
    assert platforms.get(platform).default_image(remote, registry, "svc") == image


def test_unknown_platform() -> None:
    with pytest.raises(KeyError, match="bitbucket"):
        platforms.get("bitbucket")
