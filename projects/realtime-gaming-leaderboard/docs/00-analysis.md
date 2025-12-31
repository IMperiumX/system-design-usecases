---
tags:
  - system-design
  - realtime-gaming-leaderboard
  - redis
  - sorted-sets
  - analysis
created: 2025-12-31
status: in-progress
source: "System Design Interview Vol 2 - Chapter 10: Real-time Gaming Leaderboard"
---

# Real-time Gaming Leaderboard — Analysis

## Overview

A real-time leaderboard system for a mobile game that tracks player rankings based on match wins. With 5M daily active users (DAU) and 25M monthly active users (MAU), the system must efficiently handle score updates, display top players, and show individual player rankings with near-zero latency. The leaderboard resets monthly for new tournaments.

## Core Components

| Component | Purpose | Simulates |
|-----------|---------|-----------|
| **Game Service** | Validates match wins and triggers score updates | Server-authoritative game logic |
| **Leaderboard Service** | Manages score updates and ranking queries | Microservice architecture |
| **Redis Sorted Sets** | Stores leaderboard with O(log n) operations | Production Redis cluster |
| **PostgreSQL** | Stores user profiles and game history | Persistent relational storage |
| **API Layer (DRF)** | RESTful endpoints for score updates and queries | API Gateway / Load balancer |

## Concepts Demonstrated

> [!tip] Key Learning Areas
> - [[redis-sorted-sets]]: Redis sorted sets with skip list internals for O(log n) ranking operations
> - [[skip-list]]: Probabilistic data structure enabling fast search/insert/delete (alternative to balanced trees)
> - [[sharding-strategies]]: Fixed partition vs hash partition approaches for horizontal scaling
> - [[scatter-gather]]: Query pattern for aggregating results from multiple shards
> - [[write-sharding]]: Distributing writes across partitions to avoid hot spots
> - [[time-complexity]]: O(log n) vs O(n) trade-offs for leaderboard operations
> - [[caching-strategies]]: Redis as primary data store vs cache
> - [[serverless-architecture]]: AWS Lambda + API Gateway pattern (discussed but not implemented)

## Concepts From Chapter

### Redis Sorted Sets

**What they are**: Key-value pairs where each member has an associated score. Members are automatically sorted by score.

**Internal structure**:
- Hash table: Maps users → scores (O(1) lookup)
- Skip list: Maps scores → users (O(log n) range queries)

**Key operations**:
- `ZADD`: Insert/update user score - O(log n)
- `ZINCRBY`: Increment user score - O(log n)
- `ZREVRANGE`: Get top N players - O(log n + m) where m = N
- `ZREVRANK`: Get user's rank - O(log n)

### Skip Lists

A skip list is a probabilistic data structure with multiple levels of linked lists. Each level "skips" some nodes to enable fast traversal:

```
Level 3: 1 -----------------> 45 ------> 89
Level 2: 1 -------> 23 -----> 45 ------> 89
Level 1: 1 -> 12 -> 23 -> 34 -> 45 -> 67 -> 89
```

Searching for 45 only requires 11 node visits vs 62 in a flat linked list (with 5 index levels).

### Sharding Strategies

**Fixed Partition** (recommended):
- Split by score ranges (e.g., 0-100, 101-200, etc.)
- Top 10 always in highest shard
- Requires secondary cache to track user → shard mapping
- User rank = local rank + count of users in higher shards

**Hash Partition** (Redis Cluster):
- CRC16(user_id) % 16384 to determine shard
- Auto-balancing across nodes
- Top 10 requires scatter-gather across all shards
- Doesn't solve individual user ranking efficiently

## Scope Decision

### ✅ Building (MVP)

- **Django models**: User, Game, Score tracking
- **Redis integration**: Real sorted sets with ZINCRBY, ZREVRANGE, ZREVRANK
- **Leaderboard service**: Score updates, top 10 retrieval, user rank lookup
- **RESTful API**: POST /scores (update), GET /scores (top 10), GET /scores/:user_id (rank)
- **Monthly leaderboards**: Separate sorted sets per month (e.g., `leaderboard_2025_01`)
- **Demo script**: Simulate game wins and query leaderboard
- **Docker Compose**: Redis + PostgreSQL containerized setup

