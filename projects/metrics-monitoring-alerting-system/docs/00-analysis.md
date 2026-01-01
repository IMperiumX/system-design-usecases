---
tags:
  - system-design
  - metrics-monitoring
  - alerting-system
  - analysis
created: 2026-01-01
status: in-progress
source: "System Design Interview Vol 2 - Chapter 5"
---

# Metrics Monitoring and Alerting System — Analysis

## Overview
A scalable metrics monitoring and alerting system that provides clear visibility into infrastructure health, ensuring high availability and reliability. The system collects operational metrics (CPU load, memory usage, request counts) from distributed servers, stores time-series data efficiently, enables visualization through dashboards, and sends alerts when metrics violate predefined thresholds.

## Core Components

| Component | Purpose | Simulates |
|-----------|---------|-----------|
| Metrics Collector | Pulls/receives metrics from sources | Prometheus scraper, CloudWatch agent |
| Message Queue | Buffers metrics data for reliability | Apache Kafka partitions |
| Time-Series Database | Optimized storage for metrics | InfluxDB, Prometheus TSDB |
| Query Service | Retrieves and aggregates metrics | PromQL query engine |
| Alert Manager | Evaluates rules and triggers alerts | Prometheus Alertmanager |
| Notification Service | Sends alerts to channels | PagerDuty, email gateways |
| Visualization System | Renders dashboards and graphs | Grafana panels |

## Concepts Demonstrated

> [!tip] Key Learning Areas
> - [[time-series-database]]: Specialized storage optimized for temporal data with labels
> - [[pull-vs-push-architecture]]: Trade-offs between pull-based (Prometheus) and push-based (CloudWatch) metrics collection
> - [[data-aggregation]]: Downsampling and rollup strategies to reduce storage while maintaining insights
> - [[message-queues]]: Using Kafka to decouple collection from processing and prevent data loss
> - [[service-discovery]]: Dynamic endpoint registration via etcd/ZooKeeper for pull-based systems
> - [[consistent-hashing]]: Distributing metrics collection load across collector instances
> - [[caching-strategy]]: Query result caching to reduce database load
> - [[write-heavy-workloads]]: Optimizations for systems with constant high write throughput
> - [[data-retention-policies]]: Tiered storage with different resolutions (raw → 1-min → 1-hour)
> - [[alerting-patterns]]: Deduplication, merging, retry logic, state management

## Scope Decision

### ✅ Building (MVP)

**Data Collection (Push Model)**
- Collection agent that pushes metrics to collectors
- Metrics collector cluster with load balancer
- Support for metric names, labels/tags, timestamps, values

