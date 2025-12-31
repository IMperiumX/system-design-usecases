"""
Configuration - Settings and environment variables

System Design Concept:
    Centralized configuration management for distributed system.

Simulates:
    Configuration service like Consul, etcd, or AWS Systems Manager

At Scale:
    - Configs would be in distributed config store
    - Feature flags for gradual rollouts
    - Environment-specific overrides (dev/staging/prod)
"""

from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/google_drive"

    # Storage
    storage_path: str = "./storage"
    block_size_mb: int = 4  # Dropbox standard: 4MB blocks
    max_file_size_gb: int = 10

    # Security
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Encryption (AES-256 requires 32 bytes)
    encryption_key: str = "dev-encryption-key-32-bytes!!"  # In prod: from KMS

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4

    # Notification Service
    long_poll_timeout_seconds: int = 60
    max_connections_per_server: int = 10000

    # Cache
    cache_ttl_seconds: int = 300  # 5 minutes
    enable_metadata_cache: bool = True

    # Optimization Features
    enable_compression: bool = True
    enable_deduplication: bool = True
    enable_delta_sync: bool = True

    # Storage Policies
    max_versions_per_file: int = 10  # Keep last N versions
    cold_storage_days: int = 90  # Move to cold storage after X days

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @property
    def block_size_bytes(self) -> int:
        """Block size in bytes"""
        return self.block_size_mb * 1024 * 1024

    @property
    def max_file_size_bytes(self) -> int:
        """Max file size in bytes"""
        return self.max_file_size_gb * 1024 * 1024 * 1024


# Global settings instance
settings = Settings()
