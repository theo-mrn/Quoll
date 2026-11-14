from __future__ import annotations

import json
import subprocess

import pytest
import yaml
from typer.testing import CliRunner

from quoll.cd.config import CDConfig
from quoll.main import app
from quoll.platforms.github.cd import render_workflow
from quoll.platforms.gitlab.cd import render_pipeline as render_gitlab
from tests.helpers import actionlint, gitlab_lint, load
from tests.samples import GO

runner = CliRunner()


def _quoll(*args: str):
    return runner.invoke(app, list(args))


def test_init_defaults_to_ghcr_from_the_git_remote(make_project, tmp_path) -> None:
    root = make_project(GO)
    subprocess.run(["git", "init", "-q", "-b", "trunk"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:Acme/API.git"], cwd=root, check=True)
    result = _quoll("cd", "init", "-y", "-d", str(root))
    assert result.exit_code == 0, result.output
    text = (root / ".github/workflows/cd.yml").read_text()
    doc = load(text)
    assert doc["on"]["push"] == {"branches": ["trunk"], "tags": ["v*"]}
    job = doc["jobs"]["image"]
    assert job["permissions"] == {
        "contents": "write",  # the release gets the SBOM
        "packages": "write",
        "id-token": "write",  # Sigstore attestations
        "attestations": "write",
        "artifact-metadata": "write",
    }
    names = [s.get("name") for s in job["steps"]]
    # The scan runs on a local build, before anything is pushed.
    assert names.index("Scan image") < names.index("Log in to the registry") < names.index("Push image")
    meta = next(s for s in job["steps"] if s.get("id") == "meta")
    assert meta["with"]["images"] == "ghcr.io/acme/api"
    assert '[cd]\nregistry = "ghcr"\nimage = "ghcr.io/acme/api"' in (root / "quoll.toml").read_text()
    actionlint(tmp_path, text)


def test_dockerhub_multi_arch_without_scan(tmp_path) -> None:
    cfg = CDConfig(
        registry="dockerhub",
        image="acme/api",
        platforms=["linux/amd64", "linux/arm64"],
        scan=False,
        sbom=False,
        sign=False,
    )
    text = render_workflow(cfg)
    job = load(text)["jobs"]["image"]
    uses = [s.get("uses", "") for s in job["steps"]]
    assert any(u.startswith("docker/setup-qemu-action") for u in uses)
    assert not any("trivy" in u for u in uses)
    login = next(s for s in job["steps"] if s.get("name") == "Log in to the registry")
    assert login["with"]["password"] == "${{ secrets.DOCKERHUB_TOKEN }}"
    assert job["permissions"] == {"contents": "read"}
    push = next(s for s in job["steps"] if s.get("name") == "Push image")
    assert push["with"]["platforms"] == "linux/amd64,linux/arm64"
    actionlint(tmp_path, text)


@pytest.mark.parametrize(
    "fields, error",
    [
        ({"image": "docker.io/acme/api"}, "must start with ghcr.io/"),
        ({"image": "ghcr.io/Acme/api"}, "lowercase"),
        ({"image": "ghcr.io/acme/api", "severity": ["SEVERE"]}, "unknown severity"),
        ({"image": "ghcr.io/acme/api", "branches": [], "release_tags": False}, "nothing would publish"),
        ({"image": "acme/api", "registry": "quay"}, "unknown registry"),
    ],
)
def test_validation(fields, error) -> None:
    with pytest.raises(ValueError, match=error):
        CDConfig(**fields)


def test_check_and_update_cycle(make_project) -> None:
    root = make_project(GO)
    assert _quoll("cd", "init", "-y", "-d", str(root), "--image", "ghcr.io/acme/api").exit_code == 0
    assert _quoll("cd", "check", "-d", str(root)).exit_code == 0
    config = root / "quoll.toml"
    config.write_text(config.read_text().replace('"HIGH"', '"MEDIUM", "HIGH"'))
    assert _quoll("cd", "check", "-d", str(root)).exit_code == 1
    assert _quoll("cd", "update", "-y", "-d", str(root)).exit_code == 0
    assert "severity: CRITICAL,MEDIUM,HIGH" in (root / ".github/workflows/cd.yml").read_text()


def test_cd_only_shares_the_platform(make_project) -> None:
    root = make_project({"Dockerfile": "FROM scratch\n"})
    result = _quoll("cd", "init", "-y", "-d", str(root), "--registry", "dockerhub", "--image", "acme/tool")
    assert result.exit_code == 0, result.output
    assert (root / "quoll.toml").read_text().startswith('[project]\nplatform = "github"\n\n[cd]')
    assert "DOCKERHUB_TOKEN" in result.output


def test_cd_keeps_the_project_section(make_project) -> None:
    root = make_project(GO)
    assert _quoll("ci", "init", "-y", "-d", str(root)).exit_code == 0
    assert _quoll("cd", "init", "-y", "-d", str(root), "--image", "ghcr.io/acme/api").exit_code == 0
    text = (root / "quoll.toml").read_text()
    assert 'stack = "go"' in text and text.count("[project]") == 1


# --------------------------------------------------------------------------- GitLab


def test_gitlab_init_defaults_to_the_project_registry(make_project, tmp_path) -> None:
    root = make_project(GO)
    subprocess.run(["git", "init", "-q", "-b", "trunk"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@gitlab.com:Acme/backend/API.git"], cwd=root, check=True)
    result = _quoll("cd", "init", "-y", "-d", str(root))
    assert result.exit_code == 0, result.output
    text = (root / ".gitlab/cd.yml").read_text()
    job = yaml.safe_load(text)["publish"]
    assert job["stage"] == "publish" and job["interruptible"] is False
    assert job["variables"]["IMAGE"] == "registry.gitlab.com/acme/backend/api"
    assert job["rules"] == [
        {"if": '$CI_PIPELINE_SOURCE == "schedule"', "when": "never"},  # the scheduled security scans
        {"if": '$CI_COMMIT_BRANCH == "trunk"'},
        {"if": "$CI_COMMIT_TAG =~ /^v/"},
    ]
    script = "\n".join(job["script"])
    # The scan runs on a local build, before the image is pushed (only build layers reach the cache before).
    assert script.index("trivy") < script.rindex("docker login") < script.index("--push")
    # Layers cached in the project's registry, shared with the CI's docker job.
    assert 'ref="$CI_REGISTRY_IMAGE/cache:ci"' in script and "--push $cache" in script
    assert '"$CI_REGISTRY_PASSWORD"' in script
    assert 'registry = "gitlab"' in (root / "quoll.toml").read_text()
    # No .gitlab-ci.yml includes it yet.
    assert "quoll ci init" in result.output
    gitlab_lint(tmp_path, text)


def test_gitlab_dockerhub_multi_arch_without_scan(tmp_path) -> None:
    cfg = CDConfig(
        platform="gitlab",
        registry="dockerhub",
        image="acme/api",
        platforms=["linux/amd64", "linux/arm64"],
        scan=False,
        sbom=False,
        sign=False,
    )
    text = render_gitlab(cfg)
    script = "\n".join(yaml.safe_load(text)["publish"]["script"])
    assert "tonistiigi/binfmt" in script and "trivy" not in script
    assert '"$DOCKERHUB_TOKEN"' in script and "--platform linux/amd64,linux/arm64 --push" in script
    gitlab_lint(tmp_path, text)


def test_gitlab_tags_match_github(tmp_path) -> None:
    """The tag script publishes what docker/metadata-action does on GitHub."""
    tags_script = yaml.safe_load(render_gitlab(CDConfig(platform="gitlab", image="registry.gitlab.com/a/b")))
    tags_script = tags_script["publish"]["script"][0]

    def tags(**env: str) -> str:
        base = {"CI_COMMIT_SHORT_SHA": "abc12345", "CI_DEFAULT_BRANCH": "main", "IMAGE": "img"}
        out = subprocess.run(
            ["sh", "-c", tags_script + '\necho "$tags"'], env={**base, **env}, capture_output=True, text=True
        )
        return out.stdout.strip()

    assert tags(CI_COMMIT_BRANCH="main", CI_COMMIT_REF_SLUG="main") == "sha-abc12345 main latest"
    assert tags(CI_COMMIT_BRANCH="dev", CI_COMMIT_REF_SLUG="dev") == "sha-abc12345 dev"
    assert tags(CI_COMMIT_TAG="v1.2.3") == "sha-abc12345 1.2.3 1.2 latest"
    assert tags(CI_COMMIT_TAG="v2.0.0-rc.1") == "sha-abc12345 2.0.0-rc.1"


@pytest.mark.parametrize(
    "fields, error",
    [
        ({"registry": "ghcr", "image": "ghcr.io/acme/api"}, "unknown registry 'ghcr' for gitlab"),
        ({"registry": "gitlab", "image": "acme/api"}, "registry host"),
    ],
)
def test_gitlab_validation(fields, error) -> None:
    with pytest.raises(ValueError, match=error):
        CDConfig(platform="gitlab", **fields)


def test_github_supply_chain(tmp_path) -> None:
    text = render_workflow(CDConfig(registry="dockerhub", image="acme/api"))
    job = load(text)["jobs"]["image"]
    names = [s.get("name") for s in job["steps"]]
    # SBOM of the pushed digest, signed attestations, then the SBOM on the release.
    assert names.index("Push image") < names.index("SBOM of the image") < names.index("Attest SBOM")
    assert names.index("Attest SBOM") < names.index("Attach the SBOM to the release")
    attest = next(s for s in job["steps"] if s.get("name") == "Attest build provenance")
    assert attest["uses"] == "actions/attest@v4"
    assert attest["with"]["subject-name"] == "index.docker.io/acme/api"
    sbom = next(s for s in job["steps"] if s.get("name") == "SBOM of the image")
    assert sbom["env"]["TRIVY_PASSWORD"] == "${{ secrets.DOCKERHUB_TOKEN }}"
    actionlint(tmp_path, text)


def test_gitlab_supply_chain(tmp_path) -> None:
    text = render_gitlab(CDConfig(platform="gitlab", image="registry.gitlab.com/acme/api"))
    doc = yaml.safe_load(text)
    publish = doc["publish"]
    script = "\n".join(publish["script"])
    assert script.index("--metadata-file metadata.json") < script.index("cosign sign --yes")
    assert "cosign attest --yes --type cyclonedx --predicate sbom.cdx.json" in script
    assert publish["id_tokens"] == {"SIGSTORE_ID_TOKEN": {"aud": "sigstore"}}
    assert publish["artifacts"]["reports"] == {"cyclonedx": ["sbom.cdx.json"]}
    release = doc["release"]
    assert release["rules"] == [{"if": "$CI_COMMIT_TAG =~ /^v/"}]
    assert release["release"]["assets"]["links"][0]["url"].endswith("/artifacts/raw/sbom.cdx.json")
    gitlab_lint(tmp_path, text)


def test_digest_extraction(tmp_path) -> None:
    """The digest comes from buildx's metadata file."""
    from quoll.platforms.gitlab.cd import _DIGEST

    metadata = '{\n  "buildx.build.ref": "x",\n  "containerimage.digest": "sha256:abc123",\n  "image.name": "y"\n}\n'
    out = subprocess.run(
        ["sh", "-c", f"cat > metadata.json <<'EOF'\n{metadata}EOF\n{_DIGEST}"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert out.stdout.strip() == "Digest: sha256:abc123"



# --------------------------------------------------------------------------- Releases (release-please)


def test_release_pr(make_project, tmp_path) -> None:
    root = make_project({**GO, "Dockerfile": "FROM scratch\n"})
    assert _quoll("ci", "init", "-y", "-d", str(root)).exit_code == 0
    result = _quoll("cd", "init", "-y", "-d", str(root), "--image", "ghcr.io/acme/api")
    assert result.exit_code == 0, result.output
    assert "release_pr = true" in (root / "quoll.toml").read_text()
    assert "Conventional Commits" in result.output
    text = (root / ".github/workflows/release.yml").read_text()
    doc = load(text)
    assert doc["on"] == {"push": {"branches": ["main"]}}
    steps = doc["jobs"]["release"]["steps"]
    assert steps[0]["uses"].startswith("googleapis/release-please-action@")
    # Created with the workflow's token, the release PR and the tag start nothing: dispatched instead.
    ci, publish = steps[1], steps[2]
    assert ci["env"]["WORKFLOW"] == "ci.yml"
    # Read by jq: the step's env is evaluated even when its `if` skips it, which fromJSON can't take when empty.
    assert ci["env"]["PR"] == "${{ steps.release.outputs.pr }}"
    assert "jq -r .headBranchName" in ci["run"]
    assert publish["run"] == 'gh workflow run cd.yml --repo "$GITHUB_REPOSITORY" --ref "$TAG"'
    assert doc["jobs"]["release"]["permissions"]["actions"] == "write"
    config = json.loads((root / "release-please-config.json").read_text())
    assert config["packages"]["."] == {
        "release-type": "simple",  # Go: the version lives in the tag
        "include-component-in-tag": False,
        "bump-minor-pre-major": True,
        # Never released: release-please would start at 1.0.0.
        "initial-version": "0.1.0",
    }
    assert json.loads((root / ".release-please-manifest.json").read_text()) == {".": "0.0.0"}
    actionlint(tmp_path, text)

    # release-please owns its manifest: check and update leave it alone.
    (root / ".release-please-manifest.json").write_text('{".": "1.4.0"}\n')
    assert _quoll("cd", "check", "-d", str(root)).exit_code == 0
    assert _quoll("cd", "update", "-y", "-d", str(root)).exit_code == 0
    assert "1.4.0" in (root / ".release-please-manifest.json").read_text()


def test_release_pr_starts_from_the_last_tag(make_project) -> None:
    root = make_project({"package.json": {"name": "api", "scripts": {"start": "node index.js"}}, "index.js": ""})
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "feat: first"], cwd=root, check=True)
    subprocess.run([*git, "tag", "v0.3.1"], cwd=root, check=True)
    assert _quoll("ci", "init", "-y", "-d", str(root)).exit_code == 0
    assert _quoll("cd", "init", "-y", "-d", str(root), "--image", "ghcr.io/acme/api").exit_code == 0
    assert json.loads((root / ".release-please-manifest.json").read_text()) == {".": "0.3.1"}
    package = json.loads((root / "release-please-config.json").read_text())["packages"]["."]
    # Node: package.json's version follows (and package-lock.json's).
    assert package["release-type"] == "node"
    assert "initial-version" not in package  # the next release follows v0.3.1


def test_no_release_pr(make_project) -> None:
    root = make_project(GO)
    result = _quoll("cd", "init", "-y", "-d", str(root), "--image", "ghcr.io/acme/api", "--no-release-pr")
    assert result.exit_code == 0, result.output
    assert not (root / ".github/workflows/release.yml").exists()
    assert not (root / "release-please-config.json").exists()


def test_release_without_quoll_ci_dispatches_only_the_delivery() -> None:
    from quoll.platforms.github.release import render_workflow

    doc = load(render_workflow("trunk", ["cd-web.yml", "cd-api.yml"], ci=False))
    assert doc["on"] == {"push": {"branches": ["trunk"]}}
    names = [s["name"] for s in doc["jobs"]["release"]["steps"]]
    assert names == ["Release PR or release", "Publish the release"]
    run = doc["jobs"]["release"]["steps"][1]["run"]
    assert "gh workflow run cd-web.yml" in run and "gh workflow run cd-api.yml" in run


@pytest.mark.parametrize(
    "fields, error",
    [
        ({"platform": "gitlab", "image": "registry.gitlab.com/acme/api", "release_pr": True}, "GitHub only"),
        ({"image": "ghcr.io/acme/api", "release_pr": True, "release_tags": False}, "needs release_tags"),
    ],
)
def test_release_pr_validation(fields, error) -> None:
    with pytest.raises(ValueError, match=error):
        CDConfig(**fields)


def test_init_again_keeps_the_manifest(make_project) -> None:
    root = make_project(GO)
    args = ("cd", "init", "-y", "--force", "-d", str(root), "--image", "ghcr.io/acme/api")
    assert _quoll(*args).exit_code == 0
    (root / ".release-please-manifest.json").write_text('{".": "2.0.0"}\n')
    assert _quoll(*args).exit_code == 0
    assert "2.0.0" in (root / ".release-please-manifest.json").read_text()
