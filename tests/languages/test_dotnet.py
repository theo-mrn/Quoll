from __future__ import annotations

from quoll.ci.detect import detect
from tests.helpers import runs, steps, workflow
from tests.samples import DOTNET


def test_solution(make_project) -> None:
    det = detect(make_project(DOTNET))
    assert det.stack == "dotnet"
    assert det.version == "8.0"
    assert det.matrix_versions == ["8.0", "10.0"]
    assert det.install == "dotnet restore --locked-mode"
    assert det.test_runner == "dotnet"
    assert det.coverage is True  # coverlet.msbuild
    doc = workflow(make_project, DOTNET)
    assert steps(doc, "test")[1]["with"]["cache"] is True
    assert "-p:Threshold=80 -p:ThresholdType=line" in runs(doc, "test")
    assert "dotnet list package --vulnerable" in runs(doc, "audit")


def test_global_json_and_no_tests(make_project) -> None:
    files = {"App.csproj": "<Project/>", "global.json": {"sdk": {"version": "9.0.100"}}}
    det = detect(make_project(files))
    assert (det.version_file, det.version) == ("global.json", "9.0")
    assert det.cache is False  # no packages.lock.json
    assert det.test_runner == ""
    assert steps(workflow(make_project, files), "lint")[1]["with"] == {"global-json-file": "global.json"}
