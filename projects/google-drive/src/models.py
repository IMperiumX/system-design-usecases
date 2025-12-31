"""
Data Models - Pydantic schemas for validation and serialization

System Design Concept:
    Type-safe data validation at API boundaries.

These models represent the data structures exchanged between:
- Clients and API servers
- API servers and block servers
- Services and databases
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# ENUMS
# ============================================================================


class FileStatus(str, Enum):
    """File upload/sync status"""
    PENDING = "pending"  # Upload initiated but not complete
    UPLOADING = "uploading"  # Blocks being processed
    UPLOADED = "uploaded"  # All blocks stored successfully
    FAILED = "failed"  # Upload failed
    DELETED = "deleted"  # Soft deleted


class EventType(str, Enum):
    """Notification event types"""
    FILE_UPLOADED = "file.uploaded"
    FILE_UPDATED = "file.updated"
    FILE_DELETED = "file.deleted"
    FILE_SHARED = "file.shared"
    SYNC_CONFLICT = "sync.conflict"


class ConflictResolution(str, Enum):
    """How to resolve sync conflicts"""
    MERGE = "merge"  # User manually merges versions
    KEEP_LOCAL = "keep_local"  # Override server version
    KEEP_SERVER = "keep_server"  # Discard local changes


class CompressionAlgorithm(str, Enum):
    """Supported compression algorithms"""
    NONE = "none"
    GZIP = "gzip"
    BZIP2 = "bzip2"


# ============================================================================
# USER & AUTH
# ============================================================================


class UserBase(BaseModel):
    """Base user model"""
    email: str = Field(..., description="User email (unique)")
    username: str = Field(..., min_length=3, max_length=50)


class UserCreate(UserBase):
    """User registration request"""
    password: str = Field(..., min_length=8)


class User(UserBase):
    """User response model"""
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


class Token(BaseModel):
    """JWT authentication token"""
    access_token: str
    token_type: str = "bearer"


# ============================================================================
# DEVICE
# ============================================================================


class DeviceCreate(BaseModel):
    """Register new device for user"""
    device_type: str = Field(..., description="e.g., 'ios', 'android', 'web'")
    push_id: Optional[str] = None


class Device(BaseModel):
    """Device model"""
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    device_type: str
    push_id: Optional[str] = None
    last_active: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


# ============================================================================
# FILE METADATA
# ============================================================================


class FileMetadata(BaseModel):
    """
    Core file metadata

    System Design Note:
        This is what gets cached in Redis for fast lookups.
        Stored in metadata DB, NOT in cloud storage.
    """
    id: UUID = Field(default_factory=uuid4)
    namespace_id: UUID  # Owner's namespace
    name: str = Field(..., max_length=255)
    path: str = Field(..., description="Full path: /folder/subfolder/file.txt")
    current_version_id: Optional[UUID] = None
    status: FileStatus = FileStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_deleted: bool = False

    class Config:
        from_attributes = True


class FileVersionMetadata(BaseModel):
    """
    Immutable file version record

    System Design Note:
        Each edit creates a new version row.
        Old versions are NEVER modified (append-only log).
    """
    id: UUID = Field(default_factory=uuid4)
    file_id: UUID
    version_number: int = Field(..., ge=1)
    size_bytes: int = Field(..., ge=0)
    block_count: int = Field(..., ge=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


# ============================================================================
# BLOCK STORAGE
# ============================================================================


class BlockMetadata(BaseModel):
    """
    Metadata for a single file block

    System Design Note:
        - `hash` enables deduplication (same hash = same block)
        - `block_index` preserves order for file reconstruction
        - `storage_path` points to S3 object
    """
    id: UUID = Field(default_factory=uuid4)
    file_version_id: UUID
    block_index: int = Field(..., ge=0, description="Order in file (0-indexed)")
    hash: str = Field(..., description="SHA-256 hash for deduplication")
    size_bytes: int = Field(..., ge=0)
    storage_path: str = Field(..., description="S3 object key")
    encrypted: bool = True
    compression_algo: CompressionAlgorithm = CompressionAlgorithm.GZIP

    class Config:
        from_attributes = True


class Block(BaseModel):
    """
    Block with actual data (in-memory only, not persisted)

    Used during upload/download processing
    """
    block_index: int
    hash: str
    size_bytes: int
    data: bytes  # Raw block data (before/after processing)

    @field_validator("hash")
    @classmethod
    def validate_hash(cls, v: str) -> str:
        """Ensure hash is valid SHA-256"""
        if len(v) != 64:  # SHA-256 is 64 hex chars
            raise ValueError("Hash must be SHA-256 (64 hex characters)")
        return v.lower()


# ============================================================================
# UPLOAD / DOWNLOAD
# ============================================================================


class UploadSessionCreate(BaseModel):
    """Initiate file upload session"""
    file_path: str = Field(..., description="Full path: /folder/file.txt")
    file_size_bytes: int = Field(..., ge=0)
    resumable: bool = False


class UploadSession(BaseModel):
    """Upload session response"""
    session_id: UUID = Field(default_factory=uuid4)
    file_id: UUID
    upload_url: str  # Block server URL for upload
    expires_at: datetime


class BlockManifest(BaseModel):
    """
    List of blocks to download for file reconstruction

    Returned by API on download request
    """
    file_id: UUID
    version_id: UUID
    blocks: list[BlockMetadata]
    total_size_bytes: int


class DownloadRequest(BaseModel):
    """Download file request"""
    file_path: str
    version_number: Optional[int] = None  # If None, download latest


# ============================================================================
# SYNC & CONFLICTS
# ============================================================================


class SyncConflict(BaseModel):
    """
    Sync conflict notification

    System Design Note:
        First-write-wins: this user's upload lost the race.
        Present both versions for manual resolution.
    """
    file_id: UUID
    local_version_id: UUID
    server_version_id: UUID
    conflict_timestamp: datetime = Field(default_factory=datetime.utcnow)
    resolution_options: list[ConflictResolution]


class ConflictResolve(BaseModel):
    """User's conflict resolution choice"""
    file_id: UUID
    resolution: ConflictResolution
    merged_data: Optional[bytes] = None  # If resolution=MERGE


# ============================================================================
# NOTIFICATIONS
# ============================================================================


class Event(BaseModel):
    """
    File change event

    Pushed to clients via long polling
    """
    event_type: EventType
    file_id: UUID
    user_id: UUID
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class NotificationSubscribe(BaseModel):
    """Long poll subscription request"""
    user_id: UUID
    timeout_seconds: int = 60


# ============================================================================
# FILE SHARING
# ============================================================================


class ShareCreate(BaseModel):
    """Share file with another user"""
    file_id: UUID
    shared_with_user_id: UUID
    can_edit: bool = False


class Share(BaseModel):
    """File sharing record"""
    id: UUID = Field(default_factory=uuid4)
    file_id: UUID
    owner_user_id: UUID
    shared_with_user_id: UUID
    can_edit: bool
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


# ============================================================================
# DELTA SYNC
# ============================================================================


class DeltaSyncRequest(BaseModel):
    """
    Request to calculate delta between versions

    System Design Note:
        Client sends current version, server compares blocks,
        returns only changed blocks to upload.
    """
    file_id: UUID
    current_version_number: int
    new_file_size_bytes: int


class DeltaSyncResponse(BaseModel):
    """Changed blocks to upload"""
    file_id: UUID
    old_version_id: UUID
    new_version_id: UUID
    changed_block_indices: list[int]  # Which blocks to upload
    reused_blocks: list[BlockMetadata]  # Blocks we can skip
