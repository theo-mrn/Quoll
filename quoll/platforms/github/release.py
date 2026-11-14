"""Release automation on GitHub: release-please keeps a release pull request open from the Conventional Commits on
the default branch; merging it tags v<version> and creates the GitHub release.

Created with the workflow's own token, neither the release PR nor the tag start a workflow by themselves (GitHub's
rule against recursive runs): the release workflow dispatches the CI on the release PR, so that its required check
reports, and the delivery on the tag. A workspace releases as a whole, like a v* tag pushed by hand.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from quoll.config import quoll_toml
from quoll.config.quoll_toml import ConfigError
from quoll.files import MARKER, PlannedFile, header, planned
from quoll.platforms.github.actions import ACTIONS
from quoll.platforms.github.ci import WORKFLOW_PATH as CI_PATH
from quoll.platforms.github.workflow import dump, pin

WORKFLOW_PATH = Path(".github/workflows/release.yml")
CONFIG_PATH = Path("release-please-config.json")
MANIFEST_PATH = Path(".release-please-manifest.json")

# Stacks whose version files release-please bumps along with their lockfile. The others only get CHANGELOG.md:
# their version lives in the tag (e.g. uv.lock records the project's version, which release-please can't update).
_RELEASE_TYPES = {"node": "node", "rust": "rust"}

_DISPATCH_CI = 'gh workflow run "$WORKFLOW" --repo "$GITHUB_REPOSITORY" --ref "$BRANCH"'


def plan(root: Path, branch: str, deliveries: List[str], workspace: bool) -> List[PlannedFile]:
    """The release workflow, dispatching the delivery workflows `deliveries` on each release; release-please's
    configuration and manifest, written once for the project to own."""
    return [
        planned(root, WORKFLOW_PATH, render_workflow(branch, deliveries, ci=_quoll_ci(root))),
        planned(root, CONFIG_PATH, render_config(_release_type(root, workspace)), create_only=True),
        planned(root, MANIFEST_PATH, _json({".": _last_version(root)}), create_only=True),
    ]


def render_workflow(branch: str, deliveries: List[str], ci: bool = True) -> str:
    gh_token = {"GH_TOKEN": "${{ github.token }}"}
    steps: List[Dict[str, Any]] = [
        {"name": "Release PR or release", "id": "release", "uses": pin(ACTIONS["release-please"])},
    ]
    if ci:
        steps.append({
            "name": "Run the CI on the release PR",
            "if": "${{ steps.release.outputs.pr }}",
            "run": _DISPATCH_CI,
            "env": {
                **gh_token,
                "WORKFLOW": CI_PATH.name,
                "BRANCH": "${{ fromJSON(steps.release.outputs.pr).headBranchName }}",
            },
        })
    publish = "\n".join(f'gh workflow run {w} --repo "$GITHUB_REPOSITORY" --ref "$TAG"' for w in deliveries)
    steps.append({
        "name": "Publish the release",
        "if": "${{ steps.release.outputs.release_created == 'true' }}",
        "run": publish,
        "env": {**gh_token, "TAG": "${{ steps.release.outputs.tag_name }}"},
    })
    doc = {
        "name": "Release",
        "on": {"push": {"branches": [branch]}},
        "permissions": {"contents": "read"},
        # One release at a time: a second merge waits for the first release to exist.
        "concurrency": {"group": "${{ github.workflow }}", "cancel-in-progress": False},
        "jobs": {
            "release": {
                "name": "Release PR and release",
                "runs-on": "ubuntu-latest",
                "timeout-minutes": 10,
                "permissions": {
                    "contents": "write",  # the release branch, the tag, the release
                    "pull-requests": "write",
                    "issues": "write",  # the release PR's labels
                    "actions": "write",  # dispatch the CI and the delivery
                },
                "steps": steps,
            }
        },
    }
    return header("cd") + dump(doc)


def render_config(release_type: str) -> str:
    return _json({
        "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
        "packages": {
            ".": {
                "release-type": release_type,
                # Tags v1.2.3: what the delivery publishes.
                "include-component-in-tag": False,
                # Before 1.0.0, a breaking change bumps the minor version.
                "bump-minor-pre-major": True,
            }
        },
    })


def _release_type(root: Path, workspace: bool) -> str:
    if workspace:
        return "simple"
    try:
        stack = quoll_toml.read(root).get("project", {}).get("stack", "")
    except ConfigError:
        stack = ""
    return _RELEASE_TYPES.get(stack, "simple")


def _last_version(root: Path) -> str:
    """The latest v* tag, where release-please starts from; 0.0.0 for a project never released."""
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    tag = result.stdout.strip()
    return tag[1:] if result.returncode == 0 and tag else "0.0.0"


def _quoll_ci(root: Path) -> bool:
    """quoll's CI, which can be dispatched (a hand-written one may not have `workflow_dispatch`)."""
    path = root / CI_PATH
    return path.exists() and MARKER in path.read_text()


def _json(data: Any) -> str:
    return json.dumps(data, indent=2) + "\n"
