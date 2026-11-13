from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Sequence

from quoll.ci.steps import Item, Step, step
from quoll.ci.tools import install_osv_scanner
from quoll.languages.base import CISteps, TestReports

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

# Ubuntu 24.04 on both platforms (GitHub's runner, GitLab's image): the toolchain comes from its packages.
IMAGE = "ubuntu:24.04"
SOURCES = "'*.c' '*.cc' '*.cpp' '*.cxx' '*.h' '*.hh' '*.hpp' '*.hxx'"
COVERAGE_REGEX = r"/^TOTAL\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%/"

# Installs "<gcc|clang>-<major>" and exports CC, CXX and GCOV (gcovr reads clang's coverage through llvm-cov),
# for the next steps too on GitHub.
_TOOLCHAIN = """compiler="{compiler}"
case "$compiler" in
  gcc-*)
    v="${{compiler#gcc-}}"; packages="gcc-$v g++-$v"; cc="gcc-$v"; cxx="g++-$v"; gcov="gcov-$v" ;;
  clang-*)
    v="${{compiler#clang-}}"; packages="clang-$v llvm-$v"; cc="clang-$v"; cxx="clang++-$v"; gcov="llvm-cov-$v gcov" ;;
  *) echo "Unknown compiler '$compiler' (expected gcc-<major> or clang-<major>)"; exit 1 ;;
esac
sudo=""; [ "$(id -u)" -eq 0 ] || sudo=sudo
$sudo apt-get update -qq
# shellcheck disable=SC2086 # $packages lists several packages
$sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \\
  $packages {tools}
export CC="$cc" CXX="$cxx" GCOV="$gcov"
if [ -n "${{GITHUB_ENV:-}}" ]; then printf 'CC=%s\\nCXX=%s\\nGCOV=%s\\n' "$cc" "$cxx" "$gcov" >> "$GITHUB_ENV"; fi"""

# vcpkg is preinstalled on GitHub's runners; elsewhere it is bootstrapped once per job.
_VCPKG = """if [ -z "${VCPKG_ROOT:-}" ]; then
  if [ -n "${VCPKG_INSTALLATION_ROOT:-}" ]; then
    VCPKG_ROOT="$VCPKG_INSTALLATION_ROOT"
  else
    git clone --quiet --depth 1 https://github.com/microsoft/vcpkg "$HOME/vcpkg"
    "$HOME/vcpkg/bootstrap-vcpkg.sh" -disableMetrics
    VCPKG_ROOT="$HOME/vcpkg"
  fi
fi"""

_CLANG_FORMAT = f"git ls-files -z {SOURCES} | xargs -0 -r clang-format --dry-run --Werror"
# Sources of the project only: FetchContent dependencies are built under build/.
_CLANG_TIDY = 'run-clang-tidy -p build -quiet "^$PWD/(?!build/)"'
_CPPCHECK = (
    "cppcheck --project=build/compile_commands.json -ibuild --enable=warning,style,performance,portability "
    "--inline-suppr --suppress=missingIncludeSystem --error-exitcode=1 --quiet"
)


