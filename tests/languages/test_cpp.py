from __future__ import annotations

from quoll.ci.detect import detect
from tests.helpers import dockerfile, pipeline, runs, script, steps, workflow
from tests.samples import C_MESON, CPP_CMAKE, CPP_CONAN

# --------------------------------------------------------------------------- detection


def test_detection(make_project) -> None:
    det = detect(make_project(CPP_CMAKE))
    assert (det.stack, det.package_manager, det.test_runner) == ("cpp", "cmake", "ctest")
    assert det.lint_tools == ["clang-format", "cppcheck"]
    assert det.version == "gcc-14" and det.matrix_versions == ["gcc-14", "clang-18"]
    assert det.sanitizers and not det.audit


def test_conan_detection(make_project) -> None:
    det = detect(make_project(CPP_CONAN))
    assert (det.package_manager, det.lockfile, det.services) == ("conan", "conan.lock", ["postgres"])
    assert det.audit  # osv-scanner reads conan.lock


def test_meson_detection(make_project) -> None:
    det = detect(make_project(C_MESON))
    assert (det.package_manager, det.test_runner) == ("meson", "meson")


def test_python_wins_over_its_native_cmake(make_project) -> None:
    det = detect(make_project({**CPP_CMAKE, "pyproject.toml": '[project]\nname = "x"\n'}))
    assert det.stack == "python"


# --------------------------------------------------------------------------- CI


def test_github_workflow(make_project) -> None:
    doc = workflow(make_project, CPP_CMAKE, test__coverage_threshold=70)
    setup = runs(doc, "test")
    assert 'compiler="gcc-14"' in setup and "gcovr" in setup and '>> "$GITHUB_ENV"' in setup
    assert '-DCMAKE_CXX_FLAGS="--coverage -fsanitize=address,undefined' in setup
    assert "ctest --test-dir build --output-on-failure --output-junit junit.xml" in setup
    assert "--fail-under-line 70" in setup
    lint = runs(doc, "lint")
    assert "clang-format --dry-run --Werror" in lint and "cppcheck --project=build/compile_commands.json" in lint


def test_matrix_over_compilers(make_project) -> None:
    doc = workflow(make_project, CPP_CMAKE, versions=["gcc-14", "clang-18"])
    assert doc["jobs"]["test"]["strategy"]["matrix"] == {"compiler": ["gcc-14", "clang-18"]}
    # Through the environment: an expression is never pasted into a script.
    toolchain = steps(doc, "test")[1]
    assert toolchain["env"] == {"QUOLL_COMPILER": "${{ matrix.compiler }}"}
    assert 'compiler="$QUOLL_COMPILER"' in toolchain["run"] and "${{" not in toolchain["run"]


def test_gitlab_pipeline(make_project) -> None:
    doc = pipeline(make_project, CPP_CMAKE, versions=["gcc-14", "clang-18"])
    assert doc["lint"]["image"] == "ubuntu:24.04"
    assert 'compiler="${COMPILER:-clang-18}"' in doc["lint"]["script"][0]
    assert doc["test"]["parallel"]["matrix"][0] == {"COMPILER": "gcc-14", "IMAGE": "ubuntu:24.04"}
    assert doc["test"]["artifacts"]["reports"]["junit"] == "build/junit.xml"
    reports = doc["test"]["artifacts"]["reports"]
    assert reports["coverage_report"] == {"coverage_format": "cobertura", "path": "coverage.xml"}
    assert "coverage" in doc["test"]


def test_conan_configure(make_project) -> None:
    assert "pipx run conan install . --output-folder=build" in script(pipeline(make_project, CPP_CONAN), "lint")


def test_meson_configure(make_project) -> None:
    meson = runs(workflow(make_project, C_MESON), "test")
    assert "meson setup build --buildtype=debug -Db_coverage=true -Db_sanitize=address,undefined" in meson


def test_codeql_builds_with_the_language(make_project) -> None:
    doc = workflow(make_project, CPP_CMAKE, security={"codeql": True})
    names = [s.get("name") or s.get("uses") for s in steps(doc, "codeql")]
    assert names.index("Initialize CodeQL") < names.index("Configure") < names.index("Analyze")


# --------------------------------------------------------------------------- Docker


def test_dockerfile(make_project) -> None:
    text = dockerfile(make_project, CPP_CMAKE)
    assert "FROM gcc:14 AS build" in text and "cmake ninja-build" in text
    assert "-name 'calc'" in text
    assert "FROM gcr.io/distroless/cc-debian13:nonroot" in text


def test_conan_dockerfile(make_project) -> None:
    text = dockerfile(make_project, CPP_CONAN)
    assert "pipx run conan install" in text and "CMAKE_TOOLCHAIN_FILE=/src/build/conan_toolchain.cmake" in text