**Storage Layer**
- Time-series data models with metric name, labels, value, timestamp
- Django ORM models for metrics and alert configurations
- Redis for caching query results
- Data retention simulation (won't implement actual downsampling)

**Query Service**
- API to retrieve metrics by name, labels, time range
- Basic aggregation functions (avg, sum, count, max, min)
- Cache integration

**Alert System**
- YAML-based alert rule definitions
- Alert manager that evaluates rules periodically
- Alert states: inactive, pending, firing, resolved
- Alert deduplication and merging
- Multi-channel notifications (email, webhook simulation)

**Visualization**
- REST API endpoints for dashboard data
- Sample dashboard configuration
- Time-range queries for graphs

### 🔄 Simulating

**Message Queue**
- Simplified Kafka simulation using Django models + background tasks
- Won't implement actual partitioning, just demonstrate the buffering concept

**Time-Series Database**
- Using Django ORM with PostgreSQL instead of InfluxDB/Prometheus
- Demonstrating the schema and query patterns, not the performance optimizations

**Service Discovery**
- Hardcoded endpoints instead of etcd/ZooKeeper integration
- Focus on the concept, not the distributed coordination

**Downsampling**
- Data retention policy defined but not actively running aggregation jobs
- Demonstrate the rollup logic without cron/scheduler

**Notification Channels**
- Mock email/webhook sending with logging
- Won't integrate actual SMTP or PagerDuty API

### ⏭️ Skipping

**Production Optimizations**
- Actual data compression and encoding (delta-of-delta)
- Distributed tracing integration
- Log monitoring (ELK stack)
- Advanced PromQL/Flux query language parsing
- Horizontal scaling of time-series DB
- Cold storage migration
- Authentication and access control
- Custom visualization UI (just API endpoints)

## Technology Choices

| Tool | Why |
|------|-----|
| Django | ORM for time-series models, admin panel for debugging metrics/alerts |
| Django REST Framework | Clean serializers for metrics ingestion and query APIs |
| PostgreSQL | Relational DB simulating time-series storage (with indexes on timestamp) |
| Redis | Real caching layer for query results vs in-memory dict |
| Docker Compose | PostgreSQL + Redis containerized for easy setup |
| Celery (optional) | Background tasks for alert evaluation (or simple threading) |
| YAML | Industry-standard format for alert rule definitions |

## Trade-offs from Chapter

> [!question] Key Trade-off: Pull vs Push Model
> **Options**: Pull (Prometheus-style) vs Push (CloudWatch-style)
> **Choice**: Push model for this implementation
> **Reasoning**:
> - **Pull pros**: Easy debugging (/metrics endpoint), implicit health checks, authentic data sources
> - **Push pros**: Works with firewalls/NAT, better for short-lived jobs, lower latency with UDP
> - **Implementation decision**: Push is simpler to demo without service discovery setup
> - **Learning outcome**: Both patterns documented, focusing on push's load balancer + auto-scaling

> [!question] Key Trade-off: Query-time vs Write-time Aggregation
> **Options**: Aggregate on write (stream processing) vs aggregate on read (query time)
> **Choice**: Query-time aggregation (simpler implementation)
> **Reasoning**:
> - **Write-time pros**: Reduced storage, faster queries, lower database load
> - **Write-time cons**: Data loss (no raw data), late-arriving events complexity
> - **Query-time pros**: Full data precision, flexibility for new aggregations
> - **Query-time cons**: Slower queries, higher database load
> - **Implementation decision**: Keep raw data, aggregate in API for learning clarity

> [!question] Key Trade-off: Build vs Buy (Alerting/Visualization)
> **Options**: Custom system vs Grafana + Prometheus Alertmanager
> **Choice**: Build simplified versions to understand internals
> **Reasoning**:
> - **Real-world**: Chapter recommends Grafana + existing alert systems (proven, maintained)
> - **Learning goal**: Understand alert state management, deduplication, notification retry
> - **Implementation**: Simple Django-based system showing core concepts, not production-ready

## Data Model Design

### Metric Data Point
```python
{
    "metric_name": "cpu.load",
    "labels": {"host": "webserver01", "region": "us-west", "env": "prod"},
    "timestamp": 1613707265,  # Unix timestamp
    "value": 0.75
}
```

### Alert Rule (YAML)
```yaml
- name: high_cpu_usage
  rules:
    - alert: cpu_over_threshold
      expr: "cpu.load > 0.8"  # Simplified, not full PromQL
      for: 5m  # Duration threshold
      labels:
        severity: critical
      annotations:
        summary: "High CPU on {{ host }}"
```

### Alert State Machine
```
inactive → pending (condition true) → firing (duration met) → resolved
                ↓ (condition false)
              inactive
```

## Open Questions

- [x] Should we implement actual Kafka or simulate with Django models? → **Simulate for simplicity**
- [x] Use Celery for background alert evaluation or simple threading? → **Start with simple scheduler, document Celery option**
- [x] How to demonstrate data retention rollup without running for days? → **API endpoint to manually trigger rollup on sample data**
- [ ] Include Grafana integration or just API endpoints? → **Just APIs, document Grafana connection points**

## System Scale (from Requirements)

| Metric | Value |
|--------|-------|
| Daily Active Users | 100 million |
| Server Pools | 1,000 |
| Machines per Pool | 100 |
| Metrics per Machine | 100 |
| **Total Metrics** | **~10 million metrics** |
| Data Retention | 1 year |
| Retention Policy | 7 days raw → 30 days 1-min → 1 year 1-hour |
| Query Pattern | 85% of queries for last 26 hours (hot data) |

## Implementation Phases

1. **Foundation**: Django project, PostgreSQL + Redis setup, base models
2. **Metrics Ingestion**: Push API, collector service, Kafka simulation
3. **Storage**: Time-series schema, label indexing, retention policies
4. **Query Service**: Aggregation API, cache integration, time-range filters
5. **Alerting**: Rule engine, state management, notification dispatcher
6. **Visualization**: Dashboard API, sample graphs, demo script

---

**Status**: Analysis complete. Ready to proceed with architecture design and implementation.
