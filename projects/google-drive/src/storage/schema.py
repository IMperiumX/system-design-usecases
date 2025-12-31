"""
Database Schema - SQLAlchemy ORM models

System Design Concept:
    Relational schema with ACID guarantees for strong consistency.

Key design decisions:
    - FileVersion table is immutable (append-only) for reliable history
    - Block.hash is UNIQUE for deduplication across all users
    - Indexes on frequently queried fields (user_id, file_path, block_hash)
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    BigInteger,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.models import FileStatus, CompressionAlgorithm
from src.storage.database import Base


# ============================================================================
# USER & AUTH
# ============================================================================


class UserModel(Base):
    """
    User table

    Each user has:
    - One namespace (root directory)
    - Multiple devices
    - Multiple files
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(50), nullable=False)
    password_hash = Column(String(255), nullable=False)  # bcrypt hash
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    namespace = relationship("NamespaceModel", back_populates="user", uselist=False)
    devices = relationship("DeviceModel", back_populates="user")
    owned_files = relationship("FileModel", foreign_keys="FileModel.owner_user_id")
    shared_files = relationship("ShareModel", foreign_keys="ShareModel.shared_with_user_id")


class DeviceModel(Base):
    """
    Device table - track user's devices for push notifications

    Each device has a unique push_id for mobile notifications (APNs/FCM)
    """
    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_type = Column(String(50), nullable=False)  # 'ios', 'android', 'web'
    push_id = Column(String(255), nullable=True)  # For mobile push notifications
    last_active = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("UserModel", back_populates="devices")

    # Indexes
    __table_args__ = (Index("ix_device_user", "user_id"),)


# ============================================================================
# FILE STORAGE
# ============================================================================


class NamespaceModel(Base):
    """
    Namespace - root directory for user's files

    System Design Note:
        Each user has one namespace. All user files live under this namespace.
        This enables easy sharding by user_id.
    """
    __tablename__ = "namespaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    root_path = Column(String(255), nullable=False)  # e.g., "/user_{user_id}"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("UserModel", back_populates="namespace")
    files = relationship("FileModel", back_populates="namespace")


class FileModel(Base):
    """
    File metadata table

    System Design Note:
        - current_version_id points to latest version
        - status tracks upload state (pending → uploaded)
        - is_deleted enables soft delete (for recovery)
    """
    __tablename__ = "files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    namespace_id = Column(
        UUID(as_uuid=True), ForeignKey("namespaces.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    path = Column(String(1024), nullable=False)  # Full path: /folder/file.txt
    current_version_id = Column(UUID(as_uuid=True), nullable=True)  # Latest version
    status = Column(Enum(FileStatus), default=FileStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    # Relationships
    namespace = relationship("NamespaceModel", back_populates="files")
    versions = relationship("FileVersionModel", back_populates="file")
    shares = relationship("ShareModel", foreign_keys="ShareModel.file_id")

    # Indexes for fast lookups
    __table_args__ = (
        Index("ix_file_namespace_path", "namespace_id", "path"),  # List user files
        Index("ix_file_owner", "owner_user_id"),
        UniqueConstraint("namespace_id", "path", name="uq_namespace_path"),  # No duplicates
    )


class FileVersionModel(Base):
    """
    File version history (immutable table)

    System Design Note:
        This table is APPEND-ONLY. Rows are never updated or deleted.
        This ensures version history integrity.
    """
    __tablename__ = "file_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    version_number = Column(Integer, nullable=False)  # 1, 2, 3, ...
    size_bytes = Column(BigInteger, nullable=False)
    block_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    file = relationship("FileModel", back_populates="versions")
    blocks = relationship("BlockModel", back_populates="file_version")

    # Indexes
    __table_args__ = (
        Index("ix_version_file_created", "file_id", "created_at"),  # Get recent versions
        UniqueConstraint("file_id", "version_number", name="uq_file_version"),
    )


class BlockModel(Base):
    """
    Block metadata table

    System Design Note:
        - `hash` is UNIQUE for deduplication across ALL users
        - Same hash = same content = reuse existing block
        - Multiple file_versions can reference same block
    """
    __tablename__ = "blocks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_version_id = Column(
        UUID(as_uuid=True), ForeignKey("file_versions.id", ondelete="CASCADE"), nullable=False
    )
    block_index = Column(Integer, nullable=False)  # Position in file (0-indexed)
    hash = Column(String(64), nullable=False, index=True)  # SHA-256 (64 hex chars)
    size_bytes = Column(Integer, nullable=False)
    storage_path = Column(String(512), nullable=False)  # S3 object key
    encrypted = Column(Boolean, default=True, nullable=False)
    compression_algo = Column(
        Enum(CompressionAlgorithm), default=CompressionAlgorithm.GZIP, nullable=False
    )

    # Relationships
    file_version = relationship("FileVersionModel", back_populates="blocks")

    # Indexes
    __table_args__ = (
        Index("ix_block_version_index", "file_version_id", "block_index"),  # Order blocks
        Index("ix_block_hash", "hash"),  # Deduplication lookup
    )


# ============================================================================
# FILE SHARING
# ============================================================================


class ShareModel(Base):
    """
    File sharing table

    Tracks which users have access to which files
    """
    __tablename__ = "shares"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    shared_with_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    can_edit = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    file = relationship("FileModel", foreign_keys=[file_id])
    owner = relationship("UserModel", foreign_keys=[owner_user_id])
    shared_with = relationship("UserModel", foreign_keys=[shared_with_user_id])

    # Indexes
    __table_args__ = (
        Index("ix_share_user_file", "shared_with_user_id", "file_id"),
        UniqueConstraint(
            "file_id", "shared_with_user_id", name="uq_share_file_user"
        ),  # No duplicate shares
    )
