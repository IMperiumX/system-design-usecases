"""
Database initialization script

Usage:
    python -m src.storage.init_db
"""

import asyncio
import sys

from src.storage.database import init_db, drop_db, engine


async def main():
    """Initialize database schema"""
    print("Initializing database...")

    if "--drop" in sys.argv:
        print("⚠️  Dropping all tables...")
        await drop_db()

    print("Creating tables...")
    await init_db()

    print("✅ Database initialized successfully!")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
