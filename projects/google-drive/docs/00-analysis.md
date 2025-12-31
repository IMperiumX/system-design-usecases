---
tags:
  - system-design
  - google-drive
  - cloud-storage
  - file-sync
  - analysis
created: 2025-12-31
status: in-progress
source: "System Design Interview - Chapter 15: Design Google Drive"
---

# Google Drive — Analysis

## Overview

Google Drive is a cloud storage and file synchronization service that enables users to store documents, photos, videos, and files in the cloud with access from any device. The system handles 10M DAU with 50M total users, supporting file uploads/downloads, multi-device sync, version history, file sharing, and real-time notifications.

## Core Requirements

### Functional Requirements

| Feature | Description | Priority |
|---------|-------------|----------|
| Upload files | Support simple & resumable uploads (max 10 GB) | Critical |
| Download files | Retrieve files from cloud storage | Critical |
| File sync | Auto-sync across multiple devices | Critical |
| File revisions | Track and retrieve version history | High |
| File sharing | Share with friends/family/coworkers | High |
| Notifications | Alert on file edits/deletes/shares | High |

### Non-Functional Requirements

> [!tip] Key System Qualities
> - **[[reliability]]**: Zero data loss tolerance
> - **[[fast-sync]]**: Minimize sync latency to prevent abandonment
> - **[[bandwidth-optimization]]**: Reduce network usage (delta sync)
> - **[[scalability]]**: Handle high traffic volumes (240 QPS upload, 480 peak)
> - **[[high-availability]]**: Graceful degradation on failures

### Out of Scope

- Collaborative editing (e.g., Google Docs simultaneous editing)
- Real-time co-authoring features

## Back-of-Envelope Calculations

```
Total users: 50M signed up, 10M DAU
Storage per user: 10 GB free
Upload rate: 2 files/day/user, avg 500 KB each
Read:Write ratio: 1:1

Total storage: 50M × 10 GB = 500 Petabytes
Upload QPS: 10M × 2 / 86,400 = ~240 QPS
Peak QPS: 480 QPS
Daily uploads: 10M × 2 × 500 KB = 10 TB/day
```

## Core Components

| Component | Purpose | Simulates | At Scale |
|-----------|---------|-----------|----------|
| **Block Server** | Chunk, compress, encrypt files | Dropbox block processing | Distributed worker pool |
| **API Server** | User auth, metadata operations | API gateway cluster | Horizontally scaled |
| **Metadata DB** | Store file/user/block metadata | PostgreSQL with ACID | Sharded relational DB |
| **Cloud Storage** | Store file blocks | Amazon S3 | Multi-region object storage |
| **Notification Service** | Push file change events | Long polling server | WebSocket/Server-Sent Events |
| **Metadata Cache** | Fast metadata retrieval | Redis cluster | Multi-layer cache hierarchy |
| **Offline Backup Queue** | Queue changes for offline clients | Message queue (RabbitMQ) | Kafka/SQS |
| **Load Balancer** | Distribute API traffic | Nginx/HAProxy | Cloud LB (AWS ALB) |

## Concepts Demonstrated

> [!tip] Key Learning Areas
> - **[[block-level-storage]]**: Files split into 4MB blocks with unique hashes for deduplication
> - **[[delta-sync]]**: Only modified blocks transferred, not entire files
> - **[[strong-consistency]]**: ACID guarantees for metadata to prevent divergence
> - **[[resumable-uploads]]**: Handle network interruptions gracefully
> - **[[conflict-resolution]]**: First-write-wins strategy with manual merge option
> - **[[data-deduplication]]**: Hash-based block dedup across accounts
> - **[[versioning]]**: Immutable file_version table for history
> - **[[long-polling]]**: Efficient notification delivery vs WebSockets
> - **[[cold-storage]]**: Move inactive data to cheaper tier (S3 Glacier)
> - **[[encryption-at-rest]]**: All blocks encrypted before storage

## Scope Decision

### ✅ Building (MVP)

- **Data Models**: User, Device, File, FileVersion, Block schemas
- **Block Server**: File chunking (4MB blocks), compression (gzip/bzip2), encryption
- **Storage Layer**: Simulated S3 with local filesystem + metadata tracking
- **Metadata DB**: PostgreSQL with full schema (users, files, blocks, versions)
- **API Server**: Upload (simple/resumable), download, list revisions, share
- **Notification Service**: Long polling implementation for file change events
- **Delta Sync**: Calculate changed blocks using hash comparison
- **Conflict Resolution**: Detect concurrent modifications, present merge options
- **Version Management**: Track file history with retention policies

