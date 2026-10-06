"""Read and write config/*.yaml from Settings. Edits are validated before they are saved,
and saved as the raw text the owner edited (so comments survive)."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from apps.api.config import (
    ChannelsConfig,
    EngineConfig,
    ProvidersConfig,
    ScoringConfig,
    SourcesConfig,
)
from apps.api.settings import CONFIG_DIR


class ConfigError(ValueError):
    pass


def _check_providers(data: dict[str, Any]) -> None:
    cfg = ProvidersConfig.model_validate(data)
    for task, steps in cfg.tasks.items():
        for step in steps:
            if step.provider not in cfg.providers:
                raise ConfigError(f"tasks.{task}: unknown provider {step.provider!r}")
            if step.model not in cfg.providers[step.provider].models:
                raise ConfigError(f"tasks.{task}: {step.provider} has no model {step.model!r}")


VALIDATORS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "providers": _check_providers,
    "sources": SourcesConfig.model_validate,
    "channels": ChannelsConfig.model_validate,
    "scoring": ScoringConfig.model_validate,
    "engine": EngineConfig.model_validate,
}


class ConfigFile(BaseModel):
    name: str
    path: str
    raw: str
    data: dict[str, Any]


def _path(name: str, config_dir: Path | None) -> Path:
    if name not in VALIDATORS:
        raise ConfigError(f"unknown config file {name!r}")
    return (config_dir or CONFIG_DIR) / f"{name}.yaml"


def read_config(name: str, config_dir: Path | None = None) -> ConfigFile:
    path = _path(name, config_dir)
    raw = path.read_text()
    return ConfigFile(
        name=name, path=f"config/{path.name}", raw=raw, data=yaml.safe_load(raw) or {}
    )


def validate_config(name: str, raw: str) -> dict[str, Any]:
    _path(name, None)
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML syntax error: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError("top level must be a mapping")
    try:
        VALIDATORS[name](data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise ConfigError(f"{where}: {first['msg']} ({e.error_count()} error(s))") from e
    return data


def write_config(name: str, raw: str, config_dir: Path | None = None) -> ConfigFile:
    data = validate_config(name, raw)
    path = _path(name, config_dir)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        f.write(raw if raw.endswith("\n") else raw + "\n")
    os.replace(tmp, path)
    return ConfigFile(name=name, path=f"config/{path.name}", raw=raw, data=data)
