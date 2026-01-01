# Metrics Monitoring & Alerting System

> **Educational implementation** of a production-grade metrics monitoring and alerting system based on Chapter 5 of "System Design Interview Volume 2" by Alex Xu.

**Purpose**: Learn distributed systems concepts through hands-on implementation using Django, PostgreSQL, and Redis.

---

## What You'll Learn

This project demonstrates core **observability** and **distributed systems** concepts:

### System Design Patterns
- ✅ **Push-based metrics collection** - Agents actively send data to collectors
- ✅ **Message queue buffering** - Kafka-style partitioning for decoupling and fault tolerance
- ✅ **Time-series database** - Optimized storage for temporal data with labels/tags
- ✅ **Alert state machine** - Lifecycle management (inactive → pending → firing → resolved)
- ✅ **Adaptive caching** - TTL based on data age (hot/warm/cold)
- ✅ **Horizontal scaling** - Stateless collectors, partitioned queues, read replicas

### Technologies & Concepts
- **Django ORM** simulating time-series database with JSONB labels
- **PostgreSQL** with composite indexes for time-range queries
- **Redis** for query result caching
- **REST API** design for metrics ingestion and querying
- **State machines** for alert lifecycle management
- **Fingerprinting** for deduplication
- **Retention policies** with tiered aggregation

### Interview Preparation
- Calculate **storage requirements** for metrics at scale
- Compare **push vs pull** architectures (Datadog vs Prometheus)
- Design **alert systems** that prevent flapping
- Optimize **time-series queries** with caching and indexing
- Scale from 100 to 100M+ daily active users

---

## Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Make (optional, for convenience commands)

### Setup

1. **Clone and navigate**:
```bash
cd projects/metrics-monitoring-alerting-system
```

2. **Start infrastructure** (PostgreSQL + Redis):
```bash
make setup
# Or manually:
docker-compose up -d
```

3. **Install dependencies**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

4. **Apply migrations**:
```bash
make migrate
# Or: python manage.py migrate
```

5. **Run the interactive demo**:
```bash
make demo
# Or: python scripts/demo.py
```

You should see output demonstrating:
- Metrics collection from 5 simulated web servers
- Queue processing (Kafka simulation)
- Time-series queries with aggregations
- Alert rule creation and evaluation
- System statistics

### Start the Server

```bash
make server
# Or: python manage.py runserver
```

Access:
- **API**: http://localhost:8000/api/v1/
- **Admin**: http://localhost:8000/admin (create superuser first)
- **Health Check**: http://localhost:8000/api/v1/health

---

## Architecture Overview

```
┌─────────────┐
│ Collection  │  Push metrics via HTTP POST
│   Agents    │  (running on monitored hosts)
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│          Metrics Collector (Django)             │
│  - Validate & normalize incoming metrics        │
│  - Enqueue to message queue (Kafka simulation)  │
│  - Return 202 Accepted (fire-and-forget)        │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│       Message Queue (Kafka Simulation)          │
│  - 10 partitions for horizontal scaling         │
│  - Offset-based consumption tracking            │
│  - At-least-once delivery semantics             │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│      Consumer Pool (Background Workers)         │
│  - Fetch batches from queue                     │
│  - Write to time-series storage                 │
│  - Commit offsets on success                    │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│    Time-Series Storage (PostgreSQL + JSONB)     │
│  - Composite indexes: (name, timestamp)         │
│  - JSONB labels for flexible filtering          │
│  - Retention: Raw → 1-min → 1-hour aggregates   │
└──────┬──────────────────────────────────────────┘
       │
       ├──────────────────┐
       ▼                  ▼
┌─────────────┐    ┌─────────────┐
│ Query       │    │ Alert       │
│ Service     │    │ Manager     │
│             │    │             │
│ - Redis     │    │ - Evaluate  │
│   caching   │    │   rules     │
│ - Adaptive  │    │ - State     │
│   TTL       │    │   machine   │
│ - Aggreg.   │    │ - Notify    │
└─────────────┘    └─────────────┘
```

### Data Flow

1. **Ingestion** (Push Model):
   - Agents send metrics to `/api/v1/metrics` (POST)
   - Collector validates, normalizes, and enqueues to Kafka
   - Returns 202 Accepted immediately

2. **Processing** (Consumer):
   - Background consumers fetch from queue partitions
   - Write to PostgreSQL time-series storage
   - Commit offsets for resumption

