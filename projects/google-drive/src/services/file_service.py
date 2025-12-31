"""
File Service - Upload/download orchestration

System Design Concept:
    Orchestrates block processing, storage, metadata, and notifications

This is the main business logic layer that coordinates:
- Block processor (chunking, compression, encryption)
- S3 storage (block upload/download)
- Metadata database (file records, versions)
- Notification service (real-time sync events)
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.models import (
    FileMetadata,
    FileVersionMetadata,
    BlockMetadata,
    BlockManifest,
    FileStatus,
    CompressionAlgorithm,
)
from src.storage.schema import (
    FileModel,
    FileVersionModel,
    BlockModel,
    NamespaceModel,
)
from src.storage.s3_simulator import s3
from src.services.block_processor import block_processor
from src.services.cache_service import cache, invalidate_file_cache
from src.services.notification_service import notify_file_uploaded, notify_file_updated
from src.config import settings


class FileService:
    """
    File upload/download orchestration

    Handles complete workflows:
    - Upload: chunk → compress → encrypt → store → metadata → notify
    - Download: metadata → fetch blocks → decrypt → decompress → reconstruct
    - Delta sync: compare versions → upload only changed blocks
    """

    async def create_file(
        self,
        db: AsyncSession,
        user_id: UUID,
        file_path: str,
        file_data: bytes,
    ) -> FileMetadata:
        """
        Upload new file

        Flow:
        1. Create file record (status=pending)
        2. Process blocks (chunk → compress → encrypt)
        3. Upload blocks to S3
        4. Create version record
        5. Update file (status=uploaded)
        6. Notify subscribers

        Args:
            db: Database session
            user_id: File owner
            file_path: Full path (e.g., /folder/document.txt)
            file_data: Raw file bytes

        Returns:
            File metadata
        """
        # Get user's namespace
        result = await db.execute(
            select(NamespaceModel).where(NamespaceModel.user_id == user_id)
        )
        namespace = result.scalar_one_or_none()

        if not namespace:
            # Create namespace if doesn't exist
            namespace = NamespaceModel(
                user_id=user_id,
                root_path=f"/user_{user_id}",
            )
            db.add(namespace)
            await db.flush()

        # Step 1: Create file record
        file_name = file_path.split("/")[-1]
        file_model = FileModel(
            namespace_id=namespace.id,
            owner_user_id=user_id,
            name=file_name,
            path=file_path,
            status=FileStatus.UPLOADING,
        )
        db.add(file_model)
        await db.flush()

        # Step 2: Create file version
        version = await self._create_version(
            db=db,
            file_id=file_model.id,
            file_data=file_data,
            version_number=1,
        )

        # Step 3: Update file to point to this version
        file_model.current_version_id = version.id
        file_model.status = FileStatus.UPLOADED
        file_model.updated_at = datetime.utcnow()
        await db.commit()

        # Step 4: Invalidate cache
        await invalidate_file_cache(str(file_model.id), str(user_id))

        # Step 5: Notify
        await notify_file_uploaded(file_model.id, user_id, file_name)

        return FileMetadata.model_validate(file_model)

    async def update_file(
        self,
        db: AsyncSession,
        file_id: UUID,
        user_id: UUID,
        new_file_data: bytes,
        enable_delta_sync: bool = True,
    ) -> FileMetadata:
        """
        Update existing file (creates new version)

        If delta_sync enabled:
        - Compare blocks with current version
        - Only upload changed blocks
        - Reuse unchanged blocks

        Args:
            db: Database session
            file_id: File to update
            user_id: User making the change
            new_file_data: New file content
            enable_delta_sync: Use delta sync optimization

        Returns:
            Updated file metadata
        """
        # Get current file
        result = await db.execute(
            select(FileModel)
            .options(joinedload(FileModel.versions))
            .where(FileModel.id == file_id)
        )
        file = result.scalar_one()

        # Get current version number
        current_version_num = (
            await db.execute(
                select(FileVersionModel.version_number)
                .where(FileVersionModel.id == file.current_version_id)
            )
        ).scalar_one()

        # Create new version
        new_version = await self._create_version(
            db=db,
            file_id=file_id,
            file_data=new_file_data,
            version_number=current_version_num + 1,
            previous_version_id=file.current_version_id if enable_delta_sync else None,
        )

        # Update file
        file.current_version_id = new_version.id
        file.status = FileStatus.UPLOADED
        file.updated_at = datetime.utcnow()
        await db.commit()

        # Invalidate cache
        await invalidate_file_cache(str(file_id), str(user_id))

        # Notify
        await notify_file_updated(file_id, user_id, file.name, new_version.version_number)

        return FileMetadata.model_validate(file)

    async def _create_version(
        self,
        db: AsyncSession,
        file_id: UUID,
        file_data: bytes,
        version_number: int,
        previous_version_id: Optional[UUID] = None,
    ) -> FileVersionModel:
        """
        Create file version with blocks

        Args:
            db: Database session
            file_id: Parent file
            file_data: File content
            version_number: Version number
            previous_version_id: For delta sync

        Returns:
            Created version model
        """
        # If delta sync enabled and previous version exists
        if previous_version_id and settings.enable_delta_sync:
            # Get previous version blocks
            result = await db.execute(
                select(BlockModel)
                .where(BlockModel.file_version_id == previous_version_id)
                .order_by(BlockModel.block_index)
            )
            old_blocks_models = result.scalars().all()

            # Convert to Block models
            from src.models import Block
            old_blocks = [
                Block(
                    block_index=b.block_index,
                    hash=b.hash,
                    size_bytes=b.size_bytes,
                    data=b"",  # Don't need data for delta calc
                )
                for b in old_blocks_models
            ]

            # Calculate delta
            changed_blocks, reused_blocks = await block_processor.calculate_delta(
                old_blocks, file_data
            )
        else:
            # No delta sync, all blocks are new
            changed_blocks = [b async for b in block_processor.chunk_file(file_data)]
            reused_blocks = []

        # Create version record
        version = FileVersionModel(
            file_id=file_id,
            version_number=version_number,
            size_bytes=len(file_data),
            block_count=len(changed_blocks) + len(reused_blocks),
        )
        db.add(version)
        await db.flush()

        # Upload new blocks
        for block in changed_blocks:
            await self._store_block(db, version.id, block)

        # Reuse old blocks (just create new BlockModel records pointing to same storage)
        for block in reused_blocks:
            # Find existing block with this hash
            result = await db.execute(
                select(BlockModel).where(BlockModel.hash == block.hash).limit(1)
            )
            existing_block = result.scalar_one_or_none()

            if existing_block:
                # Reuse storage path
                new_block_model = BlockModel(
                    file_version_id=version.id,
                    block_index=block.block_index,
                    hash=block.hash,
                    size_bytes=block.size_bytes,
                    storage_path=existing_block.storage_path,  # Reuse!
                    encrypted=existing_block.encrypted,
                    compression_algo=existing_block.compression_algo,
                )
                db.add(new_block_model)

        await db.flush()
        return version

    async def _store_block(
        self,
        db: AsyncSession,
        version_id: UUID,
        block,
        compression_algo: CompressionAlgorithm = CompressionAlgorithm.GZIP,
    ) -> BlockModel:
        """
        Process and store a single block

        Flow:
        1. Check if block hash already exists (deduplication)
        2. If not, process: compress → encrypt
        3. Upload to S3
        4. Create metadata record

        Returns:
            Block metadata model
        """
        # Check deduplication
        if settings.enable_deduplication:
            result = await db.execute(
                select(BlockModel).where(BlockModel.hash == block.hash).limit(1)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Block already exists, reuse!
                new_block = BlockModel(
                    file_version_id=version_id,
                    block_index=block.block_index,
                    hash=block.hash,
                    size_bytes=block.size_bytes,
                    storage_path=existing.storage_path,  # Reuse storage
                    encrypted=existing.encrypted,
                    compression_algo=existing.compression_algo,
                )
                db.add(new_block)
                await db.flush()
                return new_block

        # New block, process it
        processed_data = await block_processor.process_block(
            block, compress=True, encrypt=True, compression_algo=compression_algo
        )

        # Upload to S3
        storage_path = await s3.upload_block(block.hash, processed_data)

        # Create metadata
        block_model = BlockModel(
            file_version_id=version_id,
            block_index=block.block_index,
            hash=block.hash,
            size_bytes=block.size_bytes,
            storage_path=storage_path,
            encrypted=True,
            compression_algo=compression_algo,
        )
        db.add(block_model)
        await db.flush()

        return block_model

    async def get_file_for_download(
        self, db: AsyncSession, file_id: UUID, version_number: Optional[int] = None
    ) -> BlockManifest:
        """
        Get block manifest for file download

        Returns list of blocks client needs to download and reassemble.

        Args:
            db: Database session
            file_id: File to download
            version_number: Specific version (None = latest)

        Returns:
            Block manifest with all blocks
        """
        # Get file
        result = await db.execute(
            select(FileModel).where(FileModel.id == file_id)
        )
        file = result.scalar_one()

        # Get version
        if version_number:
            result = await db.execute(
                select(FileVersionModel)
                .where(
                    FileVersionModel.file_id == file_id,
                    FileVersionModel.version_number == version_number,
                )
            )
            version = result.scalar_one()
        else:
            # Latest version
            result = await db.execute(
                select(FileVersionModel).where(FileVersionModel.id == file.current_version_id)
            )
            version = result.scalar_one()

        # Get blocks
        result = await db.execute(
            select(BlockModel)
            .where(BlockModel.file_version_id == version.id)
            .order_by(BlockModel.block_index)  # CRITICAL: preserve order!
        )
        blocks = result.scalars().all()

        # Convert to metadata
        block_metadatas = [BlockMetadata.model_validate(b) for b in blocks]

        return BlockManifest(
            file_id=file_id,
            version_id=version.id,
            blocks=block_metadatas,
            total_size_bytes=version.size_bytes,
        )

    async def download_and_reconstruct_file(
        self, db: AsyncSession, file_id: UUID, version_number: Optional[int] = None
    ) -> bytes:
        """
        Download all blocks and reconstruct file

        Flow:
        1. Get block manifest
        2. Download each block from S3
        3. Decrypt and decompress each block
        4. Concatenate blocks in order

        Returns:
            Raw file bytes
        """
        manifest = await self.get_file_for_download(db, file_id, version_number)

        file_data = bytearray()

        for block_meta in manifest.blocks:
            # Download from S3
            encrypted_data = await s3.download_block(block_meta.storage_path)

            # Decrypt and decompress
            raw_data = await block_processor.unprocess_block(
                encrypted_data,
                encrypted=block_meta.encrypted,
                compressed=True,
                compression_algo=block_meta.compression_algo,
            )

            # Append to file
            file_data.extend(raw_data)

        return bytes(file_data)


# Global instance
file_service = FileService()
