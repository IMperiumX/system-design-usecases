# Real-time Gaming Leaderboard

A production-grade implementation of a real-time gaming leaderboard system, based on **System Design Interview Vol 2 - Chapter 10**.

## 🎯 What You'll Learn

This project demonstrates key system design concepts:

- **[[Redis Sorted Sets]]**: O(log n) leaderboard operations using skip lists
- **[[Polyglot Persistence]]**: Redis for real-time data, PostgreSQL for durability
- **[[API Design]]**: RESTful endpoints with proper separation of concerns
- **[[Sharding Strategies]]**: Fixed partition vs hash partition (documented)
- **[[Separation of Concerns]]**: Clean architecture with models, services, views
- **[[Scalability]]**: Handling 5M DAU → 500M DAU design decisions

## 📊 System Architecture

```
┌──────────┐
│  Client  │
└────┬─────┘
     │
     ▼
┌─────────────────┐
│  Django API     │  ← POST /scores (update)
│  (REST)         │  ← GET /scores (top 10)
│                 │  ← GET /scores/:id (rank)
└────┬───────┬────┘
     │       │
     ▼       ▼
┌─────────┐ ┌────────────┐
│  Redis  │ │ PostgreSQL │
│ Sorted  │ │  (Users &  │
│  Sets   │ │   Games)   │
└─────────┘ └────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (for Redis + Postgres)
- Git

### Installation

```bash
# Clone the repository
cd projects/realtime-gaming-leaderboard

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start services (Redis + PostgreSQL)
docker-compose up -d

# Wait for services to be ready (check with)
docker-compose ps

# Run migrations
python manage.py migrate

# Create admin user (optional)
python manage.py createsuperuser

# Run the interactive demo
python scripts/demo.py
```

### Alternative: Using Makefile

```bash
make setup   # Install everything and run migrations
make demo    # Run interactive demo
make shell   # Open Django shell
make test    # Run tests
```

## 📖 Documentation

Detailed documentation is in the `docs/` folder:

- **[00-analysis.md](docs/00-analysis.md)** - Requirements, scope, and technology decisions
- **[01-architecture.md](docs/01-architecture.md)** - System diagrams, component breakdown, and API specs
- **[02-learnings.md](docs/02-learnings.md)** - Key takeaways and interview preparation
- **[03-changelog.md](docs/03-changelog.md)** - Implementation timeline and decisions

## 🎮 Demo Script

The demo script (`scripts/demo.py`) demonstrates:

1. ✅ Creating 50 test users
2. ✅ Simulating 500-5000 game wins
3. ✅ Fetching top 10 leaderboard
4. ✅ Getting individual user ranks
5. ✅ Showing players ±4 positions around a user
6. ✅ Displaying leaderboard statistics
7. ✅ Edge case handling

**Expected output:**

```
╔═══════════════════════════════════════════════════════════════════╗
║        Real-time Gaming Leaderboard System Demo                  ║
╚═══════════════════════════════════════════════════════════════════╝

============================================================
Step 1: Creating Test Users
============================================================

✓ Created user: Dragon Master (@DragonMaster247)
✓ Created user: Shadow Knight (@ShadowKnight891)
...

============================================================
Step 3: Top 10 Leaderboard
============================================================

Rank   Player                    Score
---------------------------------------------
#1     Phoenix Legend            97
#2     Storm Wizard              89
#3     Thunder Champion          84
...
```

## 🔌 API Endpoints

### POST /api/v1/scores
Update user score after winning a match.

```bash
curl -X POST http://localhost:8000/api/v1/scores \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "points": 1
  }'
```

**Response:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "new_score": 47,
  "rank": 1523,
  "month": "2025-01"
}
```

### GET /api/v1/scores?limit=10
Fetch top N players.

```bash
curl http://localhost:8000/api/v1/scores?limit=10
```

**Response:**
```json
{
  "data": [
    {
      "rank": 1,
      "user_id": "...",
      "username": "alice_94",
      "display_name": "Alice",
      "score": 987
    },
    ...
  ],
  "total": 10,
  "month": "2025-01"
}
```

### GET /api/v1/scores/{user_id}
Get user's rank and score.

```bash
curl http://localhost:8000/api/v1/scores/550e8400-e29b-41d4-a716-446655440000
```

### GET /api/v1/scores/{user_id}/surrounding?offset=4
Get players ±4 positions around a user.

```bash
curl http://localhost:8000/api/v1/scores/550e8400-e29b-41d4-a716-446655440000/surrounding?offset=4
```

### GET /api/v1/stats
Get leaderboard statistics (admin).

```bash
curl http://localhost:8000/api/v1/stats
```

## 🗄️ Data Models

### User
```python
id: UUID                  # Primary key
username: str             # Unique username
display_name: str         # Display name on leaderboard
avatar_url: str           # CDN URL for avatar
created_at: datetime      # Account creation
```

### Game (Audit Log)
```python
id: BigInt                # Auto-incrementing ID
user: ForeignKey(User)    # Player who won
score_earned: int         # Points from this match (usually 1)
match_id: UUID            # Reference to game service
played_at: datetime       # Match timestamp
leaderboard_month: str    # "YYYY-MM" format
```

