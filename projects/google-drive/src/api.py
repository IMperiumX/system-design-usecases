"""
API Server - FastAPI endpoints

System Design Concept:
    RESTful API design for cloud storage service

Endpoints:
    - POST /auth/register - User registration
    - POST /auth/login - User login
    - POST /files/upload - Upload file
    - GET /files/download - Download file
    - GET /files/revisions - List file versions
    - POST /files/share - Share file
    - GET /notifications/poll - Long poll for events
"""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext
from jose import JWTError, jwt
import io

from src.config import settings
from src.storage.database import get_db, init_db
from src.storage.schema import UserModel
from src.models import (
    UserCreate,
    User,
    Token,
    FileMetadata,
    BlockManifest,
    Event,
)
from src.services.file_service import file_service
from src.services.notification_service import notification_service, offline_queue

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# FastAPI app
app = FastAPI(
    title="Google Drive - System Design Implementation",
    description="Cloud storage and file synchronization service",
    version="1.0.0",
)


# ============================================================================
# AUTH UTILITIES
# ============================================================================


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password hash"""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash password"""
    return pwd_context.hash(password)


async def get_current_user(token: str, db: AsyncSession = Depends(get_db)) -> UserModel:
    """Dependency to get current authenticated user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(UserModel).where(UserModel.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user


# ============================================================================
# STARTUP / SHUTDOWN
# ============================================================================


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    await init_db()
    print("✅ Database initialized")


# ============================================================================
# HEALTH CHECK
# ============================================================================


@app.get("/health")
async def health_check():
    """Health check endpoint for load balancer"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "notification_service": notification_service.get_stats(),
    }


# ============================================================================
# AUTH ENDPOINTS
# ============================================================================


@app.post("/api/v1/auth/register", response_model=User)
async def register_user(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Register new user

    Creates user account with hashed password
    """
    # Check if user exists
    result = await db.execute(select(UserModel).where(UserModel.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user
    user = UserModel(
        email=user_data.email,
        username=user_data.username,
        password_hash=hash_password(user_data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return User.model_validate(user)


@app.post("/api/v1/auth/login", response_model=Token)
async def login(email: str, password: str, db: AsyncSession = Depends(get_db)):
    """
    User login

    Returns JWT access token
    """
    result = await db.execute(select(UserModel).where(UserModel.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(access_token=access_token)


# ============================================================================
# FILE ENDPOINTS
# ============================================================================


@app.post("/api/v1/files/upload", response_model=FileMetadata)
async def upload_file(
    file_path: str,
    file: UploadFile = File(...),
    token: str = Depends(lambda: "mock-token"),  # Simplified auth
    db: AsyncSession = Depends(get_db),
):
    """
    Upload new file

    Flow:
    1. Read file data
    2. Chunk into blocks
    3. Compress + encrypt blocks
    4. Upload to S3
    5. Create metadata
    6. Notify subscribers
    """
    # For demo, use a mock user ID
    # In production: user = await get_current_user(token, db)
    from uuid import uuid4
    user_id = uuid4()

    # Read file data
    file_data = await file.read()

    # Upload via file service
    metadata = await file_service.create_file(
        db=db,
        user_id=user_id,
        file_path=file_path,
        file_data=file_data,
    )

    return metadata


@app.put("/api/v1/files/{file_id}", response_model=FileMetadata)
async def update_file(
    file_id: UUID,
    file: UploadFile = File(...),
    enable_delta_sync: bool = True,
    token: str = Depends(lambda: "mock-token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Update existing file

    If delta_sync enabled, only uploads changed blocks
    """
    from uuid import uuid4
    user_id = uuid4()

    file_data = await file.read()

    metadata = await file_service.update_file(
        db=db,
        file_id=file_id,
        user_id=user_id,
        new_file_data=file_data,
        enable_delta_sync=enable_delta_sync,
    )

    return metadata


@app.get("/api/v1/files/{file_id}/download")
async def download_file(
    file_id: UUID,
    version_number: Optional[int] = None,
    token: str = Depends(lambda: "mock-token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Download file

    Returns reconstructed file from blocks
    """
    file_data = await file_service.download_and_reconstruct_file(
        db=db,
        file_id=file_id,
        version_number=version_number,
    )

    return Response(content=file_data, media_type="application/octet-stream")


@app.get("/api/v1/files/{file_id}/manifest", response_model=BlockManifest)
async def get_file_manifest(
    file_id: UUID,
    version_number: Optional[int] = None,
    token: str = Depends(lambda: "mock-token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get block manifest for file

    Returns list of blocks client needs to download
    Used for client-side reconstruction
    """
    manifest = await file_service.get_file_for_download(
        db=db,
        file_id=file_id,
        version_number=version_number,
    )

    return manifest


@app.get("/api/v1/files/{file_id}/revisions")
async def list_file_revisions(
    file_id: UUID,
    limit: int = 20,
    token: str = Depends(lambda: "mock-token"),
    db: AsyncSession = Depends(get_db),
):
    """
    List file version history

    Returns:
        List of file versions with metadata
    """
    from src.storage.schema import FileVersionModel

    result = await db.execute(
        select(FileVersionModel)
        .where(FileVersionModel.file_id == file_id)
        .order_by(FileVersionModel.version_number.desc())
        .limit(limit)
    )
    versions = result.scalars().all()

    return [
        {
            "version_number": v.version_number,
            "size_bytes": v.size_bytes,
            "block_count": v.block_count,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]


# ============================================================================
# NOTIFICATION ENDPOINTS
# ============================================================================


@app.get("/api/v1/notifications/poll", response_model=Optional[Event])
async def poll_notifications(
    user_id: str,
    timeout: int = 60,
    token: str = Depends(lambda: "mock-token"),
):
    """
    Long poll for file change notifications

    Client holds connection open until:
    - Event occurs (return 200 with event)
    - Timeout reached (return 204 No Content)

    Client should immediately reconnect after response
    """
    try:
        event = await notification_service.subscribe(user_id, timeout_seconds=timeout)

        if event:
            return event
        else:
            # Timeout, no events
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    except ConnectionError:
        raise HTTPException(status_code=503, detail="Too many connections")


@app.get("/api/v1/notifications/offline", response_model=list[Event])
async def get_offline_notifications(
    user_id: str,
    token: str = Depends(lambda: "mock-token"),
):
    """
    Get all pending notifications for offline user

    Called when user comes back online
    """
    events = await offline_queue.dequeue_all(user_id)
    return events


# ============================================================================
# STATS / MONITORING
# ============================================================================


@app.get("/api/v1/stats")
async def get_system_stats():
    """
    System statistics for monitoring

    In production: This would be scraped by Prometheus
    """
    from src.storage.s3_simulator import s3

    return {
        "storage": s3.get_storage_stats(),
        "notifications": notification_service.get_stats(),
        "offline_queue": offline_queue.get_stats(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.log_level.lower(),
    )