### 🔄 Simulating

- **Cloud Storage**: Use local filesystem instead of S3 (document the mapping)
- **Load Balancer**: Single API server instance (explain multi-instance strategy)
- **Metadata Cache**: In-memory cache instead of Redis (show Redis integration points)
- **Offline Queue**: In-memory queue vs distributed message broker
- **Multi-region Replication**: Single datacenter simulation

### ⏭️ Skipping

- **Collaborative Editing**: Real-time CRDT/OT algorithms
- **Mobile Push Notifications**: APNs/FCM integration
- **CDN Integration**: Edge caching for downloads
- **Advanced Security**: 2FA, OAuth flows, encryption key management
- **Analytics**: Usage tracking, storage quotas enforcement

## Technology Choices

| Tool | Why | Alternative |
|------|-----|-------------|
| **FastAPI** | Async support for long polling, auto-docs | Flask (no async), Django (heavier) |
| **PostgreSQL** | Native ACID for strong consistency | MySQL (less features), MongoDB (no ACID) |
| **SQLAlchemy** | Type-safe ORM with async support | Raw SQL (verbose), Prisma (not Python) |
| **Pydantic** | Data validation, serialization | Dataclasses (no validation), Marshmallow |
| **asyncio** | Non-blocking I/O for concurrent uploads | Threading (GIL issues), multiprocessing |
| **hashlib (SHA-256)** | Block hashing for deduplication | MD5 (collisions), UUID (not content-based) |
| **gzip/bzip2** | Standard compression libraries | zstandard (not stdlib), lz4 (less compression) |

## Key Architecture Decisions

### 1. Block-Level Storage

> [!question] Trade-off: Whole-file vs Block-level Storage
> **Options**:
> - Upload entire files on every change
> - Split files into blocks, sync only changed blocks
>
> **Choice**: Block-level with 4MB chunks (Dropbox standard)
>
> **Reasoning**:
> - Bandwidth reduction: 10 GB file with 1 MB change = 4 MB transfer vs 10 GB
> - Deduplication: Identical blocks across files/users share storage
> - Resumability: Failed uploads resume from last completed block
>
> **Cost**: Increased complexity in chunking logic, metadata overhead

### 2. Strong Consistency Model

> [!question] Trade-off: Eventual vs Strong Consistency
> **Options**:
> - Eventual consistency (faster, complex conflict resolution)
> - Strong consistency (ACID, simpler logic)
>
> **Choice**: Strong consistency for metadata
>
> **Reasoning**:
> - File storage cannot tolerate divergent views (data loss risk)
> - Users expect immediate reflection of changes
> - ACID properties simplify conflict detection
>
> **Cost**: Potential latency in high-traffic scenarios, limits horizontal scaling

### 3. Long Polling vs WebSockets

> [!question] Trade-off: Notification Mechanism
> **Options**:
> - WebSockets: Bidirectional, persistent connections
> - Long polling: Client holds connection until event
> - Server-Sent Events: Unidirectional streaming
>
> **Choice**: Long polling (following Dropbox)
>
> **Reasoning**:
> - Unidirectional: Server → Client only
> - Infrequent updates: Not real-time chat
> - Simpler scaling: Stateless reconnections
> - Firewall-friendly: Uses standard HTTP
>
> **Cost**: Slightly higher latency than WebSockets, reconnection overhead

### 4. First-Write-Wins Conflict Resolution

> [!question] Trade-off: Conflict Handling Strategy
> **Options**:
> - Last-write-wins (simple, data loss risk)
> - First-write-wins (safe, manual merge required)
> - Operational transformation (complex, real-time)
>
> **Choice**: First-write-wins with user-driven merge
>
> **Reasoning**:
> - Preserves both versions (no silent data loss)
> - Simple to implement without CRDT complexity
> - Users understand merge process
>
> **Cost**: User intervention required, potential friction

### 5. Centralized Block Processing

