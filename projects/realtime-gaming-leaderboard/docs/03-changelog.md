---
tags:
  - system-design
  - realtime-gaming-leaderboard
  - changelog
  - implementation-log
created: 2025-12-31
---

# Real-time Gaming Leaderboard — Changelog

## 2025-12-31 - Initial Implementation

### Phase 1: Requirements Analysis ✅

**Added:**
- Comprehensive requirements document (`docs/00-analysis.md`)
- Back-of-the-envelope calculations for 5M DAU and 500M DAU scenarios
- Technology stack justification (Django + DRF + Redis + PostgreSQL)
- Scope decisions (MVP vs. bonus features vs. out-of-scope)

**Key Decisions:**
- **Redis sorted sets over MySQL**: O(log n) vs O(n log n) performance
- **Fixed partition sharding** for 500M DAU scale (documented, not implemented)
- **Django over FastAPI**: Better ecosystem for learning, admin panel for debugging
- **PostgreSQL over MySQL**: More robust for learning, better JSON support

**Trade-offs Documented:**
- Real-time vs. eventual consistency (chose real-time for MVP)
- Serverless (AWS Lambda) vs. traditional server (chose Django for simplicity)
- Single Redis instance vs. cluster (single for 5M DAU, documented sharding strategy)

---

### Phase 2: Architecture Design ✅

**Added:**
- System architecture diagrams (Mermaid format) in `docs/01-architecture.md`
- Sequence diagrams for score updates, top 10 queries, user rank lookups
- Detailed component breakdown (Redis store, leaderboard service, API layer, database)
- API endpoint specifications with example requests/responses
- Data model documentation (User, Game, LeaderboardSnapshot)
- Scaling strategy for 500M DAU with sharding details

**Key Design Patterns:**
- [[separation-of-concerns]]: Views → Services → Storage
- [[polyglot-persistence]]: Redis (hot) + PostgreSQL (warm) + snapshots (cold)
- [[api-design]]: RESTful endpoints with clear resource naming
- [[event-sourcing-lite]]: Game audit log as source of truth

**Notable Decisions:**
- Bonus feature (±4 surrounding players) included in scope
- Monthly leaderboard rotation with 90-day retention in Redis
- Disaster recovery via rebuild from Game audit logs

---

### Phase 3: Django Project Setup ✅

**Added:**
- Django 5.0.1 project structure with `leaderboard_project` and `core` app
- Docker Compose configuration for Redis 7 + PostgreSQL 15
- Environment variable management with `.env` file
- Requirements.txt with pinned versions:
  - Django 5.0.1
  - djangorestframework 3.14.0
  - redis 5.0.1
  - psycopg2-binary 2.9.9
- Makefile for common commands (`setup`, `demo`, `test`, `clean`)
- Virtual environment setup (venv)

**Configuration:**
- PostgreSQL as default database (not SQLite)
- Redis connection parameters in settings
- REST framework with pagination and throttling
- Django admin enabled for debugging

**Files Created:**
- `leaderboard_project/settings.py` - Configured with env vars
- `leaderboard_project/urls.py` - Root URL routing
- `docker-compose.yml` - Services with health checks
- `.env` and `.env.example` - Environment variables
- `Makefile` - Development workflow automation

---

### Phase 4: Data Models Implementation ✅

**Added:**
- `core/models.py` with three Django ORM models:

**User Model:**
- UUID primary key for distributed systems
- Username (unique, indexed) and display_name
- Avatar URL for CDN-hosted images
- Timestamp for account creation
- **Docstring**: Explains role in polyglot persistence

**Game Model** (Audit Log):
- BigInt auto-incrementing ID for time-series data
- ForeignKey to User with CASCADE delete
- score_earned (default: 1 per win)
- match_id UUID for cross-service referencing
- leaderboard_month indexed for query performance
- **Indexes**: Composite indexes on (user, played_at) and (month, played_at)
- **Docstring**: Explains event sourcing pattern

**LeaderboardSnapshot Model:**
- Monthly archival of final rankings
- Unique constraint on (user, month)
- final_rank and final_score for historical queries
- **Docstring**: Explains data lifecycle management

**Design Choices:**
- Used help_text on all fields for admin panel clarity
- Added verbose_name and verbose_name_plural for readability
- Optimized Meta options (db_table, ordering, indexes)
- Comprehensive `__str__` and `__repr__` methods

**System Design Concepts Demonstrated:**
- [[time-series-data]]: Games table partitionable by month
- [[audit-logging]]: Every match recorded for recovery
- [[data-archival]]: Snapshot model for historical queries

---

### Phase 5: Redis Storage Layer ✅

