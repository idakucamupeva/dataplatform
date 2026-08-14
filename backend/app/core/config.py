"""Application configuration.

Everything the platform needs to know about *where it lives* is centralised
here so that a deployment can be reconfigured through environment variables
only (12-factor style).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# <repo-root>/backend/app/core/config.py -> <repo-root>
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DMP_", env_file=".env", extra="ignore")

    # --- identity ---------------------------------------------------------
    platform_name: str = "DataMesh Platform"
    urn_namespace: str = "dmp"

    # --- persistence ------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = ""

    # --- auth -------------------------------------------------------------
    secret_key: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 12

    # --- GitHub -----------------------------------------------------------
    # When a token is set, every new data product gets a real GitHub
    # repository and all descriptor commits/tags are pushed to it.  Without a
    # token the platform falls back to local bare repositories.
    github_token: str = Field(
        default="", validation_alias=AliasChoices("DMP_GITHUB_TOKEN", "GITHUB_TOKEN")
    )
    # User or organisation the repositories are created under.  Empty means
    # "whoever owns the token".
    github_owner: str = ""
    github_repo_prefix: str = "dmp-"
    github_repos_private: bool = True
    github_api_url: str = "https://api.github.com"

    # --- platform behaviour ----------------------------------------------
    environments: list[str] = ["development", "qa", "production"]
    # An environment a data product must be provisioned in before it may be
    # published to the marketplace.
    marketplace_gate_environment: str = "production"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @property
    def repos_dir(self) -> Path:
        """Where the git repositories backing each data product live."""
        return self.data_dir / "repos"

    @property
    def workspaces_dir(self) -> Path:
        """Checked-out working copies the platform edits before committing."""
        return self.data_dir / "workspaces"

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'dmp.db'}"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.repos_dir, self.workspaces_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
