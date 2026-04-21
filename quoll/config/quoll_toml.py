"""quoll.toml: a shared [project] section plus one section per feature ([ci], [docker], [cd]).

Each feature model declares the [project] fields it uses (`shared_fields`; all of them for `ProjectConfig`
subclasses), so in memory it carries them too; on disk they live once, in [project], so the CI, the image and
the delivery can't disagree about the stack or the platform.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, ClassVar, Dict, List, Optional, Tuple, Type, TypeVar, Union

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]
import tomli_w
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, field_validator, model_validator

from quoll import languages, platforms
from quoll.services import DATABASE, SERVICES, environment

CONFIG_FILE = "quoll.toml"
PROJECT_SECTION = "project"


class ConfigError(Exception):
    pass


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Fields stored in [project] and shared with the other sections.
    shared_fields: ClassVar[Tuple[str, ...]] = ()
    # Lists left out of quoll.toml while empty, so they can be written as [[section.field]] tables ("a.b" for a
    # nested one).
    omit_when_empty: ClassVar[Tuple[str, ...]] = ()


class PlatformField(BaseModel):
    # Where the repository is hosted and the pipelines run: github | gitlab.
    platform: str = "github"

    @field_validator("platform")
    @classmethod
    def _known_platform(cls, value: str) -> str:
        if value not in platforms.NAMES:
            raise ValueError(f"unknown platform '{value}' (expected one of: {', '.join(platforms.NAMES)})")
        return value


class ProjectConfig(Section, PlatformField):
    # Where the project lives in the repository ("." alone; e.g. "backend" in a workspace). Not stored: it is
    # where its quoll.toml is.
    _directory: str = PrivateAttr(default=".")

    # Name of a registered language plugin (see quoll/languages).
    stack: str
    # Name of one of the stack's frameworks, or empty.
    framework: str = ""
    package_manager: str
    # Pin the package manager itself (pnpm, bun). Empty = read package.json "packageManager".
    package_manager_version: str = ""
    # Backing services: postgres | mysql | redis | mongodb. Run next to the CI tests and in compose.yaml.
    services: List[str] = Field(default_factory=list)

    @field_validator("stack")
    @classmethod
    def _known_stack(cls, value: str) -> str:
        if value not in languages.names():
            raise ValueError(f"unknown stack '{value}' (expected one of: {', '.join(languages.names())})")
        return value

    @field_validator("services")
    @classmethod
    def _known_services(cls, value: List[str]) -> List[str]:
        unknown = [s for s in value if s not in SERVICES]
        if unknown:
            raise ValueError(f"unknown service '{unknown[0]}' (expected one of: {', '.join(SERVICES)})")
        return value

    @model_validator(mode="after")
    def _check_project(self) -> "ProjectConfig":
        lang = self.language
        if self.framework and self.get_framework() is None:
            known = [f.name for f in languages.frameworks(lang.name)]
            raise ValueError(
                f"unknown framework '{self.framework}' for {lang.name} (expected one of: {', '.join(known)})"
            )
        if self.package_manager not in lang.package_managers:
            raise ValueError(
                f"package_manager '{self.package_manager}' is not valid for {lang.name} "
                f"(expected one of: {', '.join(lang.package_managers)})"
            )
        return self

    @property
    def language(self) -> languages.Language:
        return languages.get(self.stack)

    def get_framework(self) -> Optional[languages.Framework]:
        return languages.get_framework(self.stack, self.framework) if self.framework else None

    def service_environment(self, host: Union[str, Callable[[str], str]], database: str = DATABASE) -> Dict[str, str]:
        """Variables pointing the app at its services on `host` (or `host(service)`), using `database`."""
        framework = self.get_framework()
        hooks = [self.language.service_env] + ([framework.service_env] if framework else [])
        return environment(self.services, host, *hooks, database=database)

    @property
    def directory(self) -> str:
        return self._directory

    def in_directory(self, directory: str) -> "ProjectConfig":
        """This config for a project living in `directory` of the repository."""
        self._directory = directory.strip("/") or "."
        return self

    def path(self, name: str) -> str:
        """`name`, relative to the project, as a path from the repository root."""
        return name if self._directory == "." else f"{self._directory}/{name}"

    @property
    def target(self) -> str:
        return f"{self.stack}/{self.framework}" if self.framework else self.stack


PROJECT_FIELDS = tuple(ProjectConfig.model_fields)
ProjectConfig.shared_fields = PROJECT_FIELDS

M = TypeVar("M", bound=Section)


def read(project_dir: Path) -> dict:
    path = project_dir / CONFIG_FILE
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{CONFIG_FILE} is not valid TOML: {e}") from e


def load_section(project_dir: Path, section: str, model: Type[M]) -> M:
    data = read(project_dir)
    if section not in data:
        if not (project_dir / CONFIG_FILE).exists():
            raise ConfigError(f"{CONFIG_FILE} not found in {project_dir}. Run `quoll {section} init` first.")
        raise ConfigError(f"{CONFIG_FILE} has no [{section}] section. Run `quoll {section} init` first.")
    merged = dict(data[section])
    project = data.get(PROJECT_SECTION, {})
    # Older files kept the project fields inside [ci]; [project] wins when both exist.
    merged.update({k: v for k, v in project.items() if k in model.shared_fields})
    try:
        return model.model_validate(merged)
    except ValidationError as e:
        details = "\n".join(f"  {_location(model, section, err['loc'])}{err['msg']}" for err in e.errors())
        raise ConfigError(f"Invalid {CONFIG_FILE}:\n{details}") from e


def save_section(project_dir: Path, section: str, config: Section) -> Path:
    """Write `section` and its shared fields in [project], preserving the rest of quoll.toml."""
    data = read(project_dir)
    values = config.model_dump()
    for name in config.omit_when_empty:
        *parents, key = name.split(".")
        table = values
        for parent in parents:
            table = table.get(parent) or {}
        if not table.get(key):
            table.pop(key, None)
    shared = {k: values.pop(k) for k in config.shared_fields}
    if shared:
        data[PROJECT_SECTION] = {**data.get(PROJECT_SECTION, {}), **shared}
    data[section] = values
    # [project] first, then the features in a stable order.
    project = {PROJECT_SECTION: data.pop(PROJECT_SECTION)} if PROJECT_SECTION in data else {}
    ordered = {**project, **dict(sorted(data.items()))}
    path = project_dir / CONFIG_FILE
    path.write_text(tomli_w.dumps(ordered))
    return path


def remove_section(project_dir: Path, section: str) -> None:
    """Drop `section` from quoll.toml ([project] stays: other sections may still use it)."""
    data = read(project_dir)
    data.pop(section, None)
    (project_dir / CONFIG_FILE).write_text(tomli_w.dumps(data))


def _location(model: Type[Section], section: str, loc: tuple) -> str:
    if not loc:
        return ""
    prefix = PROJECT_SECTION if loc[0] in model.shared_fields else section
    return f"{prefix}.{'.'.join(str(p) for p in loc)}: "
