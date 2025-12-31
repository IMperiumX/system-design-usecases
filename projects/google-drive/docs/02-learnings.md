---
tags:
  - system-design
  - google-drive
  - learnings
  - interview-prep
created: 2025-12-31
status: complete
related:
  - "[[00-analysis]]"
  - "[[01-architecture]]"
---

# Google Drive — Learnings & Interview Prep

## What I Built

A functional Google Drive clone implementing core cloud storage concepts: block-level storage with 4MB chunks, delta sync for bandwidth optimization, SHA-256 based deduplication, strong consistency via PostgreSQL ACID, long polling notifications, and conflict resolution. The system handles file upload/download, version history, and real-time synchronization across devices.

## Key Takeaways

> [!tip] Core Insight #1: Block-Level Storage is the Foundation
> Splitting files into fixed 4MB blocks (Dropbox standard) enables three critical optimizations:
> 1. **Delta Sync**: Only upload changed blocks on edits (90% bandwidth savings)
> 2. **Deduplication**: Identical blocks across files/users share storage (30% savings)
> 3. **Resumability**: Failed uploads resume from last completed block
>
> **Trade-off**: Increased complexity (chunking logic, metadata overhead) vs massive bandwidth/storage savings

> [!tip] Core Insight #2: Strong Consistency is Non-Negotiable for File Storage
> Unlike eventual consistency (NoSQL), file storage demands strong consistency:
> - Users cannot tolerate divergent file states across devices
> - ACID properties simplify conflict detection (compare timestamps)
> - Cache invalidation on every write prevents stale reads
>
> **Cost**: Limits horizontal scaling (master bottleneck), potential latency at high QPS
>
> **Why PostgreSQL over MongoDB**: Native ACID support, relational schema fits file hierarchies

> [!tip] Core Insight #3: Long Polling vs WebSockets - Choose Based on Traffic Pattern
> Google Drive uses long polling (Dropbox too) instead of WebSockets because:
> - **Unidirectional**: Server → Client only (no need for bidirectional)
> - **Infrequent updates**: File sync events happen irregularly (not real-time chat)
> - **Simpler infrastructure**: Stateless HTTP (easier load balancing, reconnection)
> - **Firewall-friendly**: Standard HTTP/HTTPS
>
> **When WebSockets win**: Real-time bidirectional apps (chat, gaming, live collab editing)

> [!tip] Core Insight #4: First-Write-Wins Conflict Resolution
> When two users edit the same file concurrently:
> - **Strategy**: First upload to reach server wins
> - **Loser notification**: Receives sync conflict with both versions
> - **User choice**: Merge manually, keep local, or keep server
>
> **Why not last-write-wins**: Silent data loss (dangerous!)
> **Why not CRDT/OT**: Complex, only needed for real-time collaborative editing (Google Docs)

> [!tip] Core Insight #5: Compression Algorithm Selection Matters
> - **Text files**: gzip (50-70% reduction)
> - **Images** (JPEG, PNG): Already compressed, skip or use specialized
> - **Videos** (H.264): Already compressed, skip
> - **PDFs**: Mixed content, moderate compression
>
> **Key insight**: Content-aware compression (detect file type, choose algorithm)

## Concepts Reinforced

- **[[block-level-storage]]** — Now understand how chunking enables delta sync and deduplication
- **[[strong-consistency]]** — The trade-off between consistency guarantees and scalability
- **[[cache-invalidation]]** — Why "invalidate on write" is critical for correctness
- **[[long-polling]]** — Persistent HTTP connections for near-real-time updates
- **[[deduplication]]** — Content-addressed storage (hash as identifier)
- **[[delta-sync]]** — Rsync algorithm adapted for cloud storage
- **[[ACID-properties]]** — Why relational DB for metadata despite NoSQL popularity
- **[[conflict-resolution]]** — First-write-wins vs last-write-wins vs CRDT
- **[[horizontal-scaling]]** — Sharding strategies (by user_id), read replicas
- **[[multi-region-replication]]** — S3's 11 nines durability via replication

## At Scale

