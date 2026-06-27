"""
Vault Graph Configuration

Read-only service that connects to Context Vault's Neon database
and manages its own vault_graph schema for edge/cache data.
"""
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database - Read-only connection to Context Vault Neon
    database_url: str = "postgresql+asyncpg://user:pass@localhost/context_vault"

    @property
    def database_url_async(self) -> str:
        """Convert database URL to asyncpg-compatible format."""
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if "sslmode=" in url:
            url = url.replace("sslmode=", "ssl=")
        return url

    # OpenAI for embeddings (used for search)
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # API Settings
    api_title: str = "Vault Graph API"
    api_version: str = "1.0.0"
    api_key: str = ""  # Bearer token for authentication

    # Default owner (matches Context Vault)
    default_owner: str = "don"

    # S3/R2 Storage Configuration (for presigned URLs)
    s3_endpoint_url: Optional[str] = None
    s3_access_key_id: Optional[str] = None
    s3_secret_access_key: Optional[str] = None
    s3_bucket_name: str = ""
    s3_region: str = "auto"

    # Presigned URL expiration (seconds)
    presigned_url_expiration: int = 3600

    # Graph Settings
    edge_similarity_threshold: float = 0.7  # Minimum similarity for semantic edges
    edge_jaccard_threshold: float = 0.5  # Minimum Jaccard for tag edges (50% overlap)
    max_knn_edges: int = 5  # Max semantic edges per node
    graph_cache_ttl: int = 300  # Cache TTL in seconds

    # Search defaults (matches Context Vault)
    default_search_limit: int = 10
    max_search_limit: int = 50
    similarity_threshold: float = 0.5

    # Logging
    log_level: str = "INFO"

    # CORS
    allowed_origins: str = "*"

    # Environment identifier
    environment: str = "development"

    class Config:
        env_file = ".env"
        env_prefix = "VAULT_GRAPH_"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
