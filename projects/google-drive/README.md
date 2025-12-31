# Google Drive - System Design Implementation

A hands-on implementation of Google Drive's core architecture for learning distributed systems concepts.

## What This Teaches

This project demonstrates key system design concepts from Chapter 15 of *System Design Interview*:

- **[[block-level-storage]]** - File chunking and delta sync
- **[[strong-consistency]]** - ACID guarantees for metadata
- **[[data-deduplication]]** - Hash-based block reuse
- **[[long-polling]]** - Real-time notifications without WebSockets
- **[[conflict-resolution]]** - First-write-wins with manual merge
- **[[resumable-uploads]]** - Handle network interruptions gracefully
- **[[multi-region-replication]]** - Data durability and availability

## Architecture

```
┌─────────┐
│ Clients │───┐
└─────────┘   │
              ▼
         ┌────────┐      ┌──────────────┐
         │   LB   │─────▶│  API Servers │
         └────────┘      └──────────────┘
                               │
              ┌────────────────┼─────────────────┐
              │                │                 │
              ▼                ▼                 ▼
      ┌──────────────┐  ┌───────────┐   ┌──────────────┐
      │ Block Server │  │ Metadata  │   │ Notification │
      │  (Chunking)  │  │ Cache/DB  │   │   Service    │
      └──────────────┘  └───────────┘   └──────────────┘
              │
              ▼
      ┌──────────────┐
      │ Cloud Storage│
      │     (S3)     │
      └──────────────┘
```

See [docs/01-architecture.md](docs/01-architecture.md) for detailed diagrams.

## Features Implemented

- ✅ **File Upload** - Simple and resumable uploads (max 10 GB)
- ✅ **File Download** - Block-based file reconstruction
- ✅ **Delta Sync** - Only upload changed blocks on edits
- ✅ **Version History** - Track and retrieve file revisions
- ✅ **Conflict Resolution** - Detect concurrent edits, present merge options
- ✅ **Notifications** - Long polling for real-time file change events
- ✅ **Deduplication** - SHA-256 based block dedup across users
- ✅ **Compression** - gzip/bzip2 compression per block
- ✅ **Encryption** - AES-256 encryption at rest
- ✅ **Metadata Caching** - Redis-compatible cache layer

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (for PostgreSQL)

### Installation

```bash
# Clone and navigate
cd projects/google-drive

# Start database
make docker-up

# Install dependencies
make install

# Initialize database schema
make db-migrate

# Run demo
make demo
```

### Run API Server

```bash
make run
# API docs: http://localhost:8000/docs
```

## Demo Scenarios

The interactive demo (`make demo`) walks through:

1. **User registration and authentication**
2. **Upload a file** - See chunking, compression, encryption in action
3. **Edit file** - Observe delta sync (only changed blocks uploaded)
4. **Concurrent edits** - Trigger sync conflict, resolve manually
5. **Version history** - List and download previous versions
6. **Share file** - Generate shared link
7. **Notifications** - Watch real-time sync events

## Project Structure

```
.
├── docs/
│   ├── 00-analysis.md      # Requirements, scope, trade-offs
│   ├── 01-architecture.md  # System diagrams, component deep-dive
│   ├── 02-learnings.md     # Key takeaways, interview prep
│   └── 03-changelog.md     # Implementation history
├── src/
│   ├── config.py           # Settings, environment vars
│   ├── models.py           # Pydantic data models
│   ├── storage/
│   │   ├── database.py     # SQLAlchemy setup
│   │   ├── schema.py       # DB models (User, File, Block, etc.)
│   │   └── s3_simulator.py # Local filesystem as S3
│   ├── services/
│   │   ├── block_processor.py    # Chunking, compression, encryption
│   │   ├── file_service.py       # Upload/download orchestration
│   │   ├── notification_service.py  # Long polling implementation
│   │   ├── conflict_resolver.py  # Sync conflict detection
│   │   └── cache_service.py      # Metadata caching
│   └── api.py              # FastAPI endpoints
├── tests/
│   ├── test_block_processor.py
│   ├── test_delta_sync.py
│   └── test_conflict_resolution.py
├── scripts/
│   └── demo.py             # Interactive demo
└── storage/                # Simulated S3 (local filesystem)
    ├── blocks/             # Encrypted file blocks
    └── metadata/           # Storage manifests
```

