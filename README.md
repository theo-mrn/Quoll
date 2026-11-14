# quoll

A CLI that gives any Python, Node, Go, Rust, Java/Kotlin, PHP, Ruby, .NET or C/C++ repository a production-grade CI, Dockerfile and delivery pipeline in one command — on **GitHub Actions or GitLab CI** — and keeps them maintained.

## Install

```bash
pipx install quoll-cli        # or: uv tool install quoll-cli, pip install quoll-cli
quoll --version
```

Python 3.9 or later. Docker is needed for the images, Helm for the charts (only to install them yourself).

## CI

```bash
cd my-project
quoll ci init
```

### Supported stacks

| Language | Package managers | Lint | Tests (coverage threshold) | Frameworks |
|---|---|---|---|---|
| Python | pip, uv, poetry | ruff, ruff format, flake8, black, mypy | pytest | Django, FastAPI, Flask |
| Node.js | npm, pnpm, yarn, bun | eslint, prettier, biome, tsc, any `package.json` script | vitest, jest, bun | Next.js, Nuxt, SvelteKit, Astro, Angular, NestJS |
| Go | go modules | gofmt, go vet, golangci-lint | go test | |
| Rust | cargo | rustfmt, clippy | cargo test, nextest (cargo-llvm-cov) | |
| Java / Kotlin | Maven, Gradle (wrappers supported) | spotless, checkstyle, ktlint, detekt, SpotBugs, PMD | JUnit via `verify` / `check`, JaCoCo coverage | Spring Boot |
| PHP | composer | php-cs-fixer, phpcs, pint, phpstan, psalm, rector | phpunit, pest | Symfony, Laravel |
| Ruby | bundler | rubocop, standard | rspec, minitest (SimpleCov) | Rails |
| .NET | dotnet | dotnet format | dotnet test (coverlet.msbuild) | |
| C / C++ | CMake (plain, Conan, vcpkg), Meson | clang-format, clang-tidy, cppcheck | ctest, meson test (gcovr; ASan + UBSan) | |

Frameworks add what the language alone can't know, for example:

- **Django**: `manage.py check` and a missing-migrations check in the lint job.
- **Symfony**: the console linters (container, YAML, Twig).
- **Rails**: Brakeman, plus preparing the test database.
- **Laravel**: `.env` and app key, then `php artisan test`.
- **Next.js**: build cache.
- **Nuxt, SvelteKit, Astro**: their own type checks instead of plain `tsc`.
- **Angular**: `ng test` with headless Chrome.

### Detection

quoll reads your project instead of asking you about it:

| Detected                | From                                                                          |
|-------------------------|-------------------------------------------------------------------------------|
| Stack                   | `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `pom.xml` / `build.gradle(.kts)`, `composer.json`, `Gemfile`, `*.sln` / `*.csproj`, `CMakeLists.txt` / `meson.build` |
| Framework               | dependencies and entry points (`manage.py`, `bin/console`, `artisan`, `bin/rails`…) |
| Package manager         | lockfiles (`uv.lock`, `poetry.lock`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock`…), `packageManager` |
| Runtime version         | `.python-version`, `requires-python`, `.nvmrc`, `.node-version`, `engines`, `go.mod` |
| Lint tools              | ruff / flake8 / black / mypy config, eslint / prettier / biome / tsconfig, package.json scripts |
| Test runner & coverage  | pytest, vitest (+ coverage plugin), jest, bun, `go test`                      |
| Build                   | `[build-system]`, `build` script, `go build`                                  |
| Branch & repository     | `git` remote and default branch                                               |
| Platform                | the remote's host (github.com, gitlab.com, gitlab.&lt;company&gt;…), else an existing `.gitlab-ci.yml` |

It then asks only what it can't infer (coverage threshold, version matrix, Codecov, SonarCloud…), writes your choices to **`quoll.toml`** and generates the pipeline:

| Platform | Pipeline | Dependency updates (created only if missing) |
|---|---|---|
| GitHub | `.github/workflows/ci.yml` and `.github/actions/quoll-setup` (for your own workflows) | `.github/dependabot.yml` |
| GitLab | `.gitlab-ci.yml` (rules, includes) and `.gitlab/quoll-ci.yml` (jobs) | `renovate.json` |

### Commands

| Command            | What it does                                                                  |
|--------------------|-------------------------------------------------------------------------------|
| `quoll ci init`    | Detect, ask, write `quoll.toml` and the pipeline. `--yes` accepts the detected defaults (scripts, CI), `--platform github\|gitlab` overrides the detection, `--force` replaces a hand-written pipeline, `--local` skips the branch protection and secrets. |
| `quoll ci update`  | Regenerate the pipeline from `quoll.toml`, showing the diff first.           |
| `quoll ci check`   | Exit 1 if the pipeline no longer matches `quoll.toml` — run it in CI or pre-commit. |
| `quoll ci detect`  | Print what quoll detects, without writing anything.                          |
| `quoll ci schedule`| GitLab: create or update the pipeline schedule of the security scans.        |
| `quoll ci eject`   | Stop managing the CI: the files become yours, `[ci]` leaves `quoll.toml`.    |