3. **Querying**:
   - `/api/v1/query?metric_name=cpu.load&aggregation=avg`
   - Cache check (Redis) → Database query → Cache store
   - Adaptive TTL based on data age

4. **Alerting**:
   - Periodic rule evaluation (cron job or scheduler)
   - State transitions: inactive → pending → firing → resolved
   - Multi-channel notifications (email, webhook, PagerDuty)

---

## Project Structure

```
.
├── docs/                           # Documentation
│   ├── 00-analysis.md             # Requirements & scope analysis
│   ├── 01-architecture.md         # System design & diagrams
│   ├── 02-learnings.md            # Interview prep & insights
│   └── 03-changelog.md            # Implementation log
│
├── metrics/                        # Django app
│   ├── models.py                  # Data models (Metric, AlertRule, etc.)
│   ├── serializers.py             # DRF serializers
│   ├── views.py                   # API endpoints
│   ├── urls.py                    # URL routing
│   ├── admin.py                   # Django admin configuration
│   │
│   ├── services/                  # Business logic layer
│   │   ├── metrics_collector.py  # Push-based ingestion
│   │   ├── metrics_consumer.py   # Queue consumer
│   │   ├── query_service.py      # Query interface
│   │   ├── alert_manager.py      # Alert evaluation
│   │   └── notification_service.py  # Multi-channel notifications
│   │
│   └── storage/                   # Storage abstraction layer
│       ├── cache.py               # Redis caching
│       ├── queue.py               # Kafka simulation
│       └── timeseries.py          # Time-series storage API
│
├── scripts/
│   └── demo.py                    # Interactive demo script
│
├── metrics_system/                # Django project config
│   ├── settings.py                # Django settings
│   └── urls.py                    # Root URL config
│
├── docker-compose.yml             # PostgreSQL + Redis
├── requirements.txt               # Python dependencies
├── Makefile                       # Convenience commands
└── README.md                      # This file
```

---

## API Documentation

### Health Check

**GET** `/api/v1/health`

Response:
```json
{
  "status": "healthy",
  "timestamp": "2025-01-01T12:00:00Z",
  "database": "ok",
  "cache": "ok"
}
```

### Metrics Ingestion

**POST** `/api/v1/metrics`

Push single or batch metrics. Returns `202 Accepted` (fire-and-forget).

**Single metric**:
```json
{
  "name": "cpu.load",
  "value": 0.75,
  "labels": {"host": "web-01", "region": "us-west"},
  "timestamp": "2025-01-01T12:00:00Z"  // optional, defaults to now
}
```

**Batch**:
```json
{
  "metrics": [
    {"name": "cpu.load", "value": 0.75, "labels": {"host": "web-01"}},
    {"name": "memory.used_percent", "value": 65.2, "labels": {"host": "web-01"}}
  ]
}
```

Response:
```json
{
  "status": "accepted",
  "accepted": 2,
  "rejected": 0,
  "errors": []
}
```

### Query Metrics

**GET** `/api/v1/query`

Query time-series data with aggregations.

**Parameters**:
- `metric_name` (required): Metric to query (e.g., `cpu.load`)
- `start_time` (optional): ISO timestamp, default: 1 hour ago
- `end_time` (optional): ISO timestamp, default: now
- `labels` (optional): JSON filter (e.g., `{"host": "web-01"}`)
- `aggregation` (optional): `avg`, `max`, `min`, `sum`, `count`
- `group_by` (optional): Comma-separated label keys (e.g., `host,region`)

**Example**:
```bash
curl "http://localhost:8000/api/v1/query?metric_name=cpu.load&aggregation=avg&group_by=host"
```

Response:
```json
{
  "metric_name": "cpu.load",
  "results": [
    {
      "labels": {"host": "web-01"},
      "value": 0.72,
      "count": 150,
      "timestamp": null
    },
    {
      "labels": {"host": "web-02"},
      "value": 0.68,
      "count": 148,
      "timestamp": null
    }
  ]
}
```

### Metrics Metadata

**List all metric names**:
```bash
GET /api/v1/metrics/names
```

**Get label keys for a metric**:
```bash
GET /api/v1/metrics/cpu.load/labels
```

**Get values for a label key**:
```bash
GET /api/v1/metrics/cpu.load/labels/host/values
```

### Alert Rules

**List alert rules**:
```bash
GET /api/v1/alerts/rules
```