| Scale | What Changes | Implementation Details |
|-------|--------------|------------------------|
| **10x users** (100M DAU) | Add read replicas for metadata DB | Master-slave replication, reads from slaves |
| | Scale block servers horizontally | Worker pool behind queue (RabbitMQ) |
| | Multi-AZ deployment | Primary + secondary datacenter |
| **100x users** (1B DAU) | Shard metadata database | Shard by user_id (1024 logical → 16 physical) |
| | Distribute notification servers | Regional servers + Redis pub/sub for events |
| | CDN for downloads | CloudFront caching popular files |
| **1000x users** (10B DAU) | Multi-region architecture | Geo-distributed DCs, route by proximity |
| | Separate read/write paths | CQRS pattern (Command Query Responsibility Segregation) |
| | Event-driven architecture | Kafka for event streaming between services |

## Interview Prep

### Clarifying Questions to Ask

When given "Design Google Drive" prompt:

1. **Scale & Users**:
   - How many DAU (daily active users)?
   - How many total users?
   - What's the expected upload/download QPS?
   - Average file size? Max file size?

2. **Features & Scope**:
   - Upload/download only, or also file sharing?
   - Need version history? How many versions?
   - Mobile, web, or both?
   - Collaborative editing (Google Docs) or just sync?

3. **Consistency & Availability**:
   - Strong consistency required, or eventual OK?
   - Tolerate any data loss? (answer: NO for file storage)
   - Latency SLAs? (e.g., upload in < 5s for 10MB file)

4. **File Types & Optimization**:
   - Any file type, or specific (images, videos, docs)?
   - Should we optimize for large files (resumable upload)?
   - Compression requirements?

5. **Constraints**:
   - Use existing cloud storage (S3) or build custom?
   - Security requirements (encryption at rest/in transit)?
   - Compliance needs (GDPR, data residency)?

### How I'd Explain This (5 min)

> **"Let me walk through the high-level design first..."**

**1. Requirements Summary** (30 sec)
- "We're building a file storage and sync service for 10M DAU, supporting upload/download, multi-device sync, version history, and sharing. Key non-functional requirements are zero data loss, fast sync, and bandwidth efficiency."

**2. High-Level Architecture** (90 sec)
- "The system has four main layers:
  1. **Edge**: Load balancers distributing traffic to API servers
  2. **Application**: API servers (stateless), block servers (process files)
  3. **Data**: PostgreSQL for metadata (ACID), S3 for file blocks
  4. **Async**: Notification service (long polling), offline queue

- Files are split into 4MB blocks, each compressed and encrypted before S3 upload.
- Metadata DB tracks file versions and block hashes.
- Notification service uses long polling to push file changes to clients."

**3. Key Design Decisions** (90 sec)
- "**Block storage**: Fixed 4MB chunks enable delta sync (only upload changed blocks) and deduplication (reuse identical blocks). This saves 90% bandwidth on edits.

- **Strong consistency**: PostgreSQL with ACID guarantees prevents divergent file states. Cache invalidated on every write.

- **Long polling**: More suitable than WebSockets for infrequent, unidirectional updates. Simpler infrastructure.

- **First-write-wins**: On concurrent edits, first upload wins. Loser gets conflict notification with merge option."

**4. Upload Flow** (60 sec)
- "Client → API: Initiate upload, get session ID
- Client → Block server: Stream file, chunked into 4MB blocks
- Block server: Compress (gzip), encrypt (AES-256), upload to S3
- Block server → API: Completion webhook
- API → DB: Update file status to 'uploaded'
- API → Notification: Trigger event, push to subscribed clients"

**5. Scale Considerations** (60 sec)
- "At 100x scale:
  - Shard metadata DB by user_id (all user data on same shard)
  - Horizontal scaling of block servers via queue (Kafka)
  - Multi-region S3 for durability
  - CDN for popular downloads
  - Read replicas for metadata queries"

### Follow-up Questions to Expect

#### Q1: "How would you handle a 10x traffic spike?"

**My Answer**:
- **Horizontal scaling**: API servers are stateless, add more instances behind LB (auto-scaling group)
- **Database**: Read queries hit replicas, writes go to master (if write-heavy, shard sooner)
- **Block servers**: Queue-based (Kafka/RabbitMQ), add workers dynamically
- **S3**: Handles scale automatically (AWS scales for you)
- **Caching**: Aggressive metadata caching (Redis) to reduce DB load
- **Rate limiting**: Per-user upload limits to prevent abuse

#### Q2: "What if S3 becomes unavailable in us-east-1?"

