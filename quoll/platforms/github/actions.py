"""GitHub Actions used by the generated workflows."""

# Referenced by version here; workflows pin them to the commit SHA below (supply-chain hardening: a tag can be
# moved, a commit can't), with the version as a comment. Dependabot (github-actions ecosystem) proposes updates.
ACTIONS = {
    "checkout": "actions/checkout@v7",
    "setup-python": "actions/setup-python@v7",
    "setup-node": "actions/setup-node@v7",
    "setup-go": "actions/setup-go@v7",
    "setup-java": "actions/setup-java@v6",
    "setup-gradle": "gradle/actions/setup-gradle@v6",
    "setup-dotnet": "actions/setup-dotnet@v6",
    "setup-php": "shivammathur/setup-php@v2",
    "setup-ruby": "ruby/setup-ruby@v1",
    "setup-rust": "actions-rust-lang/setup-rust-toolchain@v2",
    "install-tool": "taiki-e/install-action@v2",
    "cache": "actions/cache@v6",
    # No floating major tag upstream since v8.
    "setup-uv": "astral-sh/setup-uv@v10.3.3",
    "setup-pnpm": "pnpm/action-setup@v6",
    "setup-bun": "oven-sh/setup-bun@v2",
    "golangci-lint": "golangci/golangci-lint-action@v9",
    "codecov": "codecov/codecov-action@v7",
    "setup-buildx": "docker/setup-buildx-action@v4",
    "build-push": "docker/build-push-action@v7",
    "setup-qemu": "docker/setup-qemu-action@v4",
    "metadata": "docker/metadata-action@v6",
    "login": "docker/login-action@v4",
    # No major-version tag upstream: dependabot bumps it.
    "trivy": "aquasecurity/trivy-action@v0.36.0",
    "sonar": "SonarSource/sonarqube-scan-action@v8",
    "codeql-init": "github/codeql-action/init@v4",
    "codeql-analyze": "github/codeql-action/analyze@v4",
    "junit-report": "mikepenz/action-junit-report@v6",
    "upload-artifact": "actions/upload-artifact@v7",
    "attest": "actions/attest@v4",
    "setup-helm": "azure/setup-helm@v5",
}

# Commit of each version above. Refresh with:
#   gh api repos/<owner>/<repo>/commits/<version> --jq .sha
PINS = {
    "SonarSource/sonarqube-scan-action@v8": "59202af334b4ba7b5db01b701b8e79f8b3bef0f4",
    "actions-rust-lang/setup-rust-toolchain@v2": "a188e68d0fd2bd36ad51dccb2b07ba6e75105f30",
    "actions/cache@v6": "55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
    "actions/checkout@v7": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-dotnet@v6": "0f4a354dd5547a28c70b7853dbd95d5b67886e73",
    "actions/setup-go@v7": "b7ad1dad31e06c5925ef5d2fc7ad053ef454303e",
    "actions/setup-java@v6": "b843ebf9b913146b38da2eaa7aeddf76074ae1ad",
    "actions/setup-node@v7": "949feb2413d6458794dcd2491c4babbbce0c15c1",
    "actions/setup-python@v7": "6d4fd22b20465ccc0f7354476588e8df7c9ca0e0",
    "aquasecurity/trivy-action@v0.36.0": "ed142fd0673e97e23eac54620cfb913e5ce36c25",
    "astral-sh/setup-uv@v10.3.3": "68559e99cc807c1eb7e9238fd43a15bba460eec2",
    "codecov/codecov-action@v7": "303a32d7a59b442fa8d48b6a1cc6825c09c847a5",
    "docker/build-push-action@v7": "c3c9e263c25d99ce0380d002d59b67737d91b0dc",
    "docker/login-action@v4": "8aa5831fb8d48d8f76594c7ddde61ae58019f550",
    "docker/metadata-action@v6": "dc802804100637a589fabce1cb79ff13a1411302",
    "docker/setup-buildx-action@v4": "f87e5991a6d7451dcb8d9637bfbc97413f497069",
    "docker/setup-qemu-action@v4": "99012661954931238ded8c8b007157a8430204e1",
    "github/codeql-action/analyze@v4": "33d7b85da1a04171e211befe2c739303b9a4c066",
    "github/codeql-action/init@v4": "33d7b85da1a04171e211befe2c739303b9a4c066",
    "actions/upload-artifact@v7": "cf430e030ddbb5b0abf93d22962f4752f3646cd9",
    "azure/setup-helm@v5": "2f5e7bc67f1f9972ab16657bb795f36d8f04de0e",
    "actions/attest@v4": "1e69f48acb82d1966a394da916b4c1698aa569d6",
    "mikepenz/action-junit-report@v6": "a16be3a69023e9bd7e748ede768b3282ea7b30ce",
    "golangci/golangci-lint-action@v9": "ba0d7d2ec06a0ea1cb5fa41b2e4a3ab91d21278a",
    "gradle/actions/setup-gradle@v6": "8da46b539cd8fe6ab27ca75128919a18d757604c",
    "oven-sh/setup-bun@v2": "0c5077e51419868618aeaa5fe8019c62421857d6",
    "pnpm/action-setup@v6": "73e46992e05b19abd31f2f3c20e0e7370d762115",
    "ruby/setup-ruby@v1": "b3aaceaef7e0ee231b499e7b5f49c03fc1d32199",
    "shivammathur/setup-php@v2": "eb7c497e18156a6bbabfef1d3a82760b9eda3962",
    "taiki-e/install-action@v2": "cfdb7ed4ccc7c7dce37759eae89dc5674b469b39",
}


def gha_cache_scope(project: str) -> str:
    """BuildKit's GitHub Actions cache, one scope per project: a monorepo's images don't evict each other's layers."""
    return f"type=gha,scope={project or 'ci'}"
