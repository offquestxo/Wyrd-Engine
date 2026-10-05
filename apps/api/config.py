"""Typed loaders for config/*.yaml. Model IDs and limits live in YAML, never in code."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from apps.api.settings import CONFIG_DIR


class ModelLimits(BaseModel):
    rpm: int | None = None
    rpd: int | None = None
    tpm: int | None = None
    tpd: int | None = None


class ModelConfig(BaseModel):
    id: str
    dimensions: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)  # provider-specific request fields
    json_mode: bool | None = None  # overrides the provider default (e.g. Gemma: no JSON mode)
    max_request_tokens: int | None = None  # router batches/chunks requests to stay under this
    limits: ModelLimits = Field(default_factory=ModelLimits)


class ProviderConfig(BaseModel):
    kind: Literal["openai_compat", "gemini", "quota_only"]
    base_url: str | None = None
    api_key_env: str | None = None
    json_mode: bool = False
    models: dict[str, ModelConfig] = Field(default_factory=dict)
    limits: dict[str, int | None] = Field(default_factory=dict)


class RouteStep(BaseModel):
    provider: str
    model: str


class RetryConfig(BaseModel):
    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 20.0


class ProvidersConfig(BaseModel):
    providers: dict[str, ProviderConfig]
    retry: RetryConfig = Field(default_factory=RetryConfig)
    near_limit_ratio: float = 0.9
    auth_failure_cooldown_s: float = 900.0
    tasks: dict[str, list[RouteStep]]

    def model(self, provider: str, alias: str) -> ModelConfig:
        return self.providers[provider].models[alias]


class HttpConfig(BaseModel):
    timeout_s: float = 20.0
    min_interval_s: dict[str, float] = Field(default_factory=lambda: {"default": 0.2})


class SourcesConfig(BaseModel):
    http: HttpConfig = Field(default_factory=HttpConfig)
    news: dict[str, Any] = Field(default_factory=dict)
    evergreen: dict[str, Any] = Field(default_factory=dict)


def _read_yaml(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or CONFIG_DIR) / name
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def load_providers(config_dir: Path | None = None) -> ProvidersConfig:
    return ProvidersConfig.model_validate(_read_yaml("providers.yaml", config_dir))


def load_sources(config_dir: Path | None = None) -> SourcesConfig:
    return SourcesConfig.model_validate(_read_yaml("sources.yaml", config_dir))


def load_yaml(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Untyped access for channels.yaml / scoring.yaml until their agents land."""
    return _read_yaml(name, config_dir)


class ChannelEntry(BaseModel):
    handle: str = Field(pattern=r"^@[\w.\-]+$")
    name: str


class ChannelsConfig(BaseModel):
    channels: list[ChannelEntry]


class ScoringConfig(BaseModel):
    dedup: dict[str, float]
    scout: dict[str, Any]
    gap_finder: dict[str, Any]
    outlier: dict[str, float | int]
    series: list[str]


def load_channels(config_dir: Path | None = None) -> ChannelsConfig:
    return ChannelsConfig.model_validate(_read_yaml("channels.yaml", config_dir))


def load_scoring(config_dir: Path | None = None) -> ScoringConfig:
    return ScoringConfig.model_validate(_read_yaml("scoring.yaml", config_dir))
