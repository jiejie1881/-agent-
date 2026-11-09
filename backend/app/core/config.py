from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_environment: str = "development"
    api_docs_enabled: bool = True
    run_migrations: bool = True
    app_name: str = "物流车辆智能分配系统"
    api_v1_prefix: str = "/api/v1"
    database_url: str = Field(min_length=1)
    sql_echo: bool = False
    jwt_secret_key: str = Field(min_length=32)
    jwt_access_token_expire_minutes: int = 480
    jwt_refresh_token_expire_days: int = 7
    agent_provider: str | None = None
    agent_model: str | None = None
    agent_api_key: SecretStr | None = None
    agent_base_url: str | None = None
    agent_timeout: float = Field(default=30.0, gt=0)
    agent_input_price_per_million: float | None = Field(default=None, ge=0)
    agent_output_price_per_million: float | None = Field(default=None, ge=0)
    agent_cost_currency: str | None = None
    model_budget_enabled: bool = False
    model_budget_path: str | None = None
    model_budget_max_calls: int | None = Field(default=None, gt=0)
    model_budget_max_micro_cny: int | None = Field(default=None, gt=0)
    model_budget_reserve_micro_cny: int | None = Field(default=None, gt=0)
    model_budget_max_inflight: int = Field(default=1, ge=1, le=8)
    model_budget_max_input_bytes: int = Field(default=24000, ge=256, le=1000000)
    model_budget_max_output_tokens: int = Field(default=2048, ge=1, le=8192)
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "logistics-agent-dev"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    agent_write_tools_enabled: bool = False
    business_timezone: str = "Asia/Shanghai"
    quality_load_target: float = Field(default=0.8, gt=0, le=1)
    agent_max_tool_calls: int = Field(default=5, ge=1, le=20)
    agent_history_max_messages: int = Field(default=20, ge=1, le=100)
    agent_pending_action_expire_minutes: int = Field(default=15, ge=1, le=60)
    agent_checkpoint_path: str = "agent_data/checkpoints.sqlite3"
    agent_dispatch_shadow_enabled: bool = False
    agent_draft_accept_enabled: bool = False
    agent_draft_accept_admin_enabled: bool = False
    agent_draft_accept_dispatcher_enabled: bool = False
    agent_draft_receipt_secret: SecretStr | None = None
    agent_draft_receipt_ttl_seconds: int = Field(default=300, ge=30, le=900)
    agent_draft_receipt_key_version: int = Field(default=1, ge=1)
    agent_plan_publish_enabled: bool = False
    agent_plan_publish_admin_enabled: bool = False
    agent_plan_publish_dispatcher_enabled: bool = False
    agent_publish_receipt_ttl_seconds: int = Field(default=300, ge=30, le=900)
    agent_dispatch_shadow_max_revisions: int = Field(default=2, ge=0, le=4)
    agent_dispatch_shadow_timeout: float = Field(default=90, gt=0, le=120)
    agent_dispatch_shadow_max_input_bytes: int = Field(
        default=100000, ge=1000, le=1000000
    )
    agent_dispatch_shadow_max_output_bytes: int = Field(
        default=50000, ge=1000, le=500000
    )
    agent_dispatch_shadow_output_tokens: int = Field(default=4096, ge=256, le=8192)
    agent_dispatch_shadow_token_budget: int = Field(default=100000, ge=1000, le=500000)
    agent_dispatch_shadow_max_cost: Decimal | None = Field(default=None, gt=0)
    agent_dispatch_shadow_input_price_per_million: Decimal | None = Field(
        default=None, ge=0
    )
    agent_dispatch_shadow_output_price_per_million: Decimal | None = Field(
        default=None, ge=0
    )
    agent_dispatch_shadow_cost_currency: str | None = None
    upload_root: str = "uploads"
    delivery_proof_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    rag_embedding_provider: str | None = None
    rag_embedding_model: str | None = None
    rag_embedding_api_key: SecretStr | None = None
    rag_embedding_base_url: str | None = None
    rag_embedding_timeout: float = Field(default=30.0, gt=0)
    rag_knowledge_base_dir: str = "knowledge_base"
    rag_vector_store_dir: str = "rag_data/chroma"
    rag_collection_name: str = "logistics_knowledge"
    agent_memory_enabled: bool = False
    agent_memory_vector_dir: str = "agent_data/memory_chroma"
    agent_memory_tenant_id: str = "logistics"
    agent_memory_project_id: str = "logistics-dispatch"
    agent_memory_embedding_version: str = "bge-m3-1024"
    agent_memory_embedding_dimension: int = Field(default=1024, ge=1, le=8192)
    rag_chunk_size: int = Field(default=800, ge=200, le=4000)
    rag_chunk_overlap: int = Field(default=120, ge=0, le=1000)
    rag_default_top_k: int = Field(default=4, ge=1, le=10)
    rag_retrieval_mode: str = "vector"
    rag_reference_policy: Literal['legacy', 'reference-v1'] = 'legacy'
    rag_evidence_gate_mode: Literal['off', 'shadow'] = 'off'
    rag_semantic_gate_mode: Literal['off', 'isolated'] = 'off'
    rag_vector_candidates: int = Field(default=20, ge=1, le=100)
    rag_bm25_candidates: int = Field(default=20, ge=1, le=100)
    rag_rrf_k: int = Field(default=60, ge=1, le=1000)
    rag_reranker_enabled: bool = False
    rag_reranker_provider: Literal['local', 'api'] = 'local'
    rag_reranker_model: str = 'BAAI/bge-reranker-v2-m3'
    rag_reranker_model_path: str | None = None
    rag_reranker_timeout: float = Field(default=10, gt=0, le=60)
    rag_reranker_candidate_k: int = Field(default=20, ge=1, le=100)
    rag_governance_enabled: bool = False
    rag_governance_offline_enabled: bool = False
    rag_governance_root: str = "knowledge_governance"
    rag_governance_default_base_id: int | None = Field(default=None, gt=0)
    rag_governance_mysql_uuid: str | None = Field(default=None, pattern=r'^[0-9a-f-]{36}$')

    @field_validator('agent_dispatch_shadow_max_cost',
                     'agent_dispatch_shadow_input_price_per_million',
                     'agent_dispatch_shadow_output_price_per_million', mode='before')
    @classmethod
    def optional_budget_environment(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def validate_rag_chunking(self):
        if self.rag_governance_offline_enabled and self.app_environment != "test":
            raise ValueError("Offline knowledge governance requires APP_ENVIRONMENT=test")
        if self.app_environment not in {"development", "test", "production"}:
            raise ValueError("APP_ENVIRONMENT must be development, test or production")
        if self.app_environment == "production" and (
            self.api_docs_enabled or self.sql_echo or self.run_migrations
        ):
            raise ValueError(
                "Production requires API_DOCS_ENABLED=false, SQL_ECHO=false and RUN_MIGRATIONS=false"
            )
        if self.rag_reranker_enabled and self.rag_reranker_provider == 'local' and not self.rag_reranker_model_path:
            raise ValueError(
                "RAG_RERANKER_MODEL_PATH is required when reranking is enabled"
            )
        if self.app_environment == 'production' and self.agent_dispatch_shadow_enabled and (
            self.agent_dispatch_shadow_max_cost is None
            or self.agent_dispatch_shadow_input_price_per_million is None
            or self.agent_dispatch_shadow_output_price_per_million is None
            or not (self.agent_dispatch_shadow_cost_currency or '').strip()
        ):
            raise ValueError('Production Agent dispatch requires a complete monetary budget')
        if self.rag_retrieval_mode not in {"vector", "bm25", "hybrid"}:
            raise ValueError("RAG_RETRIEVAL_MODE must be vector, bm25 or hybrid")
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.business_timezone)
        except ZoneInfoNotFoundError:
            raise ValueError(
                "BUSINESS_TIMEZONE must be a valid IANA timezone"
            ) from None
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE")
        if (
            self.agent_draft_accept_enabled
            and (
                self.agent_draft_accept_admin_enabled
                or self.agent_draft_accept_dispatcher_enabled
            )
        ) or (
            self.agent_plan_publish_enabled
            and (
                self.agent_plan_publish_admin_enabled
                or self.agent_plan_publish_dispatcher_enabled
            )
        ):
            secret = self.agent_draft_receipt_secret
            if secret is None or len(secret.get_secret_value().encode("utf-8")) < 32:
                raise ValueError(
                    "AGENT_DRAFT_RECEIPT_SECRET must be at least 32 bytes when Agent draft acceptance is enabled"
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
