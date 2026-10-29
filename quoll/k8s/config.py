"""The [k8s] section of quoll.toml — the single source of truth for the generated Helm chart and its deployment."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from pydantic import Field, model_validator

from quoll.config.quoll_toml import CONFIG_FILE, ConfigError, Section, load_section, save_section

__all__ = ["CONFIG_FILE", "ConfigError", "Environment", "K8sConfig", "load_config", "save_config"]

# What deploys an environment: every push to the [cd] branches, or the v* tags (after a manual approval).
TRIGGERS = ("branch", "tag")
_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class Environment(Section):
    # Created when missing. Every project of a workspace deploys to the same one, so that they reach each other.
    namespace: str
    deploy_on: str = "branch"
    # Public host of the Ingress, e.g. "api.example.com". Empty: reachable inside the cluster only.
    host: str = ""
    replicas: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _check(self) -> "Environment":
        if self.deploy_on not in TRIGGERS:
            raise ValueError(f"deploy_on must be one of: {', '.join(TRIGGERS)}")
        if not _NAME.match(self.namespace):
            raise ValueError(f"namespace '{self.namespace}' isn't a valid Kubernetes name (lowercase, digits, -)")
        return self


class K8sConfig(Section):
    # Helm release, Service and Deployment name: the other projects reach this one at http://<name>:<port>.
    name: str
    # Directory of the Helm chart, in the project.
    chart: str = "chart"
    # HTTP path answering 200 once the app is up, e.g. "/health". Empty: TCP checks on the port.
    health_path: str = ""
    cpu: str = "100m"
    memory: str = "256Mi"
    memory_limit: str = "512Mi"
    # HorizontalPodAutoscaler between an environment's replicas and this (0: off).
    max_replicas: int = Field(default=0, ge=0)
    # Ingress: the cluster's default class when empty; TLS certificate from cert-manager when cluster_issuer is set.
    ingress_class: str = ""
    tls: bool = True
    cluster_issuer: str = ""
    # Plain environment variables (secrets go in the Secret `secret`, created in the cluster).
    env: Dict[str, str] = Field(default_factory=dict)
    # Secret holding the app's secrets as environment variables. Empty: "<name>-env".
    secret: str = ""
    # Secret to pull a private image with (a docker-registry Secret in the namespace).
    pull_secret: str = ""
    environments: Dict[str, Environment] = Field(default_factory=dict)

    omit_when_empty = ("env",)

    @model_validator(mode="after")
    def _check(self) -> "K8sConfig":
        if not _NAME.match(self.name):
            raise ValueError(f"name '{self.name}' isn't a valid Kubernetes name (lowercase, digits, -)")
        if self.health_path and not self.health_path.startswith("/"):
            raise ValueError("health_path should start with /, e.g. /health")
        return self

    @property
    def secret_name(self) -> str:
        return self.secret or f"{self.name}-env"

    def deployed_on(self, trigger: str) -> List[str]:
        return [name for name, env in self.environments.items() if env.deploy_on == trigger]


def default_environments(project: str) -> Dict[str, Environment]:
    """Staging on every push to the delivered branches, production on v* tags."""
    return {
        "staging": Environment(namespace=f"{project}-staging"),
        "production": Environment(namespace=project, deploy_on="tag", replicas=2),
    }


def kubernetes_name(value: str) -> str:
    """`value` as a Kubernetes name: lowercase letters, digits and dashes."""
    name = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return name[:53] or "app"


def load_config(project_dir: Path) -> K8sConfig:
    return load_section(project_dir, "k8s", K8sConfig)


def save_config(project_dir: Path, config: K8sConfig) -> Path:
    return save_section(project_dir, "k8s", config)