**Added:**
- `core/storage/redis_store.py` - RedisLeaderboardStore class

**Key Methods Implemented:**
- `increment_score()`: ZINCRBY with O(log n) complexity
- `get_user_score()`: ZSCORE with O(1) lookup
- `get_user_rank()`: ZREVRANK with 1-indexed rank
- `get_top_n()`: ZREVRANGE for top K players
- `get_range()`: ZREVRANGE with start/end positions
- `get_surrounding_players()`: Bonus feature (±offset positions)
- `get_leaderboard_size()`: ZCARD for total users
- `clear_leaderboard()`: DEL for testing/cleanup
- `set_leaderboard_expiry()`: EXPIRE for lifecycle management
- `health_check()`: PING for monitoring

**Redis Commands Used:**
- ZINCRBY: Increment score (creates member if not exists)
- ZSCORE: Get member's score
- ZREVRANK: Get rank in descending order (0-indexed)
- ZREVRANGE: Get range of members with scores
- ZCARD: Count members
- EXPIRE: Set TTL
- PING: Health check

**Docstrings Include:**
- Time complexity for each operation
- System design concepts ([[skip-list-search]], [[sorted-set-insert]])
- Production considerations (sharding, read replicas)
- Example usage with expected input/output

**Design Decisions:**
- Redis key naming: `leaderboard_{YYYY}_{MM}` for monthly rotation
- Rank conversion: ZREVRANK returns 0-indexed, we add 1 for user display
- decode_responses=True: Return strings instead of bytes for cleaner API
- Graceful degradation: Return None for missing users instead of exceptions

---

### Phase 6: Leaderboard Service Logic ✅

**Added:**
- `core/services/leaderboard_service.py` - Business logic layer

**Methods Implemented:**

**update_score():**
- Validates user exists in database
- Increments score in Redis (O(log n))
- Logs game to PostgreSQL (audit trail)
- Returns new score + rank atomically
- **Handles**: ValueError for non-existent users

**get_top_n():**
- Fetches top N from Redis
- Batch fetches user details from PostgreSQL (1 query, not N)
- Merges leaderboard + user data
- Returns enriched JSON response

**get_user_rank():**
- Gets rank and score from Redis
- Fetches user details from PostgreSQL
- Returns combined result or None

**get_surrounding_players():**
- Implements bonus feature (±4 positions)
- Calculates rank range around user
- Fetches range from Redis
- Enriches with user details
- Marks current user in results

**get_leaderboard_stats():**
- Returns total users, top score, month
- Calculates average score from Game table
- Admin/monitoring endpoint data

**archive_leaderboard():**
- Monthly cron job functionality
- Bulk creates LeaderboardSnapshot records
- Sets Redis TTL to 7 days (grace period)
- Returns count of archived users

**rebuild_from_games():**
- Disaster recovery method
- Aggregates scores from Game audit log
- Rebuilds Redis leaderboard
- Returns count of restored users

**System Design Patterns:**
- [[read-through-cache]]: Check Redis, fall back to DB
- [[write-through]]: Update Redis + log to DB
- [[bulk-operations]]: Batch fetch users to avoid N+1 queries
- [[idempotency]]: Rebuilds can be run multiple times safely

**Docstrings Include:**
- Workflow steps (numbered for clarity)
- Production considerations (Kafka, batch inserts, circuit breakers)
- At-scale modifications (message queues, async processing)

---

### Phase 7: REST API Implementation ✅

**Added:**
- `core/serializers.py` - Django REST Framework serializers
- `core/views.py` - API views (APIView subclasses)
- `core/urls.py` - URL routing for core app

**Serializers Created:**
- ScoreUpdateRequestSerializer: Validates score update requests
- ScoreUpdateResponseSerializer: Returns updated score + rank
- LeaderboardEntrySerializer: Single leaderboard entry
- LeaderboardResponseSerializer: Top N leaderboard
- UserRankResponseSerializer: User's rank details
- SurroundingPlayerSerializer: Player with is_current_user flag
- SurroundingPlayersResponseSerializer: ±N surrounding players
- LeaderboardStatsSerializer: Admin stats (total users, top score)

**API Views Implemented:**

**ScoreUpdateView** (POST /api/v1/scores):
- Validates input with serializer
- TODO: Token authentication for game service
- Calls leaderboard service
- Returns 200 OK or 404 Not Found

**LeaderboardView** (GET /api/v1/scores):
- Accepts `limit` (1-100) and `month` query params
- Validates limit range
- Returns top N with pagination

**UserRankView** (GET /api/v1/scores/{user_id}):
- Accepts `month` query param
- Returns user's rank or 404
- Privacy note: Restrict to own user_id in production

