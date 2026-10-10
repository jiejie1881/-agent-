from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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
    business_timezone: str = "Asia/Shanghai"
    quality_load_target: float = Field(default=0.8, gt=0, le=1)
    agent_max_tool_calls: int = Field(default=5, ge=1, le=20)
    agent_history_max_messages: int = Field(default=20, ge=1, le=100)
    agent_pending_action_expire_minutes: int = Field(default=15, ge=1, le=60)
    agent_checkpoint_path: str = "agent_data/checkpoints.sqlite3"
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
    rag_chunk_size: int = Field(default=800, ge=200, le=4000)
    rag_chunk_overlap: int = Field(default=120, ge=0, le=1000)
    rag_default_top_k: int = Field(default=4, ge=1, le=10)

    @model_validator(mode="after")
    def validate_rag_chunking(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(self.business_timezone)
        except ZoneInfoNotFoundError:
            raise ValueError('BUSINESS_TIMEZONE must be a valid IANA timezone') from None
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
