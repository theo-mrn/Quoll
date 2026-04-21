from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QUOLL_",
        env_file=".env",
        extra="ignore",
        frozen=False,
    )

    github_token: str = ""
    github_org: str = ""
    gitlab_token: str = ""
    # gitlab.com or a self-managed instance.
    gitlab_url: str = "https://gitlab.com"
    # Group (or group/subgroup) where `quoll new --remote` creates GitLab projects; empty = the user's namespace.
    gitlab_group: str = ""
    default_branch: str = "main"


settings = Settings()
