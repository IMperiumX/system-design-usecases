"""
Block Processor - File chunking, compression, encryption

System Design Concept:
    Implements [[block-level-storage]], [[delta-sync]], and [[data-deduplication]]

Simulates:
    Dedicated upload worker pool (e.g., Celery workers at Dropbox)

At Scale:
    - Distributed worker pool (100s of workers)
    - Queue-based job distribution (RabbitMQ/Kafka)
    - Workers in multiple datacenters for geo-proximity
"""

import asyncio
import gzip
import hashlib
import io
from typing import AsyncIterator, Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import os

from src.config import settings
from src.models import Block, CompressionAlgorithm


class BlockProcessor:
    """
    Handles file chunking, compression, and encryption

    This is the core of bandwidth optimization:
    - Chunking enables delta sync (only upload changed blocks)
    - Compression reduces data size by 50-70% for text files
    - Deduplication saves storage by reusing identical blocks
    """

    def __init__(self):
        self.block_size = settings.block_size_bytes
        self.encryption_key = settings.encryption_key.encode()[:32]  # AES-256 requires 32 bytes

    async def chunk_file(self, file_data: bytes) -> AsyncIterator[Block]:
        """
        Split file into fixed-size blocks

        System Design Note:
            Fixed-size blocks (4MB) vs variable-size (content-defined chunking):
            - Fixed: Simpler, predictable
            - Variable (rsync): Better dedup, more complex

            Dropbox uses fixed 4MB blocks, so we do too.

        Args:
            file_data: Raw file bytes

        Yields:
            Block objects with hash calculated
        """
        file_stream = io.BytesIO(file_data)
        block_index = 0

        while True:
            chunk = file_stream.read(self.block_size)
            if not chunk:
                break

            # Calculate SHA-256 hash for deduplication
            block_hash = hashlib.sha256(chunk).hexdigest()

            yield Block(
                block_index=block_index,
                hash=block_hash,
                size_bytes=len(chunk),
                data=chunk,
            )

            block_index += 1

    def compress_block(
        self, block_data: bytes, algorithm: CompressionAlgorithm = CompressionAlgorithm.GZIP
    ) -> bytes:
        """
        Compress block data

        System Design Note:
            Different algorithms for different file types:
            - Text files: gzip (50-70% reduction)
            - Images: Already compressed (JPEG, PNG), skip or use specialized
            - Videos: Already compressed (H.264), skip

        Args:
            block_data: Raw block bytes
            algorithm: Compression algorithm

        Returns:
            Compressed bytes
        """
        if algorithm == CompressionAlgorithm.GZIP:
            return gzip.compress(block_data, compresslevel=6)  # Balance speed vs ratio
        elif algorithm == CompressionAlgorithm.BZIP2:
            import bz2
            return bz2.compress(block_data)
        else:
            return block_data  # No compression

    def decompress_block(
        self, compressed_data: bytes, algorithm: CompressionAlgorithm
    ) -> bytes:
        """Decompress block data"""
        if algorithm == CompressionAlgorithm.GZIP:
            return gzip.decompress(compressed_data)
        elif algorithm == CompressionAlgorithm.BZIP2:
            import bz2
            return bz2.decompress(compressed_data)
        else:
            return compressed_data

    def encrypt_block(self, block_data: bytes) -> bytes:
        """
        Encrypt block with AES-256

        System Design Note:
            - AES-256 in CTR mode (parallelizable, fast)
            - Random IV per block (stored as prefix)
            - In production: per-user encryption keys from KMS

        Returns:
            IV (16 bytes) + encrypted data
        """
        # Generate random IV (initialization vector)
        iv = os.urandom(16)

        cipher = Cipher(
            algorithms.AES(self.encryption_key), modes.CTR(iv), backend=default_backend()
        )
        encryptor = cipher.encryptor()

        encrypted = encryptor.update(block_data) + encryptor.finalize()

        # Prepend IV for decryption
        return iv + encrypted

    def decrypt_block(self, encrypted_data: bytes) -> bytes:
        """
        Decrypt block

        Args:
            encrypted_data: IV (16 bytes) + encrypted data

        Returns:
            Decrypted bytes
        """
        # Extract IV from first 16 bytes
        iv = encrypted_data[:16]
        ciphertext = encrypted_data[16:]

        cipher = Cipher(
            algorithms.AES(self.encryption_key), modes.CTR(iv), backend=default_backend()
        )
        decryptor = cipher.decryptor()

        return decryptor.update(ciphertext) + decryptor.finalize()

    async def process_block(
        self,
        block: Block,
        compress: bool = True,
        encrypt: bool = True,
        compression_algo: CompressionAlgorithm = CompressionAlgorithm.GZIP,
    ) -> bytes:
        """
        Full block processing pipeline: compress → encrypt

        Args:
            block: Block with raw data
            compress: Enable compression
            encrypt: Enable encryption
            compression_algo: Which compression algorithm to use

        Returns:
            Processed block data (ready for S3 upload)
        """
        data = block.data

        # Step 1: Compress
        if compress and settings.enable_compression:
            data = self.compress_block(data, compression_algo)

        # Step 2: Encrypt
        if encrypt and settings.enable_deduplication:
            data = self.encrypt_block(data)

        return data

    async def unprocess_block(
        self,
        encrypted_data: bytes,
        encrypted: bool = True,
        compressed: bool = True,
        compression_algo: CompressionAlgorithm = CompressionAlgorithm.GZIP,
    ) -> bytes:
        """
        Reverse processing pipeline: decrypt → decompress

        Args:
            encrypted_data: Processed block from S3
            encrypted: Was it encrypted?
            compressed: Was it compressed?
            compression_algo: Which compression algorithm was used

        Returns:
            Raw block data
        """
        data = encrypted_data

        # Step 1: Decrypt
        if encrypted:
            data = self.decrypt_block(data)

        # Step 2: Decompress
        if compressed:
            data = self.decompress_block(data, compression_algo)

        return data

    async def calculate_delta(
        self, old_blocks: list[Block], new_file_data: bytes
    ) -> tuple[list[Block], list[Block]]:
        """
        Calculate delta between old version and new file

        System Design Note:
            This is the core of delta sync:
            - Compare hashes of old blocks vs new blocks
            - Only upload blocks with different hashes
            - Bandwidth savings: 90% on typical edits

        Args:
            old_blocks: Blocks from previous version
            new_file_data: New file content

        Returns:
            (changed_blocks, reused_blocks)
        """
        # Build hash map of old blocks
        old_block_hashes = {block.block_index: block.hash for block in old_blocks}

        changed_blocks = []
        reused_blocks = []

        # Chunk new file
        async for new_block in self.chunk_file(new_file_data):
            old_hash = old_block_hashes.get(new_block.block_index)

            if old_hash == new_block.hash:
                # Block unchanged, reuse it!
                reused_blocks.append(new_block)
            else:
                # Block changed, need to upload
                changed_blocks.append(new_block)

        return changed_blocks, reused_blocks


# Global instance
block_processor = BlockProcessor()
