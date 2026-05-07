"""Application configuration loaded from environment variables.

Single source of truth — all modules import `settings` from here.
Validation runs at startup; missing required values fail loudly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──
    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "TAHRIX"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False
    app_log_level: str = "INFO"
    app_cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # ── Security ──
    secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7

    # ── DB ──
    database_url: str
    neo4j_uri: str
    neo4j_username: str = "neo4j"
    neo4j_password: SecretStr
    neo4j_database: str = "neo4j"
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str

    # ── Alchemy ──
    alchemy_api_key: SecretStr | None = None
    alchemy_eth_url: str = "https://eth-mainnet.g.alchemy.com/v2/"
    alchemy_base_url: str = "https://base-mainnet.g.alchemy.com/v2/"
    alchemy_polygon_url: str = "https://polygon-mainnet.g.alchemy.com/v2/"

    # ── Helius ──
    helius_api_key: SecretStr | None = None
    helius_rpc_url: str = "https://mainnet.helius-rpc.com"
    helius_api_url: str = "https://api-mainnet.helius-rpc.com"
    helius_webhook_auth_header: SecretStr | None = None
    helius_webhook_secret: SecretStr | None = None

    # ── Etherscan V2 ──
    etherscan_api_key: SecretStr | None = None
    etherscan_api_url: str = "https://api.etherscan.io/v2/api"

    # ── Chainalysis ──
    chainalysis_api_key: SecretStr | None = None
    chainalysis_api_url: str = "https://public.chainalysis.com/api/v1/address"

    # ── LayerZero ──
    layerzero_scan_url: str = "https://scan.layerzero-api.com/v1"
    layerzero_oft_api_key: SecretStr | None = None

    # ── Wormhole ──
    wormholescan_api_url: str = "https://api.wormholescan.io/api/v1"

    # ── IPFS (Pinata) ──
    pinata_api_key: SecretStr | None = None
    pinata_api_secret: SecretStr | None = None
    pinata_jwt: SecretStr | None = None
    pinata_api_url: str = "https://api.pinata.cloud"
    ipfs_public_gateway: str = "https://gateway.pinata.cloud/ipfs"

    # ── Telegram ──
    telegram_bot_token: SecretStr | None = None
    telegram_default_chat_id: str | None = None
    telegram_bot_username: str | None = None  # without '@' — used for deep links
    telegram_webhook_secret: SecretStr | None = None  # X-Telegram-Bot-Api-Secret-Token

    # ── OSINT / Web Search ──
    exa_api_key: SecretStr | None = None
    exa_api_url: str = "https://api.exa.ai"

    # ── LLM ──
    llm_provider: Literal["openai", "anthropic", "local"] = "openai"
    llm_api_key: SecretStr | None = None
    llm_base_url: AnyHttpUrl = "https://api.openai.com/v1"  # type: ignore[assignment]
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2000

    # ── LLM Fallback (Ollama) ──
    llm_fallback_url: str | None = None
    llm_fallback_model: str = "minimax-m2.5"
    llm_fallback_api_key: SecretStr | None = None

    # ── GNN ──
    gnn_model_path: str = "./ml/artifacts/gat_elliptic.onnx"
    gnn_feature_dim: int = 165
    gnn_threshold: float = 0.5

    # ── Risk weights (must sum ~ 1.0) ──
    risk_w_gnn: float = 0.40
    risk_w_anomaly: float = 0.30
    risk_w_sanctions: float = 0.20
    risk_w_centrality: float = 0.10

    # ── Investigation ──
    investigation_default_hops: int = 3
    investigation_max_hops: int = 5
    investigation_max_iterations: int = 5
    investigation_confidence_threshold: float = 0.85

    # ── Rate limit ──
    rate_limit_free: str = "100/minute"
    rate_limit_analyst: str = "1000/minute"

    # ── Validators ──
    @field_validator("app_cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("risk_w_gnn", "risk_w_anomaly", "risk_w_sanctions", "risk_w_centrality")
    @classmethod
    def _weight_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("risk weight must be in [0, 1]")
        return v

    # ── Convenience ──
    @property
    def is_prod(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
