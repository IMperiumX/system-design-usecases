"""
Configuration module for the rate limiter system.

This module handles environment variables and system-wide constants.
"""

import logging
from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Falls back to .env file if present, otherwise uses defaults.
    """

    # Redis Configuration
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Rate Limiter Configuration
    default_algorithm: Literal[
        "token_bucket",
        "leaky_bucket",
        "fixed_window",
        "sliding_window_log",
        "sliding_window_counter"
    ] = "token_bucket"

    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