**Create alert rule**:
```bash
POST /api/v1/alerts/rules
Content-Type: application/json

{
  "name": "high_cpu_usage",
  "metric_name": "cpu.load",
  "condition": ">",
  "threshold": 0.8,
  "duration_seconds": 300,
  "severity": "warning",
  "notification_channels": ["webhook"],
  "webhook_url": "https://hooks.example.com/alerts",
  "annotations": {
    "summary": "High CPU on {{ host }}",
    "description": "CPU is {{ value }}, threshold {{ threshold }}"
  },
  "enabled": true
}
```

**Test alert condition**:
```bash
POST /api/v1/alerts/rules/test

{
  "metric_name": "cpu.load",
  "condition": ">",
  "threshold": 0.8,
  "current_value": 0.85
}
```

### Alert Instances

**List all alert instances**:
```bash
GET /api/v1/alerts/instances
```

**Filter by state**:
```bash
GET /api/v1/alerts/instances?state=firing
```

**Get active alerts only**:
```bash
GET /api/v1/alerts/instances/active
```

### System Operations

**Process metrics queue** (run consumer):
```bash
POST /api/v1/ops/process-queue
```

**Evaluate all alert rules**:
```bash
POST /api/v1/ops/evaluate-alerts
```

### Statistics

**Queue statistics**:
```bash
GET /api/v1/stats/queue
```

Response:
```json
{
  "total_events": 5000,
  "unconsumed_events": 50,
  "partitions": 10,
  "events_by_partition": {
    "0": 500,
    "1": 485,
    ...
  }
}
```

**System statistics**:
```bash
GET /api/v1/stats/system
```

Response:
```json
{
  "total_metrics": 150000,
  "total_alerts": 5,
  "active_alerts": 2,
  "metric_names_count": 12,
  "time_range_start": "2025-01-01T00:00:00Z",
  "time_range_end": "2025-01-01T12:00:00Z"
}
```

---

## Running the Demo

The interactive demo script (`scripts/demo.py`) demonstrates the complete system workflow:

```bash
make demo
# Or: python scripts/demo.py
```

**What it does**:

1. **Metrics Collection**: Simulates 5 web server agents collecting CPU, memory, disk, and network metrics
2. **Queue Processing**: Consumes metrics from queue and writes to storage
3. **Querying**: Demonstrates time-range queries, aggregations, and group-by
4. **Alerting**: Creates alert rules, evaluates conditions, shows state transitions
5. **Statistics**: Displays system-wide metrics and breakdowns

**Output**:
```
================================================================================
  METRICS MONITORING AND ALERTING SYSTEM - Interactive Demo
  Demonstrating System Design Concepts from Chapter 5
================================================================================

================================================================================
  DEMO 1: Metrics Collection (Push Model)
================================================================================

[Step 1] Initializing Collection Agents
--------------------------------------------------------------------------------
✓ Created 5 collection agents

[Step 2] Collecting System Metrics
--------------------------------------------------------------------------------
  Agent web-01: Collected 4 metrics
  Agent web-02: Collected 4 metrics
  Agent web-03: Collected 4 metrics
  Agent web-04: Collected 4 metrics
  Agent web-05: Collected 4 metrics

✓ Total metrics queued: 20

Queue Statistics:
  - Total events in queue: 20
  - Unconsumed events: 20
  - Partitions: 10

...
```

---

## Django Admin Interface

Create a superuser to access the admin panel:

```bash
python manage.py createsuperuser
```

Then visit http://localhost:8000/admin

**Features**:
- Browse and filter metrics, events, alerts
- Bulk actions (mark events consumed, enable/disable rules, resolve alerts)
- Manual alert resolution
- Queue inspection and management

---

## Data Models

### Metric
Stores individual time-series data points.

```python
class Metric(models.Model):
    name = CharField()           # Metric name (e.g., "cpu.load")
    labels = JSONField()         # Tags (e.g., {"host": "web-01"})
    timestamp = DateTimeField()  # When the metric was recorded
    value = FloatField()         # Metric value
    series_id = CharField()      # Fingerprint: MD5(name + sorted labels)
```

**Indexes**: Composite on `(name, timestamp)` for efficient range queries.

### MetricEvent
Kafka-style message queue simulation.

```python
class MetricEvent(models.Model):
    partition = IntegerField()   # Partition number (0-9)
    offset = BigIntegerField()   # Sequential offset within partition
    metric_name = CharField()    # For routing
    payload = JSONField()        # Metric data
    consumed = BooleanField()    # Consumption tracking
```

