from __future__ import annotations

from quoll.ci.detect import detect
from tests.helpers import runs, steps, uses, workflow
from tests.samples import (
    ANGULAR,
    ASTRO,
    NESTJS,
    NEXTJS,
    NODE_BUN,
    NODE_NPM_JEST,
    NODE_PNPM,
    NODE_YARN_BERRY,
    NUXT,
    SVELTEKIT,
)

# --------------------------------------------------------------------------- detection


def test_pnpm(make_project) -> None:
    det = detect(make_project(NODE_PNPM))
    assert det.stack == "node"
    assert det.package_manager == "pnpm"
    assert det.package_manager_version == "10"  # no packageManager field
    assert det.install == "pnpm install --frozen-lockfile"
    assert det.version_file == ".nvmrc"
    assert det.version == "22"
    assert det.lint_tools == ["script:lint", "prettier", "tsc"]
    assert det.test_runner == "vitest"
    assert det.coverage is True
    assert det.build_command == "pnpm run build"


def test_npm_jest(make_project) -> None:
    det = detect(make_project(NODE_NPM_JEST))
    assert det.package_manager == "npm"
    assert det.install == "npm ci"
    assert det.version == "22"
    assert det.lint_tools == ["eslint"]
    assert det.test_runner == "jest"


def test_without_lockfile_disables_cache(make_project) -> None:
    det = detect(make_project({"package.json": {"name": "x", "devDependencies": {"jest": "29"}}}))
    assert det.install == "npm install"
    assert det.cache is False
    assert any("lockfile" in w for w in det.warnings)


def test_vitest_without_coverage_package(make_project) -> None:
    det = detect(make_project({"package.json": {"devDependencies": {"vitest": "3"}}, "package-lock.json": "{}"}))
    assert det.test_runner == "vitest"
    assert det.coverage is False


def test_yarn_berry_and_test_script(make_project) -> None:
    det = detect(make_project(NODE_YARN_BERRY))
    assert det.package_manager == "yarn"
    assert det.install == "yarn install --immutable"
    assert det.test_runner == "script:test"
    assert det.coverage is False


def test_yarn_classic(make_project) -> None:
    det = detect(make_project({"package.json": {"name": "old"}, "yarn.lock": "# yarn lockfile v1\n"}))
    assert det.package_manager == "yarn-classic"
    assert det.install == "yarn install --frozen-lockfile"


def test_npm_placeholder_test_script_is_ignored(make_project) -> None:
    package = {"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}
    det = detect(make_project({"package.json": package, "package-lock.json": "{}"}))
    assert det.test_runner == ""


def test_bun_with_biome(make_project) -> None:
    det = detect(make_project(NODE_BUN))
    assert det.package_manager == "bun"
    assert det.lint_tools == ["biome"]
    assert det.test_runner == "bun"


def test_invalid_package_json_warns(make_project) -> None:
    det = detect(make_project({"package.json": "{not json"}))
    assert det.stack == "node"
    assert any("package.json could not be parsed" in w for w in det.warnings)


# --------------------------------------------------------------------------- workflow


def test_pnpm_workflow(make_project) -> None:
    doc = workflow(make_project, NODE_PNPM)
    lint_uses = uses(doc, "lint")
    assert lint_uses.index("pnpm/action-setup@v6") < lint_uses.index("actions/setup-node@v7")
    setup = next(s for s in steps(doc, "lint") if s.get("uses") == "actions/setup-node@v7")
    assert setup["with"] == {"node-version-file": ".nvmrc", "cache": "pnpm"}
    lint = runs(doc, "lint")
    assert "pnpm run lint" in lint and "pnpm exec prettier --check ." in lint and "pnpm exec tsc --noEmit" in lint
    assert "--coverage.thresholds.lines=80" in runs(doc, "test")
    assert "pnpm audit --prod" in runs(doc, "audit")


def test_jest_threshold(make_project) -> None:
    doc = workflow(make_project, NODE_NPM_JEST, test__coverage_threshold=90)
    assert """npx jest --ci --coverage --coverageThreshold='{"global":{"lines":90}}'""" in runs(doc, "test")


def test_yarn_berry_enables_corepack_before_setup_node(make_project) -> None:
    test = steps(workflow(make_project, NODE_YARN_BERRY), "test")
    assert test[1]["run"] == "corepack enable"
    assert test[2]["with"]["cache"] == "yarn"


# --------------------------------------------------------------------------- frameworks


def test_nextjs(make_project) -> None:
    det = detect(make_project(NEXTJS))
    assert det.framework == "nextjs"
    assert "tsc" not in det.lint_tools  # next build type-checks
    doc = workflow(make_project, NEXTJS)
    assert doc["env"] == {"NEXT_TELEMETRY_DISABLED": "1"}
    cache = steps(doc, "build")[2]
    assert cache["uses"] == "actions/cache@v6" and cache["with"]["path"] == ".next/cache"


def test_nuxt_typecheck(make_project) -> None:
    det = detect(make_project(NUXT))
    assert det.framework == "nuxt"
    assert det.lint_tools == ["nuxt-typecheck"]
    assert "pnpm exec nuxi typecheck" in runs(workflow(make_project, NUXT), "lint")


def test_sveltekit_uses_check_script(make_project) -> None:
    det = detect(make_project(SVELTEKIT))
    assert det.framework == "sveltekit"
    assert det.lint_tools == ["script:check"]


def test_astro_check(make_project) -> None:
    det = detect(make_project(ASTRO))
    assert det.lint_tools == ["astro-check"]
    assert "npx astro check" in runs(workflow(make_project, ASTRO), "lint")


def test_angular_karma(make_project) -> None:
    det = detect(make_project(ANGULAR))
    assert det.framework == "angular"
    assert det.test_runner == "angular-karma"
    doc = workflow(make_project, ANGULAR)
    assert doc["env"] == {"NG_CLI_ANALYTICS": "false"}
    assert "npx ng test --watch=false --browsers=ChromeHeadless" in runs(doc, "test")


def test_angular_vitest_runner(make_project) -> None:
    pkg = {**ANGULAR["package.json"], "devDependencies": {"vitest": "3", "typescript": "5"}}
    det = detect(make_project({**ANGULAR, "package.json": pkg}))
    assert det.test_runner == "angular"
    assert det.warnings == []


def test_nestjs(make_project) -> None:
    det = detect(make_project(NESTJS))
    assert (det.framework, det.test_runner) == ("nestjs", "jest")


def test_prettier_leaves_quoll_files_alone() -> None:
    """quoll's files keep quoll's format; a chart's templates aren't YAML a formatter can read."""
    from quoll.languages.node.ci import _LINT

    command = _LINT["prettier"][1]
    for excluded in ("'!compose.yaml'", "'!.github/**'", "'!chart/**'"):
        assert excluded in command
