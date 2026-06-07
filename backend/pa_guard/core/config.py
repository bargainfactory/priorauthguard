"""Application settings.

Loaded once from environment variables (and an optional .env file). All secrets
must come from the environment — never from code. Defaults are chosen for safe
local development.
"""
from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEV = "development"
    STAGING = "staging"
    PROD = "production"
    TEST = "test"


class Jurisdiction(StrEnum):
    """Supported regulatory jurisdictions.

    The platform must remain compliant across all listed jurisdictions; this
    enum is the single source of truth used by the compliance engine and
    routing logic.
    """
    US_FEDERAL = "us-federal"
    US_STATE = "us-state"          # narrowed by `state_code` on the request
    CA_FEDERAL = "ca-federal"
    CA_PROVINCE = "ca-province"    # narrowed by `province_code` on the request
    UK = "uk"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PAG_",
        extra="ignore",
    )

    # --- Runtime ---
    environment: Environment = Environment.DEV
    debug: bool = False
    service_name: str = "pa-guard"

    # --- API ---
    api_host: str = "127.0.0.1"
    api_port: int = 8080
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Privacy / FHE ---
    enforce_safe_harbor: bool = True
    fhe_enabled: bool = False
    fhe_cache_dir: Path = Field(default=Path(".fhe_cache"))
    fhe_quant_bits: int = 8
    fhe_use_qat: bool = True

    # --- zk-STARK ---
    zkstark_enabled: bool = False
    zkstark_cache_dir: Path = Field(default=Path(".zkstark_cache"))

    # --- Voice ---
    voice_on_device_enabled: bool = True
    voice_cloud_enabled: bool = False
    whisper_model: str = "small.en-q8"   # quantized on-device default
    deepgram_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None

    # --- Storage ---
    database_url: str = "postgresql+asyncpg://localhost/paguard"
    audit_log_dir: Path = Field(default=Path("logs/audit"))
    pa_registry_backend: str = Field(
        default="memory",
        description="One of 'memory' or 'sql'. When 'sql', uses `database_url`.",
    )

    # --- Payer adapters (Phase 5) ---
    # `*_base_url` lets ops point an adapter at the payer's sandbox during
    # onboarding without touching code. Unset → adapter uses the production
    # URL hard-coded in its module.
    availity_client_id: str | None = None
    availity_client_secret: str | None = None
    availity_base_url: str | None = None
    covermymeds_api_key: str | None = None
    covermymeds_base_url: str | None = None
    surescripts_client_id: str | None = None
    surescripts_client_secret: str | None = None
    surescripts_base_url: str | None = None
    fax_api_url: str | None = None
    fax_api_key: str | None = None
    fax_from_number: str | None = None
    fax_to_number: str | None = None
    nhs_spine_api_key: str | None = None
    nhs_spine_base_url: str | None = None
    payer_sandbox_mode: bool = Field(
        default=False,
        description=(
            "When true, adapters log calls as sandbox requests and the "
            "smoke-test script targets non-production credentials."
        ),
    )

    # --- LLM-backed MetaImprover (Phase 5) ---
    anthropic_api_key: str | None = None
    meta_improver_model: str = "claude-sonnet-4-6"
    meta_improver_max_tokens: int = 1024

    # --- OPA / Rego policy overlay (v1.0 GA) ---
    opa_url: str | None = Field(
        default=None,
        description=(
            "Base URL of an OPA server (e.g. http://opa:8181). When unset, the "
            "OpaPolicyEngine is a no-op."
        ),
    )

    # --- Desktop auto-updater (v1.0.3) ---
    update_manifest_path: Path = Field(
        default=Path("data/desktop-updates.json"),
        description=(
            "Path to a JSON manifest in Tauri-updater format. Ops publishes "
            "new releases by updating this file. Unset/missing → endpoint "
            "returns 204."
        ),
    )

    # --- SLOs (v1.0.2) ---
    # Targets are deployment-tunable; defaults match the v1.0 GA baseline.
    slo_denial_rate_max: float = Field(default=0.20, ge=0.0, le=1.0)
    slo_pipeline_p99_latency_ms_max: float = Field(default=5000.0, gt=0.0)
    slo_fhe_executed_share_min: float = Field(default=0.80, ge=0.0, le=1.0)
    slo_on_device_voice_share_min: float = Field(default=0.95, ge=0.0, le=1.0)
    slo_agent_success_rate_min: float = Field(default=0.95, ge=0.0, le=1.0)

    # --- OpenTelemetry observability (v1.0.1) ---
    otel_enabled: bool = Field(
        default=False,
        description="Master switch for the OTel SDK. Off by default so dev / test stay quiet.",
    )
    otel_service_name: str = "pa-guard"
    otel_service_version: str = "1.0.1"
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317",
        description="OTLP gRPC endpoint of the collector (Tempo / Jaeger / OTel Collector).",
    )
    otel_traces_sample_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="ParentBased(TraceIdRatioBased) sampler ratio.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached `Settings` instance.

    Cached so importers across the app share one resolved config without
    re-parsing the environment.
    """
    return Settings()