**Unique constraint**: `(partition, offset)` for ordering guarantees.

### AlertRule
Defines threshold-based alert conditions.

```python
class AlertRule(models.Model):
    name = CharField()                    # Unique rule name
    metric_name = CharField()             # Which metric to monitor
    condition = CharField()               # >, <, >=, <=, ==, !=
    threshold = FloatField()              # Threshold value
    duration_seconds = IntegerField()     # How long condition must persist
    severity = CharField()                # info, warning, critical
    notification_channels = JSONField()   # ["email", "webhook", "pagerduty"]
    enabled = BooleanField()              # Rule on/off switch
```

### AlertInstance
Tracks alert state for specific conditions.

```python
class AlertInstance(models.Model):
    rule = ForeignKey(AlertRule)
    state = CharField()          # inactive, pending, firing, resolved
    fingerprint = CharField()    # MD5(rule_id + sorted labels)
    current_value = FloatField() # Latest metric value
    labels = JSONField()         # Alert labels

    # State timestamps
    pending_since = DateTimeField()
    firing_since = DateTimeField()
    resolved_at = DateTimeField()

    # Notification tracking
    notifications_sent = IntegerField()
    last_notification_at = DateTimeField()
```

**State machine**:
```
inactive → pending → firing → resolved
           ↑         ↓
           └─ (check duration)
```

### AggregatedMetric
Downsampled metrics for retention policies.

```python
class AggregatedMetric(models.Model):
    name = CharField()
    resolution = CharField()  # "1m" (1 minute), "1h" (1 hour)
    timestamp = DateTimeField()
    labels = JSONField()

    # Pre-computed aggregations
    avg_value = FloatField()
    max_value = FloatField()
    min_value = FloatField()
    sum_value = FloatField()
    count = IntegerField()
```

---

## Storage Abstraction Layer

### MetricsQueue (`metrics/storage/queue.py`)
Simulates Kafka with partitions and offsets.

**Key methods**:
- `produce(metric_data)`: Enqueue metric to partition
- `consume(partition, last_offset, batch_size)`: Fetch batch
- `commit(partition, offset)`: Mark offset as processed
- `get_partition(metric_name)`: Consistent hashing

### MetricsCache (`metrics/storage/cache.py`)
Redis-backed query result caching.

**Key methods**:
- `cache_query_result(query_params, result, data_age)`: Store with adaptive TTL
- `get_cached_result(query_params)`: Retrieve cached query
- `invalidate_metric(metric_name)`: Clear cache on new data

**Adaptive TTL**:
- Data < 1 hour old: 60s TTL (hot)
- Data 1-24 hours old: 300s TTL (warm)
- Data > 24 hours old: 3600s TTL (cold)

### TimeSeriesStorage (`metrics/storage/timeseries.py`)
API for writing and querying metrics.

**Key methods**:
- `write(metric_data)`: Insert single metric
- `write_batch(metrics)`: Bulk insert
- `query(metric_name, start_time, end_time, labels, aggregation, group_by)`: Time-range query
- `get_latest_value(metric_name, labels)`: Most recent data point

---

## Service Layer

### MetricsCollector (`metrics/services/metrics_collector.py`)
Handles metric ingestion.

**Responsibilities**:
- Validate incoming metrics (schema, types)
- Normalize timestamps, labels
- Enqueue to message queue
- Return ingestion statistics

**Example**:
```python
from metrics.services.metrics_collector import MetricsCollector

collector = MetricsCollector()
result = collector.collect_batch([
    {"name": "cpu.load", "value": 0.75, "labels": {"host": "web-01"}},
    {"name": "memory.used_percent", "value": 65.2, "labels": {"host": "web-01"}}
])

print(result)  # {'accepted': 2, 'rejected': 0, 'errors': []}
```

### ConsumerPool (`metrics/services/metrics_consumer.py`)
Background workers that consume from queue.

**Responsibilities**:
- Poll queue partitions for new events
- Parse and validate event payloads
- Write to time-series storage
- Commit offsets on success

**Example**:
```python
from metrics.services.metrics_consumer import ConsumerPool

pool = ConsumerPool(num_partitions=10)
stats = pool.process_all_once()  # Process one batch from each partition

print(stats)  # {'fetched': 100, 'written': 98, 'errors': 2}
```

### QueryService (`metrics/services/query_service.py`)
High-level query interface.

