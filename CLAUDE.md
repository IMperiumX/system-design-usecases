# System Design Implementations

This repository contains hands-on implementations of system design patterns for learning and interview preparation.

## Project Structure

```
.
├── .claude/commands/     # Claude Code commands
│   ├── implement.md      # /implement [system-name] - build new system
│   ├── review.md         # /review [project] - review & extend
│   └── interview-prep.md # /interview-prep [topic] - practice
├── projects/             # Individual implementations
│   └── [system-name]/    # Each system in its own folder
├── shared/               # Reusable utilities across projects
└── CLAUDE.md            # This file
```

## Commands

| Command | Usage | Purpose |
|---------|-------|---------|
| `/implement` | `/implement url-shortener` | Analyze chapter & build implementation |
| `/review` | `/review url-shortener` | Review existing project, suggest extensions |
| `/interview-prep` | `/interview-prep url-shortener` | Generate interview practice materials |

## Implementation Guidelines

When building new systems:

### Code Style
- Python 3.11+ with full type hints
- Pydantic for data validation
- FastAPI for APIs
- Async where it makes sense
- Comprehensive docstrings linking code to concepts

### Priorities
1. **Clarity over cleverness** - This is for learning
2. **Observable behavior** - Log everything important
3. **Documented trade-offs** - Explain why, not just what
4. **Working demos** - Every project should be runnable

### External Services
- Prefer Docker Compose for Redis, Postgres, etc.
- Fall back to in-memory/SQLite for simpler setups
- Always document which approach and why

## Shared Utilities

If you create something reusable, consider adding to `./shared/`:
- Common logging setup
- Base service classes
- Testing utilities
- Docker compose fragments

## Conventions

### Naming
- Project folders: `kebab-case` (e.g., `url-shortener`)
- Python files: `snake_case` (e.g., `url_service.py`)
- Classes: `PascalCase` (e.g., `URLShortener`)

### Commits
When implementing, commit after each phase:
- `feat(url-shortener): add data models`
- `feat(url-shortener): implement storage layer`
- `feat(url-shortener): add API endpoints`
- `docs(url-shortener): complete README`

### Documentation
Every project README must include:
- What system design concepts it teaches
- Architecture diagram
- How to run
- Interview questions it prepares for

## Learning Path Suggestion

Recommended implementation order (building complexity):

1. **URL Shortener** - Hashing, storage, caching basics
2. **Pastebin** - Similar to #1, adds expiration
3. **Rate Limiter** - Algorithms, distributed state
4. **Key-Value Store** - Storage engines, consistency
5. **Message Queue** - Pub/sub, delivery guarantees
6. **Cache System** - Eviction policies, invalidation
7. **Search Autocomplete** - Tries, ranking
8. **News Feed** - Fan-out, ranking, pagination
9. **Chat System** - Real-time, presence, delivery
10. **Distributed ID Generator** - Coordination, uniqueness