class CppCI(CISteps):
    version_key = "compiler"
    codeql_language = "c-cpp"
    # CodeQL watches our own configure + build (dependencies included).
    codeql_build_mode = "manual"

    def setup(self, cfg: CIConfig, version: Optional[str]) -> List[Item]:
        return [self._toolchain(cfg, version or cfg.versions[-1])]

    def image(self, cfg: CIConfig, version: str) -> str:
        return IMAGE

    def image_setup(self, cfg: CIConfig) -> List[Step]:
        # In a matrix job, COMPILER is the entry's.
        return [self._toolchain(cfg, f"${{COMPILER:-{cfg.versions[-1]}}}")]

    def install(self, cfg: CIConfig, packages: Sequence[str] = ()) -> List[Item]:
        return [configure(cfg)]

    def lint(self, cfg: CIConfig, tools: List[str]) -> List[Item]:
        steps: List[Item] = []
        if "clang-format" in tools:
            steps.append(step("clang-format", run=_CLANG_FORMAT))
        if "clang-tidy" in tools or "cppcheck" in tools:
            # Both read the compilation database written by the configure step.
            steps.append(configure(cfg))
        if "clang-tidy" in tools:
            steps.append(step("clang-tidy", run=_CLANG_TIDY))
        if "cppcheck" in tools:
            steps.append(step("cppcheck", run=_CPPCHECK))
        return steps

    def test(self, cfg: CIConfig) -> List[Item]:
        t = cfg.test
        meson = cfg.package_manager == "meson"
        env = {}
        if t.sanitizers:
            env = {"ASAN_OPTIONS": "detect_leaks=1:abort_on_error=1", "UBSAN_OPTIONS": "print_stacktrace=1"}
        if meson:
            run = "meson compile -C build\nmeson test -C build --print-errorlogs"
        else:
            run = "cmake --build build\nctest --test-dir build --output-on-failure"
            if t.reports:
                run += " --output-junit junit.xml"
        name = "Tests" + (" with sanitizers" if t.sanitizers else "")
        steps: List[Item] = [configure(cfg, instrumented=True), step(name, run=run, env=env, secrets=t.env_secrets)]
        if t.coverage:
            command = (
                'gcovr --root . --exclude build/ --exclude "(.+/)?tests?/" --gcov-executable "$GCOV" '
                f"--txt --cobertura coverage.xml --fail-under-line {t.coverage_threshold}"
            )
            steps.append(step("Coverage threshold", run=command))
        return steps

    def coverage_file(self, cfg: CIConfig) -> str:
        return "coverage.xml"

    def reports(self, cfg: CIConfig) -> TestReports:
        junit = "build/meson-logs/testlog.junit.xml" if cfg.package_manager == "meson" else "build/junit.xml"
        coverage = cfg.test.coverage
        return TestReports(
            junit=junit,
            cobertura="coverage.xml" if coverage else "",
            coverage_regex=COVERAGE_REGEX if coverage else "",
        )

    def audit(self, cfg: CIConfig) -> List[Item]:
        scan = step("Dependency vulnerability scan", run="osv-scanner scan source -L conan.lock")
        return [install_osv_scanner(), scan]

    def build(self, cfg: CIConfig) -> List[Item]:
        default = "meson compile -C build" if cfg.package_manager == "meson" else "cmake --build build"
        return [configure(cfg, release=True), step("Build", run=cfg.build.command or default)]

    def dependabot_ecosystem(self, cfg: CIConfig) -> str:
        # Dependabot has no ecosystem for CMake, Conan or Meson.
        return ""

    def _toolchain(self, cfg: CIConfig, compiler: str) -> Step:
        tools = ["ca-certificates", "git", "ninja-build"]
        tools.append("meson" if cfg.package_manager == "meson" else "cmake")
        if cfg.package_manager == "conan":
            tools.append("pipx")
        if cfg.package_manager == "vcpkg":
            tools += ["curl", "zip", "unzip", "tar", "pkg-config"]
        if cfg.lint.enabled:
            tools += [{"clang-format": "clang-format", "clang-tidy": "clang-tidy", "cppcheck": "cppcheck"}[t]
                      for t in cfg.lint.tools if t in ("clang-format", "clang-tidy", "cppcheck")]
        if cfg.test.enabled and cfg.test.coverage:
            tools.append("gcovr")
        if cfg.security.audit:
            tools.append("curl")
        tools_list = " ".join(dict.fromkeys(tools))
        if "${{" in compiler:
            # An expression (the setup action's input): through the environment, never pasted into the script.
            run = _TOOLCHAIN.format(compiler="$QUOLL_COMPILER", tools=tools_list)
            return step("Set up the toolchain", run=run, env={"QUOLL_COMPILER": compiler})
        return step("Set up the toolchain", run=_TOOLCHAIN.format(compiler=compiler, tools=tools_list))


def configure(cfg: CIConfig, instrumented: bool = False, release: bool = False) -> Step:
    """Configure the build in build/ (compilation database included), resolving the dependencies.

    `instrumented` adds coverage and sanitizers (tests); `release` builds optimized (build job).
    """
    t = cfg.test
    flags: List[str] = []
    if instrumented and t.coverage:
        flags.append("--coverage")
    if instrumented and t.sanitizers:
        flags.append("-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer")
    build_type = "Release" if release else "Debug"

    if cfg.package_manager == "meson":
        options = [f"--buildtype={build_type.lower()}"]
        if instrumented and t.coverage:
            options.append("-Db_coverage=true")
        if instrumented and t.sanitizers:
            options.append("-Db_sanitize=address,undefined -Dc_args=-fno-sanitize-recover=all "
                           "-Dcpp_args=-fno-sanitize-recover=all")
        return step("Configure", run=f"meson setup build {' '.join(options)}")

    lines: List[str] = []
    args = [f"-DCMAKE_BUILD_TYPE={build_type}", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
    if flags:
        joined = " ".join(flags)
        args += [f'-DCMAKE_C_FLAGS="{joined}"', f'-DCMAKE_CXX_FLAGS="{joined}"']
    if cfg.package_manager == "conan":
        lines += [
            "pipx run conan profile detect --exist-ok",
            f"pipx run conan install . --output-folder=build --build=missing -s build_type={build_type}",
        ]
        args.append("-DCMAKE_TOOLCHAIN_FILE=build/conan_toolchain.cmake")
    elif cfg.package_manager == "vcpkg":
        lines.append(_VCPKG)
        args.append('-DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake"')
    lines.append(f"cmake -S . -B build -G Ninja {' '.join(args)}")
    return step("Configure", run="\n".join(lines))