**Responsibilities**:
- Execute time-range queries with caching
- Support aggregations and grouping
- Provide helper methods (last hour, last day, etc.)
- Metadata queries (list metrics, labels, values)

**Example**:
```python
from metrics.services.query_service import QueryService

qs = QueryService()

# Query last hour of CPU data, averaged by host
results = qs.query_last_hour(
    metric_name='cpu.load',
    aggregation='avg',
    group_by=['host']
)

for result in results:
    print(f"{result['labels']['host']}: {result['value']:.2f}")
```

### AlertManager (`metrics/services/alert_manager.py`)
Evaluates alert rules and manages state transitions.

**Responsibilities**:
- Fetch enabled alert rules
- Query current metric values
- Check conditions (>, <, etc.)
- Transition alert states
- Trigger notifications

**Example**:
```python
from metrics.services.alert_manager import AlertManager

manager = AlertManager()
stats = manager.evaluate_all_rules()

print(stats)  # {'rules_evaluated': 5, 'alerts_triggered': 2, 'alerts_resolved': 1}
```

### NotificationService (`metrics/services/notification_service.py`)
Multi-channel alert delivery.

**Channels**:
- **Email**: SMTP-based (simulated)
- **Webhook**: HTTP POST to custom URL
- **PagerDuty**: Integration API (simulated)

**Features**:
- Retry with exponential backoff
- Error tracking
- Notification throttling

---

## Testing

Run the test suite:

```bash
make test
# Or: pytest
```

**Test coverage** (planned):
- Unit tests for services, storage layer, serializers
- Integration tests for API endpoints
- End-to-end tests for complete workflows

---

## Makefile Commands

```bash
make setup          # Start Docker containers (PostgreSQL + Redis)
make start          # Start containers (alias for setup)
make stop           # Stop containers
make migrate        # Apply database migrations
make shell          # Django shell
make server         # Start development server
make demo           # Run interactive demo
make test           # Run test suite
make clean          # Stop containers and remove volumes
```

---

## Scaling Strategies

### Current Capacity
- Single Django server: ~1000 req/sec
- PostgreSQL: ~10K writes/sec
- Redis: ~100K ops/sec

### 10x Scale (10M metrics/min)

**Bottlenecks**:
- PostgreSQL write throughput
- Single Redis cache instance

**Solutions**:
- **Horizontal collectors**: Deploy behind load balancer
- **Database sharding**: Partition by hash(metric_name)
- **Read replicas**: Separate read/write paths
- **Redis cluster**: Multiple cache nodes

### 100x Scale (100M metrics/min)

**Bottlenecks**:
- Network bandwidth to database
- JSONB query performance
- Alert evaluation CPU

**Solutions**:
- **Dedicated TSDB**: Migrate to InfluxDB/Prometheus
- **Edge collectors**: Multi-region deployment
- **Streaming aggregation**: Flink/Spark for real-time rollups
- **Distributed alerting**: Shard rules across workers

### 1000x Scale (1B metrics/min - Google/AWS scale)

**Architecture changes**:
- **Write-ahead log** on collectors for local buffering
- **Object storage** (S3) for long-term retention
- **Columnar format** (Parquet) for compression
- **Federated querying** across regions
- **Custom TSDB** with specialized compression

---

## Production vs This Implementation

| Aspect | This Implementation | Production (Prometheus/Datadog) |
|--------|---------------------|----------------------------------|
| **Storage** | PostgreSQL + JSONB | Specialized TSDB (columnar) |
| **Compression** | None | Delta-of-delta, gorilla encoding |
| **Indexing** | B-tree | Inverted index on labels |
| **Querying** | SQL + JSON ops | PromQL, custom DSL |
| **Retention** | Manual aggregation | Automatic downsampling |
| **Clustering** | None | Multi-node with replication |
| **Alerting** | Database state | Separate Alertmanager |
| **Scale** | ~10K writes/sec | 1M+ writes/sec |

**Why the differences?**:
- This is for **learning**, not production
- Django/PostgreSQL are familiar, easier to understand
- Production systems use specialized data structures (LSM trees, inverted indexes)
- Compression (10x reduction) is critical at scale but complex to implement

---

## Interview Questions This Prepares For

### Design Questions
1. "Design a metrics monitoring system like Datadog"
2. "Design an alerting system for infrastructure monitoring"
3. "Design a time-series database"
4. "How would you monitor 1 million servers?"