At the end of `init`, quoll can also, through the platform's API:

- protect the default branch: changes go through pull / merge requests, merged once the pipeline passed — on GitHub the **`CI result`** check (admins included, linear history, no force push); on GitLab no direct push, "Pipelines must succeed" and fast-forward merges. No approval is required by default (authors can't approve their own changes: a single developer would be locked out); a team adds it in the repository's settings;
- store what the pipeline needs (`.env.example` variables used by tests, `SONAR_TOKEN`, `CODECOV_TOKEN`) as GitHub secrets or masked GitLab CI/CD variables.

Tokens come from `QUOLL_GITHUB_TOKEN` / `QUOLL_GITLAB_TOKEN`, `gh auth token` / `glab`, or are asked once and stored in `~/.config/quoll/config.toml`. Self-managed GitLab instances are reached on the remote's host (`QUOLL_GITLAB_URL` for `quoll new --remote`, `QUOLL_GITLAB_GROUP` for the group of new projects).

### The generated pipeline

| Job | What it does |
|---|---|
| **lint** | the language's formatters, linters and static analyzers (ruff/mypy, eslint/tsc, golangci-lint, clippy, phpstan/psalm, rubocop/Brakeman, clang-tidy/cppcheck…) plus the framework's checks |
| **test** | tests against one or several versions (matrix), with the backing services, a coverage threshold, sanitizers for C/C++; results (JUnit) and coverage shown in the pull/merge request |
| **audit** | known vulnerabilities in the dependencies (pip-audit, npm/pnpm/yarn/bun audit, govulncheck, cargo-audit, osv-scanner, composer audit, bundler-audit, `dotnet list package --vulnerable`) |
| **secrets** | gitleaks over the whole git history (allow-list: `.gitleaksignore`) |
| **sast** | Semgrep's default rules for every language of the repository (GitLab: report in the MR security widget) |
| **sbom** | after installing the dependencies: an SBOM (CycloneDX, pipeline artifact; GitLab's dependency list) and a license gate, failing on forbidden licenses (AGPL, SSPL…) by default |
| | *Licenses are read from the installed packages (`node_modules`, `.venv`, `vendor/`…). A free-text license Trivy can't classify counts as `UNKNOWN` (add it to `license_severity` to block those too); dependencies installed outside the project (pip into the system interpreter, Maven/Go caches) are only partly covered.* |
| **codeql** | GitHub CodeQL, results in the Security tab — optional, needs GitHub Advanced Security on private repositories |
| **sonar** | SonarCloud — optional |
| **build** | the project's build (package, binary, static site…); its output (`[ci.build] artifacts`: `dist/`, `target/*.jar`…) kept a week |
| **docker** | when there is a Dockerfile: BuildKit's Dockerfile checks, build, then a Trivy scan failing on fixable `CRITICAL`/`HIGH` vulnerabilities — before the image is ever published |

On GitHub Actions, a final **`CI result`** job is the single required status check, whatever the jobs and matrix entries:

- **Least privilege & hygiene:** `permissions: contents: read`, per-job timeouts, superseded PR runs cancelled, `merge_group` support for merge queues.
- **Reproducible installs:** lockfile-based (`uv sync --locked`, `npm ci`, `pnpm install --frozen-lockfile`…) with dependency caching.
- **Useful output:** linter annotations on the PR (ruff, phpstan, psalm, rubocop), failed tests annotated and listed in the job summary, coverage summary, coverage threshold enforced for every test runner that measures it.
- **Test reports** for every language: pytest, Vitest, Jest (jest-junit, installed outside the project), bun, gotestsum, nextest (`cargo test` has no stable JUnit output), PHPUnit/Pest, RSpec (its JUnit formatter, outside the bundle), Surefire/Gradle, `dotnet test` (TRX converted by trx2junit), CTest/Meson. Cobertura coverage where the runner measures it (Go through gocover-cobertura). Java's coverage: JaCoCo without any build file change (Maven goals, a Gradle init script), the threshold over every module's report.
- **Security:** dependency audit, secret scanning, Semgrep, optional CodeQL; jobs needing secrets (SonarCloud) skipped on fork PRs where they aren't available.
- **Supply chain:** every action pinned to a commit SHA (`actions/checkout@<sha> # v7`), proposed updates by Dependabot; the tool images (gitleaks, Semgrep, Trivy) pinned by version.

On GitLab CI, the same jobs run in the `test` stage, each in the language's official image (`python`, `ghcr.io/astral-sh/uv`, `node`, `oven/bun`, `golang`, `rust`, `eclipse-temurin` / `maven` / `gradle`, `php` + Composer and the `ext-*` the lock file needs, `ruby`, `dotnet/sdk`):

- **Pipelines:** merge requests, pushes to the configured branches, tags and manual runs, without duplicate branch + MR pipelines; a new commit cancels the running pipeline. The pipeline itself is the merge gate.
- **Caches** kept inside the project (`.venv`, `.npm`, `.go`, `.cargo`, `.m2`, `vendor/bundle`…), keyed on the lockfile, per job and matrix entry.
- **Matrix:** `parallel:matrix` over the versions, each entry with its resolved image.
- **Services** started as GitLab services; their variables are exported by the script, so a project CI/CD variable of the same name (which would override job variables) can't point the tests at a real database.
- **Merge request widgets:** test results (JUnit), coverage on the diff (Cobertura) and the total coverage parsed from the log (badge); Semgrep's report in the security widget (Ultimate).
- **Codecov** in its own job reading the test job's report; **SonarCloud** only where `SONAR_TOKEN` is available.
- **Docker layer cache** in the project's registry (`cache:<project>`), shared by the CI's docker job and the delivery; a pipeline without access to the registry (a fork) builds from scratch.
- **Retries** of the jobs lost to the infrastructure (runner, timeout, API) — never of a failing test, which would hide a flaky one.
- Steps that use a GitHub Action on GitHub (golangci-lint, govulncheck, cargo tools, osv-scanner…) run the equivalent CLI here.

### `quoll.toml`

`quoll.toml` is the source of truth: edit it, then run `quoll ci update` (or `quoll docker update`). Every field is validated, with a clear error on typos. `[project]` is shared by the CI and the Docker image, so they can't disagree about the stack.

```toml
[project]
platform = "github"               # github | gitlab
stack = "python"                  # go | rust | java | dotnet | php | ruby | python | node
framework = "django"              # optional, one of the stack's frameworks
package_manager = "uv"            # pip | uv | poetry | npm | pnpm | yarn | yarn-classic | bun | go | ...
services = ["postgres", "redis"]  # postgres | mysql | redis | mongodb — for the CI tests and compose.yaml

[ci]
versions = ["3.12", "3.13"]       # several = test matrix; empty = read version_file (GitHub only)
version_file = ""                 # e.g. ".python-version", ".nvmrc", "go.mod"
install = "uv sync --locked --all-extras"
source_dir = "src"                # measured by coverage, checked by mypy
branches = ["main"]
dependency_updates = true         # Dependabot (GitHub) / Renovate (GitLab) config, created once

[ci.lint]
enabled = true
tools = ["ruff", "mypy", "django-check"] # language + framework tools; node also accepts "script:<name>"

[ci.test]
enabled = true
runner = "pytest"
coverage_threshold = 80
codecov = false
reports = true                    # JUnit results and Cobertura coverage in pull/merge requests
sanitizers = false                # ASan + UBSan (C/C++; detected on)
env_secrets = ["DATABASE_URL"]    # exposed to tests from GitHub secrets / GitLab CI/CD variables

[ci.security]
audit = true                      # dependency vulnerabilities
secrets = true                    # gitleaks
sast = true                       # Semgrep
codeql = false                    # GitHub only
sbom = true                       # CycloneDX SBOM of the dependencies
licenses = true                   # license gate (Trivy)
license_severity = ["CRITICAL"]   # CRITICAL = forbidden (AGPL, SSPL…), HIGH = restricted (GPL, LGPL), MEDIUM = reciprocal (MPL)
sonar = false
sonar_organization = ""

[ci.build]
enabled = true
command = "uv build"
docker = true                     # lint, build and scan the image (on when there is a Dockerfile)
```

### Going beyond what quoll generates

quoll can't know every tool a project needs. The generated pipeline is one part of the CI, not all of it: three levels, pick the one that fits.

**1. `quoll.toml`** — the standard pipeline: versions, tools, thresholds, jobs on or off. Plus `[[ci.steps]]` to add a command, or a GitHub Action, to a generated job:

```toml
[[ci.steps]]
job = "test"                      # lint, test, build, audit or sbom
when = "before"                   # before: once the dependencies are installed; after: at the end
name = "Migrate"
run = "python manage.py migrate"
secrets = ["DJANGO_SECRET_KEY"]   # read from GitHub secrets / GitLab CI/CD variables

[[ci.steps]]                      # GitHub only: any action of the marketplace
job = "test"
when = "after"
name = "Upload screenshots"
uses = "actions/upload-artifact@v4"
with = { name = "screenshots", path = "screenshots/" }
```

Or without writing TOML — the step is added, then the pipeline regenerated:

```bash
quoll ci add-step --job test --when before --name Migrate --run "python manage.py migrate" --secret DJANGO_SECRET_KEY
quoll ci add-step -d back     # in a workspace: the project's directory; asks what's missing
```

**Keeping the files in sync**: `quoll ci check` (and `docker check`, `cd check`) fails when a generated file no longer matches `quoll.toml`. With [pre-commit](https://pre-commit.com), quoll's hooks regenerate them when a `quoll.toml` changes:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/theo-mrn/Quoll
    rev: v0.2.0
    hooks:
      - id: quoll-ci          # quoll ci update; also quoll-docker, quoll-cd
```

**2. Your own CI, in plain YAML, next to quoll's** — any tool, any action, any runner. quoll gives it the project's environment so you don't rebuild the toolchain setup:

- **GitHub**: write your workflows in `.github/workflows/` (quoll only owns `ci.yml`), and start your jobs with the generated action:

  ```yaml
  steps:
    - uses: actions/checkout@v4
    - uses: ./.github/actions/quoll-setup   # toolchain, caches, dependencies — as quoll's CI
      with: { version: "3.13" }             # optional
    - uses: microsoft/playwright-github-action@v1
    - run: npx playwright test
  ```

- **GitLab**: write `.gitlab/custom-ci.yml`, included last. Your jobs extend the generated `.quoll-setup` template, and any key of quoll's jobs can be overridden there (maps such as `variables` are merged, lists such as `script` replaced):

  ```yaml
  e2e:
    extends: .quoll-setup                 # image, caches, dependencies
    script: [npx playwright test]

  test:                                   # quoll's test job, completed
    tags: [gpu]
    timeout: 45 minutes
    variables: { FEATURE_FLAGS: "on" }
  ```

**3. `quoll ci eject`** — the pipeline files become yours, as they are (quoll's header removed), and `[ci]` leaves `quoll.toml`. quoll stops managing the CI; the Docker image and the delivery stay managed.

### Scheduled security scans

New vulnerabilities appear without any code change. Every week, the audit, secret scanning, Semgrep, CodeQL, SBOM/licenses and image scan run again on the default branch (lint, tests and build don't):

```toml
[ci.schedule]
enabled = true
cron = "0 6 * * 1"                # UTC — Mondays at 06:00
```

On GitHub the schedule is part of the workflow. On GitLab it is a pipeline schedule, created by `quoll ci init` (or `quoll ci schedule` after changing the cron) through the API. A failed scheduled run notifies like any failed pipeline.

## Monorepos

A repository holding several projects — a Next.js front-end and a FastAPI back-end, services in Go and Java… — is a **workspace**. `quoll ci init` at its root finds them (first-level directories, and `apps/*`, `packages/*`, `services/*`) and sets it up:

```
shop/
├── quoll.toml              # the workspace: its members, and what they share
├── backend/quoll.toml      # a project, in the single-project format: [project], [ci], [docker], [cd]
└── frontend/quoll.toml
```

```toml
# quoll.toml at the root
[project]
platform = "github"

[workspace]
members = ["backend", "frontend"]

[ci]                              # the repository's: triggers and repository-wide scans
branches = ["main"]

[ci.schedule]
cron = "0 6 * * 1"

[ci.security]
secrets = true                    # gitleaks, once for the whole repository
sast = true                       # Semgrep, once
```

Each member keeps the single-project format, so a project moved out of the repository stays a valid quoll project. In a workspace its `branches`, `schedule`, `secrets` and `sast` are the root's.

- **One pipeline**: every member's jobs, prefixed by its name (`backend-test`, `frontend-lint`…) and run in its directory; on GitHub, one `CI result` gate for all.
- **Only what changed runs**: a pull request touching `frontend/` doesn't run the back-end's jobs. A change to the root `quoll.toml` or to the CI runs everything, as do tags, scheduled and manual runs. GitLab uses `rules: changes`; GitHub a `changes` job (plain `git diff`, no third-party action).
- **Per member**: Dockerfile, `compose.yaml`, image and delivery (`quoll docker init` / `quoll cd init` at the root do every member). GitHub: one `cd-<member>.yml` per image, run when its directory changed; GitLab: `<member>-publish` jobs, and one release carrying every SBOM.
- **A root `compose.yaml`** running every member and their databases together: see [Microservices](#microservices).
- **Building blocks**: `.github/actions/quoll-setup-<member>` / `.quoll-setup-<member>` for your own jobs.
- Every command works from the root or from a member's directory.

## Docker

```bash
quoll docker init       # detect, ask the port / start command if needed, write Dockerfile, .dockerignore, compose.yaml
quoll docker update     # regenerate from quoll.toml, showing the diff first
quoll docker check      # exit 1 if the Dockerfile no longer matches quoll.toml
```

Every image is multi-stage, runs as a non-root user, installs dependencies from the lockfile in their own cached layer (BuildKit cache mounts) and ships only what runs. Runtime images on Debian, Ubuntu or Alpine get the OS security fixes released since their base image was built (distroless ones have no package manager: rebuilding picks up Google's). Each framework gets an image that fits it:

| Stack | Build | Runtime image |
|---|---|---|
| Python (pip, uv, poetry) | virtualenv built in a builder stage | `python:<v>-slim`; gunicorn for Django and Flask, uvicorn for FastAPI (app module found in the code) |
| Node | lockfile install, build, devDependencies pruned | `node:<v>-slim`, or `oven/bun` |
| Next.js | `output: "standalone"` when enabled | only the standalone server, `.next/static` and `public/` |
| Nuxt | Nitro build | only `.output/` |
| Vite SPA, Angular, Astro, SvelteKit (static) | static build | `nginx-unprivileged` with SPA fallback (or 404 page) |
| SvelteKit / Astro (node adapter), Angular SSR, NestJS | build | Node server |
| Go | static binary (`CGO_ENABLED=0`, trimmed) | `distroless/static:nonroot` |
| Rust | release binary (system OpenSSL when needed) | `distroless/cc:nonroot` |
| Java / Kotlin | Maven/Gradle, wrapper or official image | `eclipse-temurin:<v>-jre`; Spring Boot jar extracted into cache-friendly layers |
| PHP, Symfony, Laravel | Composer without dev dependencies, optimized autoloader, framework scripts | FrankenPHP with the `ext-*` from composer.json |
| Ruby, Rails | Bundler deployment mode, system packages for native gems (pg, mysql2, vips) | `ruby:<v>-slim`; Rails: bootsnap, asset precompilation, `bin/docker-entrypoint`, writable dirs only |
| .NET | `dotnet publish` of the app project | `aspnet` or `runtime`, built-in non-root user |
| C / C++ | CMake or Meson release build (Conan / vcpkg dependencies), libstdc++ linked statically | `distroless/cc:nonroot` |

```toml
[docker]
version = "3.13"                  # runtime version of the base image
port = 8000
command = "gunicorn shop.wsgi --bind 0.0.0.0:8000"  # what the container runs
build_command = ""                # build step, e.g. "npm run build"
output_dir = ""                   # what the build produces (static site or self-contained server)
static = false                    # serve output_dir with nginx
```

## Services

quoll reads which databases and caches the app talks to from its client libraries:

| Service | Detected from (examples) |
|---|---|
| Postgres | psycopg, asyncpg, pg, Prisma `provider = "postgresql"`, pgx, sqlx, org.postgresql, pdo_pgsql, Symfony/Laravel `.env`, pg gem, Npgsql |
| MySQL | mysqlclient, mysql2, go-sql-driver, mysql-connector, pdo_mysql, trilogy, MySqlConnector |
| Redis | redis, ioredis, go-redis, jedis/lettuce, predis, StackExchange.Redis |
| MongoDB | pymongo, mongoose, mongo-driver, mongoid, MongoDB.Driver |

They are listed in `[project] services` and used twice:

- **CI**: the test job starts them as service containers and waits until they are healthy. It sets `DATABASE_URL`, `REDIS_URL`, `MONGODB_URI` and the `PG*` variables, plus the framework's own: Laravel's `DB_*`, Spring's `SPRING_DATASOURCE_*`, `mysql2://` for Rails. A GitHub secret or GitLab CI/CD variable with the same name is never used for tests.
- **compose.yaml** (written by `quoll docker init`): the app plus its services, with healthchecks, `depends_on: service_healthy`, persistent volumes and an optional `.env` for secrets. `docker compose up --build` runs everything.

## Delivery (CD)

```bash
quoll cd init           # registry, image name → .github/workflows/cd.yml or .gitlab/cd.yml
quoll cd update / check
```

Every push to the default branch and every `v*` tag:

1. builds the image (BuildKit);
2. **scans it with Trivy before anything is pushed**, failing on fixable `CRITICAL`/`HIGH` vulnerabilities;
3. pushes it with tags `:<branch>`, `:sha-<sha>`, `:latest` (default branch) and `:1.2.3` / `:1.2` (release tags), plus BuildKit's provenance and SBOM attestations;
4. generates the SBOM of the pushed digest (CycloneDX, pipeline artifact) and, on `v*` tags, attaches it to the GitHub / GitLab release;
5. signs the image and its SBOM with Sigstore: GitHub artifact attestations (`gh attestation verify oci://<image> --owner <org>`), cosign keyless on GitLab (`cosign verify <image> --certificate-identity-regexp … --certificate-oidc-issuer https://gitlab.com`).

| | GitHub | GitLab |
|---|---|---|
| Pipeline | `.github/workflows/cd.yml` | `.gitlab/cd.yml`, included by quoll's `.gitlab-ci.yml` |
| Runs after CI | through branch protection | always: its `publish` stage starts once every CI job passed |
| Default registry (no secret) | GHCR, with the workflow's token | the project's container registry, with the job token |
| Build | Buildx, GitHub Actions cache | Docker-in-Docker, a Buildx container builder; Trivy runs next to the image |
| Signature | artifact attestations (public repositories, or GitHub Enterprise Cloud for private ones) | cosign keyless with the job's OIDC token (gitlab.com: Sigstore's public instance doesn't trust self-managed issuers) |

Docker Hub (`registry = "dockerhub"`) needs `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. Multi-arch images are a `platforms` entry away.

```toml
[cd]
registry = "ghcr"                 # ghcr (GitHub) | gitlab (GitLab) | dockerhub
image = "ghcr.io/acme/api"
branches = ["main"]
release_tags = true
platforms = ["linux/amd64"]       # e.g. ["linux/amd64", "linux/arm64"]
scan = true
severity = ["CRITICAL", "HIGH"]
ignore_unfixed = true
sbom = true                       # SBOM of the image: artifact + release asset
sign = true                       # Sigstore signature and attestations (set false on a private repo without GitHub Enterprise)
```

On GitHub, branch protection (set by `quoll ci init`) makes sure only commits that passed CI reach the default branch, and therefore the registry.

## Kubernetes

```bash
quoll k8s init          # [k8s] in quoll.toml, a Helm chart per project; the CI checks it, the delivery deploys it
quoll k8s update        # regenerate from quoll.toml, showing the diff first
quoll k8s check         # exit 1 if a chart no longer matches quoll.toml
```

Each project gets a Helm chart in `chart/`. The templates are the same everywhere; the values come from `quoll.toml`:

```
back/chart/
├── Chart.yaml
├── values.yaml                 # image, port, health check, resources, URLs of the other projects…
├── values-staging.yaml         # what an environment changes: replicas, public host
├── values-production.yaml
└── templates/                  # Deployment, Service, ServiceAccount, Ingress, PodDisruptionBudget, HPA
```

```toml
[k8s]
name = "back"                     # release, Service and Deployment: the others reach it at http://back:3000
health_path = "/health"           # found in the code (/health, /healthz…); empty: TCP checks on the port
cpu = "100m"                      # requests; memory_limit caps the memory (no CPU limit: no throttling)
memory = "256Mi"
memory_limit = "512Mi"
max_replicas = 0                  # > 0: a HorizontalPodAutoscaler up to this
ingress_class = ""                # the cluster's default
cluster_issuer = ""               # cert-manager ClusterIssuer for the TLS certificate
secret = ""                       # Secret with the app's secrets (DATABASE_URL…), default "<name>-env"

[k8s.environments.staging]
namespace = "shop-staging"
deploy_on = "branch"              # every push to the [cd] branches
host = "api.staging.example.com"  # Ingress; empty: reachable inside the cluster only
replicas = 1

[k8s.environments.production]
namespace = "shop"
deploy_on = "tag"                 # v* tags, after an approval
replicas = 2
```

**Secure by default** — the pods run as non-root (every image's user is numeric, so Kubernetes can check it), with a read-only root filesystem (the directories the app writes to — `/tmp`, nginx's cache, Next.js' `.next/cache`… — are `emptyDir` volumes; Laravel, Symfony and Ruby apps keep a writable one: the frameworks write in their own tree, and Ruby refuses `emptyDir`'s world-writable temporary directory), all capabilities dropped, no privilege escalation, `RuntimeDefault` seccomp, no service account token. Rolling updates never remove a ready pod before its replacement is; with two replicas or more, a PodDisruptionBudget keeps one through node drains.

**In the CI**, a `chart` job lints the chart with each environment's values, checks the rendered manifests against Kubernetes' schemas (kubeconform) and scans them for misconfigurations (Trivy), failing on `HIGH`/`CRITICAL`.

**In the delivery** (with `quoll cd`), once the image is pushed, scanned and signed, a job per environment deploys it **by digest** — what was scanned is what runs:

| | GitHub | GitLab |
|---|---|---|
| Staging | `deploy-staging`, on pushes to the delivered branches | `deploy-staging` (stage `deploy`), same |
| Production | `deploy-production`, on `v*` tags — protect the `production` environment with required reviewers | `deploy-production`, on `v*` tags, started by hand (protect the environment to choose who can) |
| Cluster access | `KUBECONFIG` secret of each GitHub environment (the kubeconfig's content) | `KUBECONFIG` CI/CD variable of type *File*, scoped to each environment |
| Before deploying | the image's provenance: `gh attestation verify` | its signature: `cosign verify` (this project's pipelines) |
| Deploying | `helm upgrade --install --rollback-on-failure`: waits until the release is ready, rolls it back otherwise | same |

The app's secrets live in the cluster: `kubectl create secret generic back-env --from-env-file=.env.production -n shop`. A private image needs a pull secret (`pull_secret` in `[k8s]`).

In a **workspace**, every project deploys to the same namespaces and reaches the others at their Service, `<NAME>_URL=http://<name>:<port>` — the same variables as the root `compose.yaml`, so the front-end's `/api/` proxy works unchanged. `quoll add service` gives a new service its chart (same namespaces), `quoll remove service` drops it from the others' values. `quoll new --k8s` sets it all up from the start.

## Creating a project

```bash
quoll new                                    # interactive
quoll new shop --front angular --back express
quoll new shop --front react --back fastapi --python 3.13
quoll new shop --front nextjs --back go
quoll new shop --front angular@18 --back express@4 --node 20 --platform gitlab --cd --k8s --remote
quoll new shop --front angular --back none --service orders=express --service users=express@4
```

From nothing to a repository whose pipeline passes on its first push:

1. creates the front-end in `front/`, the back-end in `back/` and each `--service` in `services/<name>/` (only one of them: the repository is the project);
2. writes, for each, its Dockerfile and `compose.yaml`; then the workspace's CI, its root `compose.yaml`, with `--k8s` a Helm chart each, and with `--cd` the delivery (which then deploys them);
3. `git init`, a first commit — and with `--remote`, the GitHub/GitLab repository, pushed, `main` protected.

| Starter | Role | How |
|---|---|---|
| `angular` | front | Angular's own CLI (`ng new`) at the chosen major — `angular@18` — plus ESLint (angular-eslint) |
| `react` | front | Vite's own generator (`create-vite`, TypeScript), React's major with `react@18`; Vitest + Testing Library, Prettier |
| `nextjs` | front | Next.js' own generator (`create-next-app`: App Router, ESLint, Tailwind), `nextjs@15`; standalone build, Vitest, Prettier |
| `express` | back | quoll's template: Express (`express@4` for 4) and TypeScript, Vitest + Supertest, ESLint, `/health`, graceful shutdown |
| `fastapi` | back | quoll's template: FastAPI with uv, pytest (TestClient), ruff, `/health` |
| `go` | back | quoll's template: the standard library's `net/http` (Go 1.22+ routing), httptest, graceful shutdown, `/health` |

**Versions.** `name@version` picks the framework's major; `--node 22`, `--python 3.13`, `--go 1.26` the runtime: the generators then run in that runtime's image (so the dependencies and the lockfile match it), and `.nvmrc`, `.python-version` or `go.mod` make the CI and the Dockerfile use it too. A version its maintainers no longer support is flagged at creation: the CI's dependency audit would fail on its known vulnerabilities.

### Microservices

```bash
quoll add service billing=express            # services/billing/, from the root or any member
quoll add service billing=express --in apps  # apps/billing/
```

`quoll add service` creates the project, its Dockerfile and `quoll.toml`, adds it to `[workspace] members`, and regenerates what depends on the members: the pipeline (`billing-lint`, `billing-test`, `billing-docker`…), the root `compose.yaml`, Dependabot's config (unless edited by hand) and, when the other members publish images, its own delivery. Files you wrote yourself are left alone, with a warning.

```bash
quoll remove service billing                 # deletes services/billing/ (asks first; -y doesn't)
quoll remove service billing --keep-files    # only takes it out of the workspace
```

`quoll remove service` does the opposite: the project leaves the members, its jobs, its compose service and `BILLING_URL`, its delivery and setup action are removed. It refuses to delete a directory with uncommitted changes.

**Front-end → API.** With a front-end and a back-end, `quoll new` makes the front-end call the API on its own origin, at `/api/` (no CORS, no URL baked into the build). In development, the dev server forwards there (`proxy.conf.json` for Angular, Vite's `server.proxy`); deployed, to the URL in `BACK_URL`, which the root `compose.yaml` and the charts set — through nginx for a static site, through Next.js' own `proxy.ts` (read on each request) for Next.js:

```toml
# front/quoll.toml
[docker.proxy]
"/api/" = "BACK_URL"              # path prefix = environment variable holding the API's URL (no path)
```

Without `BACK_URL`, the container stops at startup saying what to set (in production: the API's address in your platform).

The root `compose.yaml` (written by `quoll docker init|update` in a workspace, checked by `quoll docker check`) runs the whole platform with `docker compose up --build`:

- every member on one network, each reaching the others at `<NAME>_URL` (`BILLING_URL=http://billing:3000`), and listening on its own host port (3000, 3001… when they share one);
- **one** instance of each backing service, with **a database per member** on it (`orders`, `users`…, Postgres and MySQL), created by a one-shot container at every `up` when missing — so a service added later gets its own too; Redis and MongoDB are shared as they are;
- each member's `.env` (optional) for its secrets.

**Adding a starter** is a plugin's business: a `Starter` in its `starters=(...)`, either a generator (`starter.py` calling the framework's CLI through `quoll.starters.run`, which uses the local tool or a container) or a template directory next to the plugin (`templates/<name>/`, copied with `{{name}}`, `{{version}}`, `{{runtime}}` filled in, then commands such as `npm install`).

`quoll new` replaces the scaffolding of 0.1.x (`quoll init`, `quoll create-project`, `quoll list-types`), removed.

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest            # validates every generated workflow with actionlint, every GitLab pipeline with its schema
.venv/bin/quoll ci check    # quoll's own CI is generated by quoll

QUOLL_DOCKER_TESTS=check .venv/bin/pytest tests/docker   # + lint every Dockerfile with `docker build --check`
QUOLL_DOCKER_TESTS=build .venv/bin/pytest tests/docker   # + build and run real apps for each stack (slow)
QUOLL_GITLAB_TESTS=run .venv/bin/pytest tests/platforms  # + run real projects' GitLab pipelines with gitlab-ci-local (slow)
```

### Architecture

Everything language-, framework- or platform-specific lives in its own folder; the rest of quoll never names one.

```
quoll/
├── project.py                 # safe file access for detectors (missing = empty, invalid = warning)
├── languages/
│   ├── __init__.py            # registry: built-ins + third-party plugins (entry points)
│   ├── base.py                # the contract: Language, Framework, Detection, CISteps, FrameworkCI, DockerImage
│   ├── python/
│   │   ├── __init__.py        # `language = Language(...)`: markers, package managers, tools, frameworks
│   │   ├── detect.py          # Project -> Detection
│   │   ├── ci.py              # CIConfig -> neutral steps (install, lint, test, audit, build) + toolchain:
│   │   │                      #   setup actions (GitHub), image and cache (GitLab)
│   │   ├── docker.py          # DockerImage: defaults (port, command...) and template context
│   │   ├── Dockerfile.j2      # multi-stage template, split into blocks (build, runtime...)
│   │   └── frameworks/
│   │       └── django/
│   │           ├── __init__.py  # `framework = Framework(...)`: extra lint tools / test runners
│   │           ├── detect.py    # (Project, Detection) -> bool, refining the detection
│   │           ├── ci.py        # FrameworkCI: only the hooks it needs (env, lint, test, before_build)
│   │           └── docker.py    # subclass of the language's image (+ a Dockerfile.j2 extending it if needed)
│   ├── node/  go/  rust/  java/  php/  ruby/  dotnet/  cpp/
├── platforms/
│   ├── base.py                # the contract: Platform (pipelines), PlatformAPI (repo, secrets, protection)
│   ├── github/                # workflows, gate job, dependabot, build → scan → push, REST API
│   └── gitlab/                # .gitlab-ci.yml, renovate.json, .gitlab/cd.yml, REST API
├── workspace.py               # monorepos: members, the repository's settings (Repo), discovery
├── ci/                        # [ci] config, detection, the neutral Step / Cache model (steps.py), and the
│                              #   language-independent tools: gitleaks, Semgrep, image checks (tools.py)
├── docker/                    # language-agnostic: [docker] config, Dockerfile, .dockerignore, compose.yaml
├── cd/                        # [cd] config
├── k8s/                       # [k8s] config, the Helm chart (fixed templates + generated values), its CI checks
│                              #   and deploy commands, shared by both platforms
├── services.py                # postgres, mysql, redis, mongodb: containers, healthchecks, app variables
└── config/quoll_toml.py       # quoll.toml: shared [project] section + one section per feature
```

### Adding a language

1. Create `quoll/languages/<name>/` with:
   - `detect.py`: a `detect(project) -> Detection` function, which also fills `services` from the client libraries (`quoll.services.detect_services`);
   - `ci.py`: a `CISteps` subclass. `setup` installs the toolchain on GitHub, `image` (and optionally `image_setup`, `cache`) provides it on GitLab; every other step that uses a GitHub Action also gives the equivalent `run` command;
   - `docker.py` and `Dockerfile.j2`: a `DockerImage` subclass and its template;
   - `__init__.py`: exposes `language = Language(...)`.
2. Add `<name>` to `_BUILTIN` in `quoll/languages/__init__.py`. Its position sets the detection priority.
3. Add a sample project to `SAMPLE_BY_LANGUAGE` in `tests/samples.py` and the language's own tests to `tests/languages/test_<name>.py`.

### Adding a framework

1. Create `quoll/languages/<language>/frameworks/<name>/` with:
   - `detect.py`: returns True when the framework is used, and may adjust the detection;
   - `ci.py` (optional): a `FrameworkCI` subclass overriding only the hooks it needs;
   - `docker.py` (optional): a subclass of the language's image overriding `defaults` or `context`. Add a `Dockerfile.j2` only if the image differs: it starts with `{% extends "<language>/Dockerfile.j2" %}` and overrides only the blocks that change;
   - `services.py` (optional): a `service_env(service, host)` function, when the framework reads its database settings from its own variables;
   - `__init__.py`: exposes `framework = Framework(...)`.
2. List it in the language's `frameworks=(...)`. Order sets the detection priority.
3. Add a sample project to `SAMPLE_BY_FRAMEWORK`.

The contract tests (`tests/languages/test_contract.py`) then check that every sample is detected correctly. They also render the pipelines of both platforms for every declared package manager, lint tool and test runner, and validate each one (actionlint, GitLab's schema). quoll.toml validation, `quoll ci detect`, the prompts and dependabot pick up new languages and frameworks automatically.

A separate package can also ship a language or a framework without changing quoll:

```toml
# pyproject.toml of the plugin
[project.entry-points."quoll.languages"]
elixir = "quoll_elixir:language"

[project.entry-points."quoll.frameworks"]
remix = "quoll_remix:framework"      # Framework(language="node", ...)
```

## Requirements

- Python 3.9+
- A GitHub or GitLab repository (optional, for branch protection and secrets)