**SurroundingPlayersView** (GET /api/v1/scores/{user_id}/surrounding):
- Accepts `offset` (1-10) and `month` query params
- Returns players ±N positions
- Highlights current user

**LeaderboardStatsView** (GET /api/v1/stats):
- Admin/monitoring endpoint
- Returns leaderboard statistics

**Design Decisions:**
- Removed Swagger (drf-yasg) to keep dependencies minimal
- Used APIView instead of ViewSets for explicit control
- Docstrings include example requests/responses
- Query param validation in views (not serializers)
- Consistent error responses (404, 400 with detail messages)

**URL Patterns:**
- Clean, RESTful resource naming
- UUID path converters for type safety
- Trailing slashes for consistency

---

### Phase 8: Django Admin Panel ✅

**Added:**
- `core/admin.py` - Custom admin classes for all models

**Admin Classes:**

**UserAdmin:**
- List display: id, username, display_name, created_at
- Search by username and display_name
- Fieldsets: Identity, Profile, Metadata
- Optimized ordering

**GameAdmin:**
- List display: id, user, score_earned, month, played_at
- Filters by month and played_at
- Search by username and match_id
- raw_id_fields for User (search widget)
- select_related optimization (avoid N+1 queries)

**LeaderboardSnapshotAdmin:**
- List display: user, month, final_rank, final_score, created_at
- Filters by month
- Search by username
- Ordering by month, then rank

**Benefits for Development:**
- Quick user creation for testing
- View game history for debugging
- Verify monthly archival worked
- No need for SQL queries during development

---

### Phase 9: Interactive Demo Script ✅

**Added:**
- `scripts/demo.py` - Comprehensive demonstration

**Demo Features:**
1. Creates 50 test users with realistic gamer names
2. Simulates 500-5,000 game wins with random distribution
3. Displays top 10 leaderboard with colored output
4. Shows specific user's rank
5. Demonstrates ±4 surrounding players feature
6. Displays leaderboard statistics
7. Shows Redis sorted set internals
8. Demonstrates edge case handling

**User Experience:**
- Colored terminal output (colorama library, graceful fallback)
- Progress indicators and section headers
- Success/error/info message formatting
- Clear next steps after demo completes

**Educational Value:**
- Shows time complexities (O(log n), O(1))
- Demonstrates Redis key naming strategy
- Explains system design concepts in output
- Tests edge cases (non-existent users, empty leaderboards)

**Production Considerations Highlighted:**
- Redis health check before running
- Batch user creation (not one-by-one API calls)
- Error handling with try/except
- Graceful shutdown on Ctrl+C

---

### Phase 10: Documentation ✅

**Added:**
- `README.md` - Comprehensive project guide
- `docs/00-analysis.md` - Requirements and scope
- `docs/01-architecture.md` - System design details
- `docs/02-learnings.md` - Interview preparation
- `docs/03-changelog.md` - This file

**README Sections:**
- Quick start guide
- System architecture diagram
- API endpoint examples with curl commands
- Data model descriptions
- Performance characteristics table
- Scaling strategies (10x, 100x, 1000x)
- Debugging guides (Redis CLI, PostgreSQL queries)
- Interview preparation questions
- Project structure

**Documentation Quality:**
- Mermaid diagrams for visual learners
- Code examples with expected output
- Links between related concepts
- Obsidian-compatible wikilinks [[concept]]
- YAML frontmatter for metadata

---

## Decisions Made

### Why Django over FastAPI?

**Chose Django because:**
- Batteries-included (admin panel, ORM, migrations)
- Better for learning full-stack patterns
- Larger ecosystem of tutorials/resources
- DRF provides clean serializer patterns

**Trade-off:**
- Slightly slower than FastAPI (100ms vs 50ms)
- More boilerplate code
- Larger memory footprint

**Justification:**
For a learning project, Django's observability (admin panel) and maturity outweigh FastAPI's raw speed.

---

### Why PostgreSQL over MySQL?

**Chose PostgreSQL because:**
- Better JSON support (for future extensions)
- More robust transaction handling
- Superior documentation
- Better for learning advanced SQL

**Trade-off:**
- Chapter uses MySQL in examples
- Slightly more complex setup

**Justification:**
PostgreSQL is industry standard for new projects. Skills transfer better to modern stacks.

---

### Why Not Implement Sharding?

**Decision:** Document sharding strategy but don't implement.

**Reasoning:**
- Local development can't simulate 500M DAU
- Sharding adds complexity that obscures core concepts
- Would need multiple Redis instances + shard mapping
- Better to understand principles than fake the scale

**Documentation:**
- Detailed fixed partition strategy in architecture doc
- Secondary cache design for user → shard mapping
- Trade-offs vs. hash partitioning