> [!question] Trade-off: Client-side vs Server-side Processing
> **Options**:
> - Client handles chunking/compression/encryption
> - Server-side block servers handle processing
>
> **Choice**: Server-side block servers
>
> **Reasoning**:
> - Single implementation (vs iOS/Android/Web)
> - Security: Encryption keys not on client
> - Consistency: Uniform block sizes/algorithms
> - Client simplicity: Thin client design
>
> **Cost**: Extra network hop (client → block server → S3)

## Database Schema Design

```sql
-- Core tables (simplified)
User (id, email, username, created_at)
Device (id, user_id, push_id, last_active)
Namespace (id, user_id, root_path)
File (id, namespace_id, name, path, current_version_id, updated_at)
FileVersion (id, file_id, version_number, size, created_at) -- immutable
Block (id, file_version_id, block_index, hash, size, storage_path, encrypted)
```

> [!info] Design Notes
> - **FileVersion immutability**: Ensures revision history integrity
> - **Block hash uniqueness**: Enables deduplication across users
> - **Namespace isolation**: User data separation for security
> - **Device tracking**: Per-device sync state management

## Storage Optimization Strategies

| Technique | Implementation | Savings |
|-----------|----------------|---------|
| **Deduplication** | Hash-based block matching | ~30% (identical files/blocks) |
| **Version limits** | Keep last N versions (configurable) | Prevents unbounded growth |
| **Valuable versions** | Weight recent edits, prune old | Smart retention for active files |
| **Cold storage** | Move old versions to S3 Glacier | 90% cost reduction |
| **Compression** | Gzip (text), specialized (media) | 50-70% for text files |

## Failure Scenarios & Handling

| Failure | Detection | Recovery | Implementation |
|---------|-----------|----------|----------------|
| Load balancer down | Health check timeout | Secondary LB takes over | Active-passive failover |
| Block server crash | Job heartbeat missing | Pending jobs reassigned | Job queue with TTL |
| S3 unavailable | API error | Fetch from replica region | Multi-region replication |
| API server crash | LB health check | Traffic rerouted | Stateless servers |
| Metadata cache failure | Connection error | Query DB directly | Cache-aside pattern |
| DB master down | Replication lag spike | Promote slave to master | Master-slave replication |
| Notification server down | Connection drop | Clients reconnect | Connection pooling |
| Offline queue failure | Queue health check | Failover to replica queue | Queue replication |

## API Design

### 1. Upload File (Resumable)

```
POST /api/v1/files/upload?uploadType=resumable
Headers: Authorization: Bearer <token>
Body: multipart/form-data

Flow:
1. Client → API: Request resumable URL
2. API → Client: Return upload session URL
3. Client → Block Server: Stream file chunks
4. Block Server: Process (chunk → compress → encrypt → store)
5. Block Server → API: Completion callback
6. API → Notification: Trigger file.uploaded event
```

### 2. Download File

```
GET /api/v1/files/download?path=/folder/file.txt
Headers: Authorization: Bearer <token>

Flow:
1. Client → API: Request file
2. API → DB: Fetch file metadata + block list
3. API → Client: Return block manifest
4. Client → Block Server: Download blocks
5. Client: Reconstruct file from blocks
```

### 3. List File Revisions

```
GET /api/v1/files/revisions?path=/file.txt&limit=20
Response: [
  {version: 5, timestamp: "2025-12-31T10:00:00Z", size: 1024},
  {version: 4, timestamp: "2025-12-30T15:30:00Z", size: 1020}
]
```

## Open Questions

- [ ] **Compression algorithm selection**: Auto-detect file type or user-configurable?
- [ ] **Block size tuning**: 4MB optimal for all use cases or adaptive based on file type?
- [ ] **Version retention policy**: Default to last 10 versions or time-based (30 days)?
- [ ] **Conflict resolution UI**: CLI demo or simulated UI flow?
- [ ] **Encryption**: Symmetric (AES-256) or asymmetric? Key management strategy?
- [ ] **Rate limiting**: Per-user upload quotas to prevent abuse?

## Interview Preparation Angles

This implementation prepares for questions about:

1. **Distributed systems**: Consistency models, replication, partitioning
2. **Storage systems**: Block storage, deduplication, versioning
3. **Optimization**: Delta sync, compression, caching strategies
4. **Real-time systems**: Long polling, notification delivery
5. **Scalability**: Sharding, load balancing, queue-based processing
6. **Reliability**: Failure handling, data durability, conflict resolution

---

**Next Steps**: Proceed to architecture design with detailed component diagrams.