**My Answer**:
- **Multi-region replication**: S3 cross-region replication (us-east-1 → us-west-2)
- **Automatic failover**: On primary region failure, route uploads to secondary
- **Eventual consistency**: Replicas sync asynchronously, brief window of stale data
- **Detection**: Health checks every 30s, failover within 60s
- **User impact**: Minimal (transparent failover), uploads continue to secondary region

**Production example**: Dropbox uses multiple cloud providers (S3 + custom Magic Pocket storage)

#### Q3: "How do you detect and resolve sync conflicts?"

**My Answer**:
- **Detection**: Compare file version timestamps
  - User A uploads at 10:00:01 → succeeds (version 2)
  - User B uploads at 10:00:02 → conflict detected (still on version 1)

- **Resolution strategy**: First-write-wins
  - User A's version becomes canonical (version 2)
  - User B gets notification: "Sync conflict detected"
  - Present both versions to User B:
    - Option 1: Merge manually (we provide diff view)
    - Option 2: Keep local (override server)
    - Option 3: Keep server (discard local)

- **Implementation**:
  ```python
  if incoming_timestamp <= current_file.updated_at:
      conflict = SyncConflict(local_version, server_version)
      notify_user(conflict)
  ```

**Why not CRDT**: Too complex for simple file sync. Only needed for real-time collaborative editing (Google Docs).

#### Q4: "How would you optimize bandwidth for large files?"

**My Answer**:
- **Delta sync**: Only upload changed blocks (implemented via hash comparison)
  - 1 GB file, 10 MB change → upload 1 block (4 MB) instead of 1 GB
  - Savings: 99.6%

- **Resumable uploads**: Break into blocks, track progress
  - If upload fails at block 50, resume from block 51 (not start over)

- **Compression**: gzip for text (50-70% reduction)
  - Skip for already-compressed (JPEG, MP4)

- **Client-side dedup**: Before upload, check if blocks exist on server
  - Send hash list → server responds with "already have blocks 1, 3, 5"
  - Client only uploads missing blocks

- **Multipart upload**: Upload blocks in parallel (S3 multipart upload API)
  - 1 GB file = 250 blocks → upload 10 blocks concurrently

#### Q5: "How would you monitor this system?"

**My Answer**:

**Key Metrics** (Prometheus + Grafana):
- **Throughput**: upload_requests_per_second, download_requests_per_second
- **Latency**: upload_p50_latency_ms, upload_p99_latency_ms (alert if p99 > 5s)
- **Errors**: upload_failure_rate (alert if > 1%), sync_conflict_rate
- **Resources**: block_server_cpu_util (alert if > 80%), db_connection_pool_usage
- **Business**: total_files_count, storage_deduplication_ratio

**Alerting**:
- Critical: DB master down, S3 unavailable → Page on-call
- Warning: P99 latency > 5s, CPU > 80% → Slack alert

**Logging** (ELK stack):
- Structured logs: JSON format
- Trace IDs: Track request across services
- Error tracking: Sentry for exceptions

**Distributed tracing**: Jaeger for upload flow visualization

#### Q6: "How do you ensure data security?"

**My Answer**:

**Encryption**:
- **At rest**: AES-256 encryption before S3 upload
- **In transit**: TLS 1.3 for all client-server communication
- **Key management**: AWS KMS for encryption keys (per-user keys)

**Authentication**:
- JWT tokens (short-lived, 30 min expiry)
- Refresh tokens (long-lived, stored securely)

**Authorization**:
- File access control: Owner + explicitly shared users
- Row-level security: Users can only query their own files

**Compliance**:
- GDPR: User data deletion within 30 days
- Audit logs: Who accessed what file, when

**Attack prevention**:
- Rate limiting: 100 requests/min per user
- Input validation: File path sanitization (prevent directory traversal)
- DDoS protection: CloudFlare in front of LB

#### Q7: "What about versioning and storage costs?"

**My Answer**:

**Versioning strategy**:
- Keep last 10 versions by default (configurable per user)
- Intelligent retention:
  - Recent versions: Keep all (last 7 days)
  - Older versions: Keep 1 per week (7-30 days ago)
  - Ancient versions: Keep 1 per month (> 30 days)

**Storage optimization**:
- **Deduplication**: 30% savings (identical blocks across files/users)
- **Compression**: 50-70% for text files
- **Cold storage**: Move versions > 90 days to S3 Glacier (90% cost reduction)
  - Standard S3: $0.023/GB/month
  - Glacier: $0.004/GB/month
