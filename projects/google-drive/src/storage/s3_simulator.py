"""
S3 Simulator - Local filesystem as cloud storage

System Design Concept:
    Object storage abstraction (S3-compatible interface)

Simulates:
    Amazon S3 with multi-region replication

At Scale:
    - Multi-region S3 buckets
    - CloudFront CDN for downloads
    - Lifecycle policies (move to Glacier after 90 days)
"""

import os
import shutil
from pathlib import Path
from typing import Optional

import aiofiles

from src.config import settings


class S3Simulator:
    """
    Simulates Amazon S3 using local filesystem

    Storage structure:
        storage/
        ├── blocks/
        │   ├── 0a/
        │   │   └── 0a3f5c8d...sha256.enc
        │   └── 1b/
        │       └── 1b2e9a7f...sha256.enc
        └── metadata/
            └── manifest.json
    """

    def __init__(self, base_path: str = None):
        self.base_path = Path(base_path or settings.storage_path)
        self.blocks_path = self.base_path / "blocks"
        self.metadata_path = self.base_path / "metadata"

        # Ensure directories exist
        self.blocks_path.mkdir(parents=True, exist_ok=True)
        self.metadata_path.mkdir(parents=True, exist_ok=True)

    def _get_block_path(self, block_hash: str) -> Path:
        """
        Generate storage path for block

        Uses hash prefix for partitioning (like S3):
            hash: 0a3f5c8d... → storage/blocks/0a/0a3f5c8d...sha256.enc
        """
        prefix = block_hash[:2]  # First 2 chars for sharding
        prefix_dir = self.blocks_path / prefix
        prefix_dir.mkdir(exist_ok=True)
        return prefix_dir / f"{block_hash}.enc"

    async def upload_block(self, block_hash: str, data: bytes) -> str:
        """
        Upload block to storage

        Args:
            block_hash: SHA-256 hash of block (for deduplication)
            data: Encrypted + compressed block data

        Returns:
            storage_path: Relative path to stored block

        Simulates:
            boto3.client('s3').put_object(Bucket=bucket, Key=key, Body=data)
        """
        block_path = self._get_block_path(block_hash)

        async with aiofiles.open(block_path, "wb") as f:
            await f.write(data)

        # Return relative path (what we'd store in metadata DB)
        return str(block_path.relative_to(self.base_path))

    async def download_block(self, storage_path: str) -> bytes:
        """
        Download block from storage

        Args:
            storage_path: Relative path returned from upload_block

        Returns:
            Encrypted + compressed block data

        Simulates:
            boto3.client('s3').get_object(Bucket=bucket, Key=key)['Body'].read()
        """
        full_path = self.base_path / storage_path

        if not full_path.exists():
            raise FileNotFoundError(f"Block not found: {storage_path}")

        async with aiofiles.open(full_path, "rb") as f:
            return await f.read()

    async def block_exists(self, block_hash: str) -> Optional[str]:
        """
        Check if block already exists (deduplication)

        Returns:
            storage_path if exists, None otherwise
        """
        block_path = self._get_block_path(block_hash)
        if block_path.exists():
            return str(block_path.relative_to(self.base_path))
        return None

    async def delete_block(self, storage_path: str) -> bool:
        """
        Delete block from storage

        Note: In production, we'd rarely delete blocks due to deduplication.
        Other files might reference the same block.
        """
        full_path = self.base_path / storage_path

        if full_path.exists():
            full_path.unlink()
            return True
        return False

    def get_storage_stats(self) -> dict:
        """
        Get storage usage statistics

        Returns:
            {
                'total_blocks': int,
                'total_size_bytes': int,
                'unique_hashes': int
            }
        """
        total_blocks = 0
        total_size = 0

        for prefix_dir in self.blocks_path.iterdir():
            if prefix_dir.is_dir():
                for block_file in prefix_dir.iterdir():
                    if block_file.is_file():
                        total_blocks += 1
                        total_size += block_file.stat().st_size

        return {
            "total_blocks": total_blocks,
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024),
        }

    async def replicate_block(self, storage_path: str, replica_base: str) -> str:
        """
        Simulate cross-region replication

        In production: S3 automatically replicates to other regions
        """
        source = self.base_path / storage_path
        replica_path = Path(replica_base) / storage_path

        replica_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, replica_path)

        return str(replica_path)

    async def cleanup_orphaned_blocks(self, referenced_hashes: set[str]) -> int:
        """
        Delete blocks not referenced by any file version

        Returns:
            Number of blocks deleted
        """
        deleted_count = 0

        for prefix_dir in self.blocks_path.iterdir():
            if not prefix_dir.is_dir():
                continue

            for block_file in prefix_dir.iterdir():
                if not block_file.is_file():
                    continue

                # Extract hash from filename: 0a3f5c8d...sha256.enc → 0a3f5c8d...
                block_hash = block_file.stem  # Remove .enc

                if block_hash not in referenced_hashes:
                    block_file.unlink()
                    deleted_count += 1

        return deleted_count


# Global S3 instance
s3 = S3Simulator()