## Key Concepts Demonstrated

### 1. Block-Level Storage

Files are split into 4MB chunks (Dropbox standard). Each block is:
- Hashed (SHA-256) for deduplication
- Compressed (gzip for text, specialized for media)
- Encrypted (AES-256)
- Stored independently in S3

**Code**: `src/services/block_processor.py`

### 2. Delta Sync

Only modified blocks are uploaded on file edits:

```python
# Compare old version blocks vs new file blocks
old_hashes = {block.index: block.hash for block in old_version.blocks}
new_blocks = chunk_file(new_file)

changed = [b for b in new_blocks if old_hashes.get(b.index) != b.hash]
# Upload only `changed` blocks!
```

**Bandwidth savings**: 90% reduction on typical edits

### 3. Strong Consistency

PostgreSQL ACID guarantees prevent divergent file states:
- Cache invalidation on every write
- Synchronous replication to slaves
- Conflict detection via version timestamps

**Code**: `src/storage/database.py`

### 4. Long Polling

Clients hold HTTP connections open (60s timeout) until file change events:

```python
# Client
while True:
    event = await GET("/api/v1/notifications/poll")
    if event:
        sync_file(event.file_id)
```

**Trade-off**: Simpler than WebSockets, sufficient for infrequent updates

## Interview Prep

This implementation prepares you for:

**Clarifying questions**:
- What's the expected scale (DAU, storage, QPS)?
- What file types (text vs binary affects compression)?
- Consistency requirements (strong vs eventual)?
- Latency SLAs (real-time vs near-real-time)?

**Follow-up deep dives**:
- How would you handle 10x traffic spike?
  → *Load balancer auto-scaling, database read replicas, CDN for downloads*
- What if S3 is unavailable?
  → *Multi-region replication, fallback to secondary region*
- How to detect and resolve sync conflicts?
  → *Compare version timestamps, present both versions to user*
- How to optimize bandwidth?
  → *Delta sync, compression, deduplication*

See [docs/02-learnings.md](docs/02-learnings.md) for full interview guide.

## Simplifications vs Production

| Aspect | This Implementation | Production (Google/Dropbox) |
|--------|---------------------|------------------------------|
| Storage | Local filesystem | Multi-region S3/GCS clusters |
| Database | Single PostgreSQL | Sharded DB across 1000s nodes |
| Cache | In-memory dict | Distributed Redis cluster |
| Load balancer | None | Multi-layer LB hierarchy |
| Notifications | Long poll (1 server) | WebSocket cluster (1M conn/server) |
| Encryption | Single AES key | Per-user key encryption (KMS) |
| Auth | Simple JWT | OAuth 2.0, 2FA, device trust |

## Extensions to Try

- [ ] Implement true Redis caching (replace in-memory)
- [ ] Add file sharing with expiration links
- [ ] Implement storage quotas per user
- [ ] Add CDN simulation for downloads
- [ ] Implement versioning retention policies
- [ ] Add metrics dashboard (Prometheus + Grafana)
- [ ] Implement sharding strategy for metadata DB

## Resources

- **System Design Interview** - Chapter 15: Design Google Drive
- [Dropbox scaling talk](https://youtu.be/PE4gwstWhmc) - Engineering insights
- [rsync algorithm](https://rsync.samba.org/tech_report/) - Delta sync foundation
- [S3 documentation](https://aws.amazon.com/s3/) - Object storage patterns

## Related Implementations

- [[url-shortener]] - Simpler key-value storage pattern
- [[key-value-store]] - Deep dive into storage engines
- [[chat-system]] - Real-time messaging (WebSocket vs long poll)

---

**Learning path**: Start with `make demo`, read `docs/00-analysis.md`, then explore code in this order:
1. `src/models.py` - Data structures
2. `src/services/block_processor.py` - Core chunking logic
3. `src/services/file_service.py` - Upload/download orchestration
4. `src/api.py` - API endpoints

Happy learning! 🚀