### 🔄 Simulating

- **Game Service**: Simple function to validate wins (not a separate microservice)
- **Sharding**: Single Redis instance (will document sharding in architecture)
- **Load balancer**: Direct API calls (not behind nginx/HAProxy)
- **Serverless**: Traditional Django server (not Lambda functions)

### ⏭️ Skipping

- **Multi-region deployment**: Global distribution with CDN
- **WebSocket real-time updates**: Push notifications to clients
- **Advanced tie-breaking**: Timestamp-based ranking for same scores
- **User profile cache**: Redis hash for top 10 player details
- **Analytics service**: Game history analysis, ML recommendations
- **NoSQL alternative**: DynamoDB implementation (documented only)

## Technology Choices

| Tool | Why |
|------|-----|
| **Django** | Batteries-included framework with ORM, migrations, admin panel for rapid development |
| **Django REST Framework** | Clean serializers, viewsets, and browsable API for debugging |
| **Redis 7.x** | Production-grade sorted sets with skip list implementation |
| **PostgreSQL 15** | ACID guarantees for user data and game history (more robust than MySQL for learning) |
| **Docker Compose** | Reproducible dev environment with Redis + Postgres containers |
| **Poetry/pip** | Dependency management with locked versions |

## Trade-offs from Chapter

> [!question] Key Trade-off: MySQL vs Redis
> **Options**: Relational DB with `ORDER BY score DESC` vs Redis sorted sets
> **Choice**: Redis sorted sets
> **Reasoning**:
> - MySQL sorting 25M rows takes 10+ seconds (O(n log n))
> - Redis sorted sets maintain order on insert (O(log n))
> - Can't cache MySQL results due to constant updates
> - MySQL better for batch processing, not real-time

> [!question] Key Trade-off: Fixed Partition vs Hash Partition
> **Options**: Score-based sharding vs user-id hashing
> **Choice**: Fixed partition (if scaling to 500M DAU)
> **Reasoning**:
> - Top 10 always in highest shard (no scatter-gather)
> - User rank = local rank + higher shard counts (efficient)
> - Hash partition requires querying all shards for top 10
> - Trade-off: Need secondary cache for user → shard mapping

> [!question] Key Trade-off: Serverless vs Traditional Server
> **Options**: AWS Lambda + API Gateway vs Django on EC2
> **Choice**: Chapter recommends Lambda for auto-scaling
> **For this project**: Django (easier to learn/debug)
> **Reasoning**:
> - Lambda auto-scales with DAU growth
> - No server management
> - Pay-per-request pricing
> - But Django better for local development and learning

## Back-of-the-Envelope Calculations

**From chapter**:

| Metric | Calculation | Result |
|--------|-------------|--------|
| **Average users/sec** | 5M DAU / 86,400 sec | ~58 users/sec |
| **Peak load (5x)** | 58 × 5 | ~290 users/sec |
| **Score updates QPS** | 58 × 10 games/day | ~580/sec (2,900 peak) |
| **Top 10 fetch QPS** | Once per day per user | ~58/sec |
| **Storage (worst case)** | 25M MAU × 26 bytes | ~650 MB |
| **With overhead (2x)** | Skip list + hash table | ~1.3 GB |

**Conclusion**: Single Redis instance handles 5M DAU easily. Need sharding at 500M DAU (65 GB + 250K QPS).

## Open Questions

- [x] Should we implement tie-breaking with timestamps? → **Bonus feature, skip for MVP**
- [x] Monthly leaderboard reset strategy? → **New sorted set each month, archive old ones**
- [x] How to handle user not in top 10? → **ZREVRANK returns exact rank regardless**
- [x] Should we cache user profiles for top 10? → **Skip for MVP, query DB**
- [ ] How to test Redis sorted set performance locally? → **Use redis-benchmark tool**
- [ ] Should we implement the ±4 positions bonus feature? → **Yes, use ZREVRANGE with calculated offsets**

## Next Steps

Proceed with **Phase 2: Architecture Document** to design:
1. System diagram with client → API → Redis → DB flow
2. API endpoint specifications
3. Data models (User, Game, LeaderboardEntry)
4. Redis key naming strategy (`leaderboard_{YYYY}_{MM}`)
5. Service layer structure
