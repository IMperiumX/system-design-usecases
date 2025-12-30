# System Design Implementations 🏗️

Hands-on implementations of system design patterns. Built for learning, optimized for interview prep.

## Why This Exists

Reading about system design is not enough. This repo turns theory into working code:

- **Implement** → Build scaled-down versions of real systems
- **Observe** → See how components interact through logs and demos
- **Understand** → Every line of code links back to concepts
- **Prepare** → Direct mapping to interview questions

## Quick Start

```bash
# Clone and navigate
cd system-design-implementations

# Pick a project
cd projects/url-shortener

# Run it
make install
make run

# See it in action
make demo
```

## Projects

| System | Key Concepts | Status |
|--------|--------------|--------|
| URL Shortener | Hashing, KV store, caching | 🔲 |
| Rate Limiter | Token bucket, sliding window | 🔲 |
| Key-Value Store | LSM trees, compaction | 🔲 |
| Message Queue | Pub/sub, delivery guarantees | 🔲 |
| ... | | |

## Using with Claude Code

This repo includes custom commands:

```bash
# Analyze a chapter and build implementation
/implement url-shortener

# Review and extend existing project
/review url-shortener

# Generate interview prep materials
/interview-prep url-shortener
```

## Structure

```
.
├── projects/          # Each system design in its own folder
│   └── [system]/
│       ├── README.md  # Architecture + learnings
│       ├── src/       # Implementation
│       ├── tests/     # Tests + demos
│       └── Makefile   # Convenient commands
├── shared/            # Reusable utilities
└── CLAUDE.md          # Project context for AI assistance
```

## Philosophy

1. **Learning > Production** - Optimize for understanding
2. **Observable > Efficient** - Log everything, make behavior visible
3. **Documented > Clever** - Explain trade-offs, link to concepts
4. **Working > Complete** - A running demo beats perfect code

## Resources

- [System Design Primer](https://github.com/donnemartin/system-design-primer)
- [Designing Data-Intensive Applications](https://dataintensive.net/)
- [ByteByteGo](https://bytebytego.com/)

---

*Built for learning. Every system tells a story.*