---

### Why Skip Swagger/OpenAPI?

**Decision:** Remove drf-yasg dependency.

**Reasoning:**
- Adds dependency and complexity
- Docstrings provide same information
- DRF browsable API is good enough for learning
- Can add later if needed

**Trade-off:**
- Manual API documentation
- No auto-generated client SDKs

---

## Blockers / Questions

### Resolved:

✅ **Q: Use Redis Cluster or single instance?**
- **A:** Single instance for 5M DAU, document cluster for 500M DAU
- Reason: Can't meaningfully test cluster locally, better to understand fundamentals

✅ **Q: Synchronous or asynchronous score updates?**
- **A:** Synchronous for MVP, document Kafka async pattern
- Reason: Simpler to reason about, user gets immediate feedback

✅ **Q: Store leaderboard in both Redis and PostgreSQL?**
- **A:** No, use [[event-sourcing]] pattern instead
- Reason: Game audit log is source of truth, can rebuild leaderboard

✅ **Q: How to handle monthly rotation?**
- **A:** New sorted set each month, archive to PostgreSQL, expire old keys after 7 days
- Reason: Balances historical queries with Redis memory constraints

---

## Next Steps

### For Learning:
- [ ] Practice explaining the design out loud (record yourself)
- [ ] Implement one extension (sharding, caching, tie-breaking)
- [ ] Run load tests with Locust or k6
- [ ] Deploy to AWS (EC2 + ElastiCache + RDS)
- [ ] Add Prometheus metrics and Grafana dashboards

### For Production:
- [ ] Add authentication (API keys + user tokens)
- [ ] Implement rate limiting (Redis rate limiter pattern)
- [ ] Add comprehensive tests (pytest with Redis/PostgreSQL fixtures)
- [ ] Set up CI/CD pipeline (GitHub Actions)
- [ ] Add logging with structured JSON (Python logging + ELK)
- [ ] Create Terraform/CloudFormation for infrastructure
- [ ] Document runbooks for common issues

---

## Retrospective

### What Went Well ✅

1. **Documentation-first approach**: Writing analysis and architecture docs before coding clarified requirements and prevented scope creep.

2. **Separation of concerns**: Clean 3-layer architecture (views → services → storage) made testing easy and code readable.

3. **Comprehensive docstrings**: Every class/method explains system design concepts, making code self-teaching.

4. **Interactive demo**: Demo script validates entire system and provides confidence in implementation.

5. **Production mindset**: Documented scaling, monitoring, disaster recovery even though not implemented.

### What Could Improve 🔄

1. **Tests**: Wrote minimal tests. Should have added pytest with Redis/PostgreSQL fixtures.

2. **Type hints**: Used some, but not consistently. Full typing would improve IDE autocomplete.

3. **Async code**: Used synchronous Django. Could have explored Django async views or FastAPI.

4. **Observability**: No metrics/tracing. Should add Prometheus exporters and OpenTelemetry.

5. **Load testing**: No performance benchmarks. Unknown how system behaves under real load.

### Key Learnings 💡

1. **Data structures matter more than code quality**: O(log n) vs O(n log n) is the difference between milliseconds and minutes.

2. **Documentation is a forcing function**: Writing docs exposed gaps in understanding and forced design decisions.

3. **Real-time is a spectrum**: "Real-time" doesn't mean "zero latency"—it means "acceptable staleness for the use case."

4. **Start simple, document complexity**: Single Redis instance works for millions of users. Don't over-engineer.

5. **System design is storytelling**: Practice explaining WHY you made decisions, not just WHAT you built.

---

## Time Tracking

| Phase | Duration | Key Deliverable |
|-------|----------|----------------|
| Requirements Analysis | 2 hours | `docs/00-analysis.md` |
| Architecture Design | 3 hours | `docs/01-architecture.md` with diagrams |
| Project Setup | 1 hour | Django + Docker + Makefile |
| Models Implementation | 1 hour | User, Game, LeaderboardSnapshot |
| Redis Storage Layer | 2 hours | RedisLeaderboardStore with 10+ methods |
| Service Logic | 2 hours | LeaderboardService with business logic |
| API Implementation | 2 hours | Serializers + Views + URLs |
| Admin Panel | 0.5 hours | Custom admin classes |
| Demo Script | 2 hours | Interactive demo with edge cases |
| Documentation | 3 hours | README + learnings + changelog |
| **Total** | **18.5 hours** | **Fully functional leaderboard system** |

---

**Status**: ✅ Complete

**Next Project**: Consider implementing News Feed or Chat System to learn about fan-out and real-time messaging patterns.
