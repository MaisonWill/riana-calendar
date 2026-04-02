"""Load per-property display metadata from a YAML file next to the project root."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

LOGGER = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "properties_meta.yaml"


class PropertyExtras(BaseModel):
    """Optional fields for calendar UI and titles (edited in properties_meta.yaml)."""

    display_name: str | None = Field(
        default=None,
        description="Отображаемое имя; если пусто — берётся name из config.yaml",
    )
    bedrooms: float | None = Field(default=None, description="Количество спален")
    bathrooms: float | None = Field(default=None, description="Количество ванных")
    google_drive_photos_url: str = Field(
        default="",
        description="Ссылка на папку Google Drive с фото (пусто — кнопка скрыта)",
    )

    @field_validator("google_drive_photos_url", mode="before")
    @classmethod
    def strip_url(cls, v: Any) -> Any:
        if v is None:
            return ""
        val = str(v).strip()
        if val and not (val.lower().startswith("http://") or val.lower().startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return val

    @field_validator("bedrooms", "bathrooms", mode="before")
    @classmethod
    def empty_to_none(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        return v


def load_property_meta(path: str | Path | None = None) -> dict[str, PropertyExtras]:
    """Load property extras from YAML. Missing file → empty dict (defaults only).

    Args:
        path: Path to properties_meta.yaml (default: next to main.py / project root).

    Returns:
        Map property_id -> PropertyExtras.
    """
    meta_path = Path(path) if path is not None else _DEFAULT_PATH
    if not meta_path.is_file():
        LOGGER.warning("Файл метаданных не найден (%s) — подставляются только имена из config", meta_path)
        return {}

    with meta_path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f)

    if not payload or not isinstance(payload, dict):
        return {}

    raw_props = payload.get("properties")
    if not isinstance(raw_props, dict):
        return {}

    result: dict[str, PropertyExtras] = {}
    for prop_id, data in raw_props.items():
        if not isinstance(prop_id, str) or not prop_id.strip():
            continue
        if data is None:
            data = {}
        if not isinstance(data, dict):
            LOGGER.warning("Пропуск %s: ожидался объект в YAML", prop_id)
            continue
        try:
            result[prop_id] = PropertyExtras.model_validate(data)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Некорректные данные для %s: %s", prop_id, exc)

    return result
