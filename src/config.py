"""Configuration loading and validation for Airbnb occupancy tracker."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class PropertyConfig(BaseModel):
    """Configuration for a single Airbnb property."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    ical_url: HttpUrl


class Settings(BaseModel):
    """Global application settings."""

    update_cron: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    log_path: str = Field(min_length=1)
    request_timeout: int = Field(default=30, ge=1)
    request_delay: float = Field(default=2, ge=0)
    months_ahead: int = Field(default=6, ge=1, le=24)


class DeploymentConfig(BaseModel):
    """GitHub Pages deployment settings."""

    enabled: bool = Field(default=False)
    repo_url: str = Field(min_length=1)
    branch: str = Field(default="main")
    local_clone_path: str = Field(default="./deploy_repo")
    commit_message: str = Field(default="Update calendar {timestamp}")
    git_user_name: str = Field(default="Calendar Bot")
    git_user_email: str = Field(default="bot@example.com")


class AppConfig(BaseModel):
    """Top-level application configuration."""

    model_config = ConfigDict(extra="forbid")

    settings: Settings
    properties: list[PropertyConfig] = Field(min_length=1)
    deployment: DeploymentConfig | None = Field(default=None)


def load_config(path: str = "config.yaml") -> AppConfig:
    """Load and validate application configuration from YAML.

    Args:
        path: Path to YAML config file.

    Returns:
        Parsed and validated application config.

    Raises:
        FileNotFoundError: If config file does not exist.
        ValueError: If YAML is empty or invalid structure.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file)

    if not isinstance(payload, dict):
        raise ValueError("Config YAML must contain a top-level mapping.")

    return AppConfig.model_validate(payload)