### LeaderboardSnapshot (Historical Data)
```python
user: ForeignKey(User)    # Player
month: str                # "YYYY-MM" format
final_score: int          # Total score at month end
final_rank: int           # Rank at month end
created_at: datetime      # Snapshot timestamp
```

## ⚡ Performance Characteristics

| Operation | Time Complexity | Notes |
|-----------|----------------|-------|
| Update score | O(log n) | Redis ZINCRBY |
| Get top 10 | O(log n + 10) | Redis ZREVRANGE |
| Get user rank | O(log n) | Redis ZREVRANK |
| Get user score | O(1) | Redis ZSCORE |

**At scale (5M DAU):**
- Storage: ~650 MB in Redis
- QPS: ~2,500 score updates/sec (peak)
- Single Redis instance is sufficient

**At scale (500M DAU):**
- Storage: ~65 GB (requires sharding)
- QPS: ~250,000 updates/sec
- Solution: Fixed partition sharding by score ranges

## 🧪 Testing

```bash
# Run all tests
make test

# Or with pytest directly
pytest tests/

# Run specific test
pytest tests/test_leaderboard_service.py -v
```

## 📊 Monitoring

**Key metrics to track:**

- Redis memory usage (should be ~650 MB for 25M MAU)
- Redis QPS (watch for approaching 100K)
- API latency (p50, p95, p99)
- Leaderboard size growth

**Health check:**

```bash
# Check Redis
docker-compose exec redis redis-cli ping

# Check PostgreSQL
docker-compose exec postgres pg_isready

# Check Django
curl http://localhost:8000/api/v1/stats
```

## 🔧 Debugging

### Django Admin Panel

Access at: http://localhost:8000/admin

- View/create users
- Browse game history
- Check leaderboard snapshots

### Redis CLI

```bash
# Connect to Redis
docker-compose exec redis redis-cli

# View leaderboard (top 10)
ZREVRANGE leaderboard_2025_01 0 9 WITHSCORES

# Get user's rank
ZREVRANK leaderboard_2025_01 "550e8400-e29b-41d4-a716-446655440000"

# Get user's score
ZSCORE leaderboard_2025_01 "550e8400-e29b-41d4-a716-446655440000"

# Count total users
ZCARD leaderboard_2025_01
```

### Database Queries

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U leaderboard_user -d leaderboard_db

# Count users
SELECT COUNT(*) FROM users;

# View top 10 by game count
SELECT u.username, COUNT(*) as games
FROM users u
JOIN games g ON g.user_id = u.id
WHERE g.leaderboard_month = '2025-01'
GROUP BY u.id
ORDER BY games DESC
LIMIT 10;
```

## 🎓 Interview Preparation

This project prepares you to answer questions like:

### Clarifying Questions
- How many daily/monthly active users?
- What's the acceptable latency for leaderboard updates?
- Do we need historical leaderboards (monthly/seasonal)?
- How do we handle ties in scoring?
- Is real-time accuracy required or is eventual consistency okay?

### Technical Deep Dives
- **Why Redis over MySQL?**
  - MySQL: O(n log n) sorting on every query, not real-time
  - Redis: O(log n) with sorted sets, maintains order on insert

- **How would you shard this?**
  - Fixed partition by score ranges (recommended)
  - Hash partition by user_id (harder to query top 10)

- **How would you handle 100x traffic spike?**
  - Add read replicas for Redis
  - Cache top 10 in CDN (60 sec TTL)
  - Rate limit per user

- **What if Redis crashes?**
  - Rebuild from PostgreSQL Game audit log
  - Or promote read replica (faster)

## 🚦 Scaling to 500M DAU

Changes needed:

1. **Shard Redis** by score ranges (10 shards × 6.5 GB each)
2. **Add secondary cache** for user → shard mapping
3. **Use Kafka** to decouple game events from leaderboard updates
4. **Partition PostgreSQL** by month (time-series data)
5. **Add read replicas** for PostgreSQL
6. **CDN caching** for top 10 (1 minute TTL)

See [docs/01-architecture.md](docs/01-architecture.md#scaling-strategy-500m-dau) for details.

## 📂 Project Structure

```
.
├── core/                      # Main Django app
│   ├── models.py              # User, Game, LeaderboardSnapshot
│   ├── serializers.py         # DRF serializers
│   ├── views.py               # API views
│   ├── services/              # Business logic
│   │   └── leaderboard_service.py
│   └── storage/               # Data access
│       └── redis_store.py     # Redis sorted set operations
├── leaderboard_project/       # Django project
│   ├── settings.py            # Configuration
│   └── urls.py                # URL routing
├── scripts/
│   └── demo.py                # Interactive demo
├── tests/                     # Unit tests
├── docs/                      # System design documentation
├── docker-compose.yml         # Redis + PostgreSQL
├── requirements.txt           # Python dependencies
├── Makefile                   # Common commands
└── README.md                  # This file
```

## 🤝 Contributing

This is a learning project, but suggestions are welcome!

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📝 License

MIT License - feel free to use for learning and interviews.

## 🙏 Acknowledgments

- **System Design Interview Vol 2** by Alex Xu
- **Redis Documentation** for sorted set internals
- **Django** and **Django REST Framework** communities

## 📬 Questions?

Open an issue or check the documentation in `docs/`.

---

**Happy learning! 🚀**
