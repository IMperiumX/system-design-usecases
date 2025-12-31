"""
Database - SQLAlchemy async setup and session management

System Design Concept:
    Connection pooling for database scalability.

Simulates:
    Database cluster with master-slave replication

At Scale:
    - Sharded across multiple database servers
    - Read replicas for scalability
    - Connection pool per shard
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from src.config import settings

# SQLAlchemy base for ORM models
Base = declarative_base()

# Async database engine
engine = create_async_engine(
    settings.database_url,
    echo=(settings.log_level == "DEBUG"),
    pool_size=20,  # Connection pool size
    max_overflow=10,  # Max connections beyond pool_size
    pool_pre_ping=True,  # Test connection health before using
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI routes

    Usage:
        @app.get("/files")
        async def list_files(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """
    Initialize database schema

    Creates all tables defined in schema.py
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db():
    """Drop all tables (for testing)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
