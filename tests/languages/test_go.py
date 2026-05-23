from __future__ import annotations

from quoll.ci.detect import detect
from tests.helpers import runs, steps, uses, workflow
from tests.samples import GO

# --------------------------------------------------------------------------- detection


def test_go(make_project) -> None:
    det = detect(make_project(GO))
    assert det.stack == "go"
    assert det.version == "1.23"
    assert det.version_file == "go.mod"
    assert det.has_dockerfile
    assert det.lint_tools == ["gofmt", "vet", "golangci-lint"]


def test_without_go_sum_disables_cache(make_project) -> None:
    det = detect(make_project({"go.mod": "module x\n\ngo 1.22\n"}))
    assert det.lockfile == ""
    assert det.cache is False


# --------------------------------------------------------------------------- workflow


def test_go_workflow(make_project) -> None:
    doc = workflow(make_project, GO, test__coverage_threshold=70)
    assert "golangci/golangci-lint-action@v9" in uses(doc, "lint")
    assert "-v min=70" in runs(doc, "test")
    assert [s.get("uses") for s in steps(doc, "audit")][:2] == ["actions/checkout@v7", "actions/setup-go@v7"]
    # govulncheck may need a newer Go than the project's to build.
    assert "GOTOOLCHAIN=auto go run golang.org/x/vuln/cmd/govulncheck@latest ./..." in runs(doc, "audit")
