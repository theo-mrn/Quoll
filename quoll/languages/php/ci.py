from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from quoll.ci.steps import ROOT, Cache, Item, Step, on_github, step
from quoll.languages.base import THRESHOLD_REGEX, CISteps, TestReports
from quoll.platforms.github.actions import ACTIONS

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

# tool: (step name, command, flag printing GitHub annotations)
_LINT = {
    "php-cs-fixer": ("PHP CS Fixer", "vendor/bin/php-cs-fixer fix --dry-run --diff", ""),
    "phpcs": ("PHP_CodeSniffer", "vendor/bin/phpcs", ""),
    "pint": ("Pint", "vendor/bin/pint --test", ""),
    "phpstan": ("PHPStan", "vendor/bin/phpstan analyse --no-progress", " --error-format=github"),
    "psalm": ("Psalm", "vendor/bin/psalm --no-progress", " --output-format=github"),
    "rector": ("Rector", "vendor/bin/rector process --dry-run --no-progress-bar", ""),
}

# PHPUnit has no CLI threshold: read the line rate from its Clover report.
_CLOVER_CHECK = """php -r '
$m = simplexml_load_file("coverage.xml")->project->metrics;
$pct = (int) $m["statements"] ? 100 * (int) $m["coveredstatements"] / (int) $m["statements"] : 100;
$summary = getenv("GITHUB_STEP_SUMMARY");
if ($summary) file_put_contents($summary, sprintf("### Coverage: %.1f%%\\n", $pct), FILE_APPEND);
if ($pct < {threshold}) {{ printf("::error::Coverage %.1f%% is below the {threshold}%% threshold\\n", $pct); exit(1); }}
printf("Coverage %.1f%% (threshold {threshold}%%)\\n", $pct);'"""

# The official images have neither Composer nor most extensions: install them, then the ext-* the lock file needs.
_EXTENSIONS = """curl -sSLf -o /usr/local/bin/install-php-extensions \\
  https://github.com/mlocati/docker-php-extension-installer/releases/latest/download/install-php-extensions
chmod +x /usr/local/bin/install-php-extensions
install-php-extensions @composer zip{coverage}
if [ -f composer.lock ]; then
  # Exits 2 when something is missing, which is the point here (the runner sets pipefail).
  missing=$({{ composer check-platform-reqs --lock --no-interaction 2>/dev/null || true; }} \\
    | awk '$1 ~ /^ext-/ && /missing/ {{ sub("ext-", "", $1); print $1 }}')
  if [ -n "$missing" ]; then install-php-extensions $missing; fi
fi"""


class PhpCI(CISteps):
    version_key = "php-version"

    def setup(self, cfg: CIConfig, version: Optional[str]) -> List[Item]:
        with_: Dict[str, Any] = (
            {"php-version": version} if version else {"php-version-file": cfg.path(cfg.version_file)}
        )
        with_["coverage"] = "pcov" if cfg.test.enabled and cfg.test.coverage else "none"
        with_["tools"] = "composer:v2"
        steps = [step("Set up PHP", uses=ACTIONS["setup-php"], with_=with_)]
        if cfg.cache:
            steps += [
                step(
                    "Get Composer cache directory",
                    id_="composer-cache",
                    run='echo "dir=$(composer config cache-files-dir)" >> "$GITHUB_OUTPUT"',
                ),
                step(
                    "Cache Composer packages",
                    uses=ACTIONS["cache"],
                    with_={
                        "path": "${{ steps.composer-cache.outputs.dir }}",
                        "key": "${{ runner.os }}-composer-${{ hashFiles('**/composer.lock') }}",
                        "restore-keys": "${{ runner.os }}-composer-",
                    },
                ),
            ]
        return steps

    def image(self, cfg: CIConfig, version: str) -> str:
        return f"php:{version}-cli"

    def image_setup(self, cfg: CIConfig) -> List[Step]:
        coverage = " pcov" if cfg.test.enabled and cfg.test.coverage else ""
        return [step("Install Composer and PHP extensions", run=_EXTENSIONS.format(coverage=coverage))]

    def cache(self, cfg: CIConfig) -> Optional[Cache]:
        if not cfg.cache:
            return None
        env = {"COMPOSER_CACHE_DIR": f"{ROOT}/.cache/composer"}
        return Cache("composer", (".cache/composer",), key_files=("composer.lock",), env=env)

    def install(self, cfg: CIConfig, packages: Sequence[str] = ()) -> List[Item]:
        return [step("Install dependencies", run=cfg.install)]

    def lint(self, cfg: CIConfig, tools: List[str]) -> List[Item]:
        steps = self.install(cfg)
        for tool in tools:
            name, cmd, github = _LINT[tool]
            steps.append(step(name, run=cmd + on_github(cfg, github)))
        return steps

    def test(self, cfg: CIConfig) -> List[Item]:
        t = cfg.test
        if t.runner == "pest":
            cmd = "vendor/bin/pest"
            if t.coverage:
                cmd += f" --coverage --min={t.coverage_threshold} --coverage-clover coverage.xml"
            cmd += report_flags(cfg)
            name = "Tests" + (" with coverage" if t.coverage else "")
            return [*self.install(cfg), step(name, run=cmd, secrets=t.env_secrets)]
        if not t.coverage:
            cmd = "vendor/bin/phpunit" + report_flags(cfg)
            return [*self.install(cfg), step("Tests", run=cmd, secrets=t.env_secrets)]
        cmd = "vendor/bin/phpunit --coverage-clover coverage.xml" + report_flags(cfg)
        return [
            *self.install(cfg),
            step("Tests with coverage", run=cmd, secrets=t.env_secrets),
            step("Coverage threshold", run=clover_check(t.coverage_threshold)),
        ]

    def coverage_file(self, cfg: CIConfig) -> str:
        return "coverage.xml"

    def reports(self, cfg: CIConfig) -> TestReports:
        coverage = cfg.test.coverage
        # PHPUnit prints the threshold line of clover_check; Pest and `artisan test` their own total.
        regex = THRESHOLD_REGEX if cfg.test.runner == "phpunit" else r"/Total:\s+(\d+(?:\.\d+)?) ?%/"
        return TestReports(
            junit="junit.xml",
            cobertura="cobertura.xml" if coverage else "",
            coverage_regex=regex if coverage else "",
        )

    def audit(self, cfg: CIConfig) -> List[Item]:
        return [step("Dependency vulnerability scan", run="composer audit --locked --no-dev")]

    def build(self, cfg: CIConfig) -> List[Item]:
        return [*self.install(cfg), step("Build", run=cfg.build.command)]

    def dependabot_ecosystem(self, cfg: CIConfig) -> str:
        return "composer"


def report_flags(cfg: CIConfig) -> str:
    """PHPUnit (and Pest, Laravel's `artisan test`) options writing the JUnit and Cobertura reports."""
    if not cfg.test.reports:
        return ""
    return " --log-junit junit.xml" + (" --coverage-cobertura cobertura.xml" if cfg.test.coverage else "")


def clover_check(threshold: int) -> str:
    return _CLOVER_CHECK.format(threshold=threshold)
