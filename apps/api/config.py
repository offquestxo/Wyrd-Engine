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


class ParallelConfig(BaseModel):
    """Run a task's batches on all usable route providers at once (see providers/parallel.py)."""

    last_resort: list[str] = Field(default_factory=list)  # only used once all others stop
    default_batch_tokens: int = 6000  # batch size when a model has no max_request_tokens
    safety_ratio: float = Field(default=0.9, gt=0, le=1)  # stay this far under rpm/tpm
    max_failures_per_lane: int = 2  # consecutive failures before a provider drops out
    workers: dict[str, int] = Field(default_factory=dict)  # concurrent requests per provider
    max_item_attempts: int = 3  # an item that fails this often is reported unscored
    hedge_after_s: float = 30.0  # idle lanes duplicate batches in flight longer than this


class ProvidersConfig(BaseModel):
    providers: dict[str, ProviderConfig]
    parallel: dict[str, ParallelConfig] = Field(default_factory=dict)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    near_limit_ratio: float = 0.9
    auth_failure_cooldown_s: float = 900.0
    headroom_tasks: list[str] = Field(default_factory=list)
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
    prefilter: dict[str, Any] = Field(default_factory=dict)
    dedup: dict[str, float]
    scout: dict[str, Any]
    gap_finder: dict[str, Any]
    outlier: dict[str, Any]
    research: dict[str, Any] = Field(default_factory=dict)
    series: list[str]


def load_channels(config_dir: Path | None = None) -> ChannelsConfig:
    return ChannelsConfig.model_validate(_read_yaml("channels.yaml", config_dir))


def load_scoring(config_dir: Path | None = None) -> ScoringConfig:
    return ScoringConfig.model_validate(_read_yaml("scoring.yaml", config_dir))


class JobsConfig(BaseModel):
    max_concurrent_runs: int = Field(default=2, ge=1, le=16)
    poll_interval_s: float = Field(default=2.0, gt=0)


class UsageConfig(BaseModel):
    day_reset_timezone: str = "America/Los_Angeles"


class OrchestratorConfig(BaseModel):
    model: str = "sonnet"
    effort: str | None = "low"
    workdir: str = "~/.local/share/wyrd/orchestrator"
    turn_timeout_s: float = Field(default=300, gt=0)
    daily_soft_cap: int = Field(default=40, ge=1)
    warn_ratio: float = Field(default=0.8, gt=0, le=1)


class EngineConfig(BaseModel):
    jobs: JobsConfig = Field(default_factory=JobsConfig)
    usage: UsageConfig = Field(default_factory=UsageConfig)
    orchestrator: OrchestratorConfig = Field(default_factory=OrchestratorConfig)


def load_engine(config_dir: Path | None = None) -> EngineConfig:
    return EngineConfig.model_validate(_read_yaml("engine.yaml", config_dir))