- **Deleted file handling**: Soft delete for 30 days (trash), then hard delete

**Cost at scale**:
- 10M users × 10 GB = 100 PB
- After dedup (30%) + compression (60%): 28 PB
- Cost: 28 PB × $0.023/GB = $644k/month (S3 standard)
- With Glacier for 80% data: $193k/month

## Extensions to Explore

- [ ] Implement true Redis caching (replace in-memory dict)
- [ ] Add file sharing with expiration links (e.g., expires in 7 days)
- [ ] Implement storage quotas per user (track usage, enforce limits)
- [ ] Add CDN simulation for downloads (cache popular files at edge)
- [ ] Implement smart version retention policies (time-based, size-based)
- [ ] Add metrics dashboard (Prometheus + Grafana)
- [ ] Implement database sharding strategy (consistent hashing)
- [ ] Add rate limiting per user (token bucket algorithm)
- [ ] Implement trash/recycle bin (soft delete with 30-day retention)
- [ ] Add file search (full-text search with Elasticsearch)

## Related Implementations

- **[[url-shortener]]** — Simpler key-value storage pattern, good starting point
- **[[key-value-store]]** — Deep dive into storage engines (LSM tree, B+ tree)
- **[[chat-system]]** — Real-time messaging (compares WebSocket vs long poll)
- **[[pastebin]]** — Similar to Google Drive but simpler (no sync, no versions)

## Real-World Comparisons

### Dropbox Architecture (from their tech talks)

| Aspect | Our Implementation | Dropbox Production |
|--------|-------------------|-------------------|
| Block size | 4 MB (configurable) | 4 MB fixed |
| Storage | S3 simulation | Magic Pocket (custom) + S3 |
| Metadata DB | PostgreSQL | MySQL (sharded) |
| Notification | Long polling | Long polling |
| Deduplication | SHA-256 hash | SHA-256 hash |
| Workers | In-process | Celery distributed workers |
| Scale | Demo | 700M+ users, 500 PB data |

### Google Drive Differences

| Feature | Dropbox | Google Drive | Our Implementation |
|---------|---------|--------------|-------------------|
| Collaborative editing | No | Yes (Google Docs) | No |
| Block size | 4 MB | Unknown (likely similar) | 4 MB |
| Consistency | Strong | Strong | Strong |
| Conflict resolution | First-write-wins | OT/CRDT for Docs | First-write-wins |

## Code Highlights

### Most Important Files to Understand

1. **`src/services/block_processor.py`** (Lines 31-60: chunking algorithm)
   - Fixed-size chunking vs content-defined (rsync)
   - SHA-256 hashing for deduplication
   - Compression and encryption pipeline

2. **`src/services/file_service.py`** (Lines 105-175: delta sync logic)
   - Compare old version blocks vs new file blocks
   - Only upload changed blocks (bandwidth optimization)
   - Reuse existing blocks (storage optimization)

3. **`src/storage/schema.py`** (Lines 98-135: FileVersion + Block tables)
   - Immutable version table (append-only log)
   - Block.hash uniqueness constraint (deduplication)
   - Foreign key relationships

4. **`src/services/notification_service.py`** (Lines 25-60: long polling)
   - asyncio.Queue for event delivery
   - Timeout handling (60s)
   - Offline queue for disconnected clients

## What I'd Do Differently Next Time

1. **Use content-defined chunking** (variable block size like rsync) instead of fixed 4MB
   - Better deduplication for files with inserted content
   - Trade-off: More complex algorithm

2. **Implement true async workers** (Celery + RabbitMQ) instead of in-process
   - Better fault isolation
   - Easier horizontal scaling

3. **Add observability from day 1** (structured logging, metrics, tracing)
   - Hard to retrofit later
   - Critical for debugging production issues

4. **Write property-based tests** (Hypothesis) for block reconstruction
   - Ensure chunking → reassembly is lossless
   - Catch edge cases (file size = exact multiple of block size)

5. **Implement circuit breakers** for S3 calls
   - Prevent cascading failures
   - Graceful degradation

---

**Practice recommendation**: Explain this design to a friend or record yourself. Aim for 5 min, hit all key points. Iterate until confident!