### Follow-Up Topics
- Push vs pull architectures
- Time-series data compression
- Alert deduplication and grouping
- Query optimization strategies
- High-cardinality label problems
- Distributed tracing correlation
- Cost attribution in multi-tenant systems

### Behavioral Examples
- "Tell me about a time you designed an observability system"
- "How would you troubleshoot high latency in a metrics pipeline?"
- "Explain the trade-offs between different monitoring approaches"

---

## Extensions & Next Steps

### 1. Streaming Aggregation
Replace batch processing with Apache Flink for real-time rollups.

### 2. Distributed Tracing Integration
Add OpenTelemetry support to correlate metrics with traces.

### 3. Anomaly Detection
Implement ML-based alerting (ARIMA, Prophet) instead of static thresholds.

### 4. Multi-Region Deployment
Deploy edge collectors in multiple regions with cross-region replication.

### 5. Grafana Integration
Build a Grafana datasource plugin for visualization.

### 6. Cost Optimization
Add label cardinality limits, sampling, and tiered storage (hot/cold).

### 7. Custom Metrics SDK
Client libraries for Python, Java, Go with automatic instrumentation.

---

## Key Takeaways

### What This Project Teaches

1. **Observability Fundamentals**: Metrics, logs, and traces are the three pillars
2. **Time-Series Optimization**: Specialized storage, compression, and indexing
3. **Decoupling**: Message queues isolate failures and smooth traffic
4. **State Machines**: Alert lifecycle prevents flapping and spam
5. **Caching Strategies**: Adaptive TTL based on access patterns
6. **Horizontal Scaling**: Partitioning enables parallelism

### Production Awareness

- **Build vs Buy**: Most companies use Datadog/Prometheus, not custom solutions
- **Operational Complexity**: Monitoring systems need monitoring too (meta-monitoring)
- **Cost at Scale**: Label cardinality can explode storage costs
- **Trade-offs Matter**: Every design decision has implications

### Interview Skills

- **Structured thinking**: Requirements → Design → Deep dive → Scale
- **Calculation**: Storage math (metrics/min × retention = size)
- **Communication**: Explain trade-offs clearly, use diagrams
- **Production mindset**: Consider ops, cost, failure modes

---

## Related Projects

| Project | Concepts | Difficulty |
|---------|----------|------------|
| **[[distributed-message-queue]]** | Kafka internals, replication | ★★★ |
| **[[rate-limiter]]** | Request throttling, algorithms | ★★ |
| **[[distributed-cache]]** | Eviction policies, consistency | ★★★ |
| **[[notification-service]]** | Multi-channel delivery, routing | ★★ |
| **[[time-series-db]]** | Storage engine internals | ★★★★ |

---

## References

### System Design Interview
- **Book**: "System Design Interview Volume 2" by Alex Xu, Chapter 5
- **Topics**: Metrics monitoring, time-series databases, alerting

### Production Systems
- [Prometheus Documentation](https://prometheus.io/docs)
- [InfluxDB Architecture](https://docs.influxdata.com/influxdb/)
- [Datadog Blog](https://www.datadoghq.com/blog/engineering/)
- [Google Monarch Paper](https://research.google/pubs/pub43838/)

### Research Papers
- [Gorilla: Time-Series Compression](https://www.vldb.org/pvldb/vol8/p1816-teller.pdf)
- [Facebook Scuba: Time-Series Database](https://research.facebook.com/publications/scuba-diving-into-data-at-facebook/)

### Technologies
- [Django Documentation](https://docs.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [PostgreSQL JSONB](https://www.postgresql.org/docs/current/datatype-json.html)
- [Redis Caching](https://redis.io/docs/manual/client-side-caching/)

---

## Contributing

This is an educational project for learning system design. Contributions welcome:

- Improve documentation clarity
- Add test coverage
- Implement extensions (ML alerting, tracing, etc.)
- Optimize performance
- Fix bugs

---

## License

MIT License - See LICENSE file for details.

---

## Acknowledgments

- **Alex Xu** for "System Design Interview Volume 2"
- **Django community** for excellent documentation
- **Prometheus/InfluxDB teams** for open-source TSDB implementations

---

## Contact & Questions

For questions about this implementation or system design interviews:
- Open an issue in the repository
- See `docs/02-learnings.md` for interview prep materials
- Review `docs/01-architecture.md` for detailed system design

**Happy Learning!** 🚀
