---
title: "Learnings & Interview Prep"
created: 2025-01-01
tags:
  - system-design
  - interview-prep
  - metrics-monitoring
  - observability
  - learnings
phase: 5
system: metrics-monitoring-alerting
---

# Metrics Monitoring & Alerting System - Learnings

> **Purpose**: This document synthesizes key learnings from implementing a metrics monitoring and alerting system, organized for interview preparation and deep understanding.

---

## What I Built

A **production-grade metrics monitoring and alerting system** demonstrating core observability patterns:

### Core Components

1. **Push-Based Metrics Collection**
   - Collection agents running on monitored hosts
   - Batched metric ingestion via REST API
   - Validation and normalization layer
   - 202 Accepted fire-and-forget pattern

2. **Message Queue Buffering** (Kafka Simulation)
   - Partitioned queue for horizontal scaling
   - Offset-based consumption tracking
   - At-least-once delivery semantics
   - Consumer group coordination

3. **Time-Series Storage** (TSDB Simulation)
   - Tag-based data model using JSONB
   - Composite indexes for time-range queries
   - Retention policy with tiered aggregation
   - Series ID generation via fingerprinting

4. **Query Service**
   - Time-range queries with label filtering
   - Aggregations: avg, max, min, sum, count
   - Group-by functionality
   - Adaptive caching (hot/warm/cold data)

5. **Alert System**
   - Rule-based threshold monitoring
   - State machine: inactive → pending → firing → resolved
   - Multi-channel notifications (email, webhook, PagerDuty)
   - Fingerprint-based deduplication

### Scale Profile

- **Design Target**: 100M DAU, 10M metrics/min
- **Retention**: 1 year with tiered aggregation
- **Query Pattern**: 85% of queries for last 26 hours
- **Data Model**: ~1KB per metric, ~100B labels per series

---

## Core Insights

### 1. Push vs Pull Models

**Push Model** (What I Built):
- Agents actively send metrics to collectors
- Pros: Simple agent config, NAT-friendly, immediate data
- Cons: Collector must handle traffic spikes, harder to detect dead agents
- **Use Case**: Ephemeral workloads (containers, lambdas)

**Pull Model** (Prometheus):
- Collectors scrape metrics from agent endpoints
- Pros: Service discovery, easy to detect dead targets, backpressure control
- Cons: Requires network access to agents, polling latency
- **Use Case**: Long-lived infrastructure

> [!tip] Interview Insight
> In interviews, discuss the trade-off: "Push is better for ephemeral workloads and services behind NAT. Pull is better when you need centralized control over scrape intervals and want to detect dead targets."

### 2. Time-Series Storage Optimization

**Key Concepts Implemented**:

- **[[time-series-database]]**: Specialized storage for temporal data
- **[[downsampling]]**: Raw → 1-min → 1-hour aggregation for retention
- **[[tag-based-indexing]]**: JSONB labels for flexible querying
- **[[series-cardinality]]**: Unique metric name + label combinations

**Django Implementation vs Production TSDB**:

| Aspect | Django (My Impl) | InfluxDB/Prometheus |
|--------|------------------|---------------------|
| Storage | Row-per-datapoint | Columnar chunks |
| Compression | None | Delta-of-delta + gorilla |
| Indexing | B-tree on (name, time) | Inverted index on labels |
| Retention | Manual aggregation | Automatic rollup |
| Query | SQL with JSON ops | Custom query language |

**What I Learned**: The chapter's architecture works at scale because:
1. Columnar storage → 10x compression for time-series data
2. Inverted indexes → O(1) label lookups vs O(n) JSON scans
3. Write-optimized chunks → Batch writes without blocking reads

### 3. Message Queue as Decoupling Layer

**[[message-queue]]** between collection and storage provides:

1. **Traffic Smoothing**: Absorbs spikes without overwhelming storage
2. **Horizontal Scaling**: Partition-based parallelism
3. **Replay Capability**: Offset-based consumption enables reprocessing
4. **Failure Isolation**: Collector failures don't lose data

**Kafka Simulation Implementation**:
```python
# Partition assignment via consistent hashing
partition = hash(metric_name) % num_partitions

# Offset tracking for resumption
last_offset = Consumer.get_committed_offset(partition)
events = Queue.consume(partition, offset=last_offset, batch_size=1000)
```

**At Scale**: Real Kafka adds:
- Replication (3 replicas minimum)
- Leader election for partitions
- Distributed coordination (ZooKeeper/KRaft)
- Disk-based durability with page cache optimization

### 4. Alert State Machine

**[[alert-state-machine]]** prevents flapping and spam:

```
inactive → pending → firing → resolved
           ↑         ↓
           └─ (duration check)
```

**Key Design Decisions**:

1. **Pending State**: Condition must be true for `duration_seconds` before firing
   - Prevents flapping from transient spikes
   - Trade-off: Delays alerts by duration window

2. **Fingerprint Deduplication**: `MD5(rule_id + sorted_labels)`
   - Ensures one alert instance per unique condition
   - Prevents duplicate notifications

3. **Notification Throttling**: Minimum 5-minute interval
   - Reduces alert fatigue
   - Configurable via rule settings

**What I Learned**: Production alert systems (PagerDuty, Alertmanager) add:
- Grouping: Combine similar alerts
- Silencing: Temporary mute during maintenance
- Routing: Different teams for different alert types
- Escalation: Notify on-call rotation if unacknowledged

### 5. Query Optimization Strategies

**[[adaptive-caching]]** based on data age:

| Data Age | TTL | Reasoning |
|----------|-----|-----------|
| < 1 hour | 60s | Hot data, high query rate, likely changing |
| 1-24 hours | 300s | Warm data, moderate query rate, stable |
| > 24 hours | 3600s | Cold data, low query rate, immutable |

**Implementation**:
```python
def adaptive_ttl(data_age: timedelta) -> int:
    if data_age < timedelta(hours=1):
        return 60  # Hot: queries for "last 5 minutes"
    elif data_age < timedelta(hours=24):
        return 300  # Warm: queries for "last 6 hours"
    else:
        return 3600  # Cold: historical analysis
```

**Additional Optimizations**:
- **Composite indexes**: `(name, timestamp)` for range scans
- **Query result caching**: Cache key = hash(query params)
- **Aggregation pre-computation**: Materialized views for common queries

---

## At Scale Considerations

### 10x Scale (1B DAU, 100M metrics/min)

**Challenges**:
1. Single PostgreSQL can't handle write throughput
2. Cache hit rate drops due to query diversity
3. Alert evaluation becomes CPU-bound

**Solutions**:
- **Sharding**: Partition metrics by hash(metric_name) across multiple DBs
- **Read replicas**: Separate read/write paths
- **Background workers**: Dedicated alert evaluation processes

### 100x Scale (10B DAU, 1B metrics/min)

**Challenges**:
1. JSONB label queries become bottleneck
2. Network bandwidth between collectors and storage
3. Single Kafka cluster limits

**Solutions**:
- **Dedicated TSDB**: Migrate to InfluxDB/Prometheus with:
  - Columnar storage for compression
  - Inverted indexes for labels
  - Distributed queries
- **Edge collectors**: Multi-region deployment with local buffering
- **Kafka clustering**: Multi-datacenter replication

### 1000x Scale (100B DAU, 10B metrics/min - Google/AWS scale)

**Architecture Changes**:
- **[[write-ahead-log]]** on collectors for local buffering
- **[[distributed-tracing]]** integration (correlate metrics with traces)
- **[[stream-processing]]** (Flink/Spark) for real-time aggregation
- **[[object-storage]]** (S3) for long-term retention
- **[[federated-querying]]** across regions

**Real-World Examples**:
- **Google Monarch**: 2B metrics/sec, custom columnar storage
- **AWS CloudWatch**: 500M metrics/day, serverless architecture
- **Datadog**: Multi-tenant SaaS, edge aggregation

---

## Interview Preparation

### Clarifying Questions to Ask

When given "Design a metrics monitoring system":

1. **Scale Questions**:
   - How many hosts/services are we monitoring?
   - What's the expected metric ingestion rate?
   - How long should we retain data?
   - What query patterns do users have?

2. **Functional Requirements**:
   - Do we need real-time alerting or is near-real-time okay?
   - What aggregation functions are required?
   - Do we support custom metrics or just system metrics?
   - Multi-tenancy? (SaaS vs internal tool)

3. **Non-Functional Requirements**:
   - Availability vs consistency trade-off?
   - Acceptable data loss during failures?
   - Query latency SLO?
   - Cost constraints?

4. **Scope Questions**:
   - Build vs buy for TSDB? (InfluxDB, Prometheus, Datadog)
   - Should we include log aggregation? (metrics + logs + traces = observability)
   - Distributed tracing integration?

### 5-Minute Explanation Script

**Opening** (30 seconds):
> "I'll design a metrics monitoring system that collects, stores, and queries time-series data from distributed services, with alerting capabilities. Think Datadog or Prometheus. Let me start with requirements..."

**Requirements** (1 minute):
> "Assuming 100M DAU with 10M metrics per minute, 1-year retention. Functional requirements: push-based collection, time-range queries with aggregations, threshold-based alerting. Non-functional: 99.9% availability, < 1 second query latency for recent data."

**High-Level Architecture** (1.5 minutes):
> "Four main components:
> 1. **Metric Collectors**: Receive pushed metrics via REST API, validate, and enqueue to Kafka
> 2. **Message Queue**: Kafka partitions for buffering and decoupling
> 3. **Storage Layer**: Time-series database (InfluxDB) with tag-based indexing
> 4. **Query & Alert Service**: Handles queries with caching, evaluates alert rules
>
> Data flow: Agents → Collectors → Kafka → TSDB → Query Service → Users/Alerts"

**Deep Dive - Storage** (1 minute):
> "For storage, I'm using a specialized TSDB like InfluxDB because:
> - Columnar format optimized for time-series compression
> - Inverted indexes on labels for fast filtering
> - Built-in downsampling for retention policies
>
> Data model: Each metric is (name, labels, timestamp, value). We generate a series ID from name + labels. Store raw data for 7 days, 1-min aggregates for 30 days, 1-hour aggregates for 1 year."

**Deep Dive - Alerting** (45 seconds):
> "Alert rules define threshold conditions. We use a state machine:
> - **Pending**: Condition true, waiting for duration
> - **Firing**: Condition true for full duration, send notification
> - **Resolved**: Condition false again
>
> This prevents flapping. We fingerprint alerts to avoid duplicates."

**Scaling** (15 seconds):
> "To scale: shard TSDB by metric name, use read replicas for queries, deploy collectors in multiple regions, partition Kafka for parallelism."

### Expected Follow-Up Questions

**Q: Why push instead of pull?**
A: "Push is better for ephemeral workloads like containers and serverless functions that may not have stable endpoints. Pull (Prometheus) is better for long-lived services where you want centralized control. In practice, many systems support both - Datadog has agents that push, Prometheus pulls. For this design, push simplifies NAT traversal and works well with cloud-native architectures."

**Q: How do you handle late-arriving data?**
A: "Late data is metrics that arrive after their timestamp. TSDB solutions handle this differently:
- InfluxDB: Accepts late data, can backfill
- Prometheus: Rejects data older than scrape interval
- My design: Accept late data within a window (e.g., 1 hour), reject older. For aggregations, use event-time windowing (Flink) instead of processing-time. Trade-off: Accepting late data complicates aggregation, rejecting loses data."

**Q: How would you reduce storage costs?**
A: "Several strategies:
1. **Downsampling**: Store high-res for 7 days, then aggregate
2. **Compression**: Delta-of-delta encoding reduces size by 10x
3. **Selective retention**: Critical metrics for 1 year, others for 30 days
4. **Tiered storage**: Hot data in SSD, cold in S3
5. **Label cardinality limits**: Prevent explosion from high-cardinality labels like user IDs
6. **Sampling**: For high-volume metrics, sample 10% instead of storing all"

**Q: How do you prevent alert fatigue?**
A: "Multiple mechanisms:
1. **Duration threshold**: Only fire after condition persists
2. **Notification throttling**: Max 1 per 5 minutes per alert
3. **Grouping**: Combine related alerts (all web servers down → one 'web cluster down' alert)
4. **Severity levels**: Critical goes to PagerDuty, warning to Slack
5. **Silencing**: Manual mute during maintenance
6. **Anomaly detection**: Instead of static thresholds, detect deviations from baseline"

**Q: What's your write path latency budget?**
A: "Breaking down the write path:
- Agent → Collector: 10ms (HTTP POST)
- Collector → Kafka: 5ms (async produce)
- Kafka → Consumer: Variable (depends on batch size, target 100ms)
- Consumer → TSDB: 50ms (batch write)
- Total: ~165ms end-to-end
- Trade-off: Could reduce to 50ms with direct writes, but lose buffering and fault tolerance"

**Q: How would you handle multi-tenancy?**
A: "Two approaches:
1. **Shared infrastructure** (Datadog model):
   - Add tenant_id label to all metrics
   - Query-time filtering by tenant
   - Shared Kafka partitions
   - Pros: Resource efficiency, Cons: Noisy neighbor

2. **Isolated infrastructure**:
   - Separate Kafka clusters per tenant
   - Separate TSDB instances
   - Pros: Isolation, Cons: Higher cost

I'd use shared for small tenants, isolated for enterprise. Add rate limiting per tenant to prevent abuse."

**Q: How do you handle schema evolution?**
A: "Metrics are schema-less (name + labels + value), so adding new labels is backward-compatible. Challenges:
- Renaming metrics: Use metric mapping layer, maintain both names during migration
- Changing label names: Similar mapping, deprecation period
- Removing labels: Queries must handle missing labels gracefully
- Label value changes: Document breaking changes, version APIs
- Store schema metadata separately for validation and documentation"

**Q: How would you implement anomaly detection?**
A: "Beyond static thresholds:
1. **Statistical methods**:
   - Calculate rolling mean and std deviation
   - Alert when value > mean + 3*std
2. **Machine learning**:
   - Train model on historical patterns (daily/weekly seasonality)
   - Detect outliers using isolation forest or autoencoders
3. **Comparative analysis**:
   - Compare metric across peers (this server vs other servers)
   - Alert if one deviates significantly
4. **Trade-offs**:
   - ML requires training data, compute resources
   - Static thresholds are explainable, predictable
   - Hybrid: ML for detection, human-defined thresholds as guardrails"

**Q: What happens if Kafka goes down?**
A: "Failure modes:
1. **Kafka unavailable**:
   - Collectors buffer locally (write-ahead log, 10-minute capacity)
   - Return 503 to agents if buffer full
   - Agents retry with exponential backoff
2. **Kafka partition leader failure**:
   - Automatic failover to replica (< 30 seconds)
   - Some in-flight writes may fail, agents retry
3. **Extended outage**:
   - Shed load: Sample metrics, drop low-priority
   - Alert operators
   - Resume from last committed offset when restored
Trade-off: Could bypass Kafka in emergencies (direct to TSDB), but lose ordering guarantees"

---

## Key Trade-Offs Encountered

### 1. Push vs Pull
- **Chose**: Push
- **Why**: Better for containers/serverless, simpler agent deployment
- **Cost**: Must handle traffic spikes, harder to detect dead agents

### 2. JSONB vs Separate Tables for Labels
- **Chose**: JSONB
- **Why**: Flexible schema, no migrations for new labels
- **Cost**: Slower queries vs indexed columns, limited query optimization

### 3. Synchronous vs Asynchronous Writes
- **Chose**: Asynchronous (via Kafka)
- **Why**: Higher throughput, decoupling, buffering
- **Cost**: Increased complexity, eventual consistency

### 4. Alert Duration Threshold
- **Chose**: Required duration before firing
- **Why**: Prevents flapping from transient issues
- **Cost**: Delayed alerting (could miss brief outages)

### 5. Cache TTL Strategy
- **Chose**: Adaptive based on data age
- **Why**: Balances freshness and cache hit rate
- **Cost**: More complex cache management, requires tuning

---

## Concepts Reinforced

### System Design Patterns
- [[push-model]] vs [[pull-model]] architectures
- [[message-queue]] as decoupling layer
- [[time-series-database]] fundamentals
- [[alert-state-machine]] for stability
- [[adaptive-caching]] strategies
- [[horizontal-scaling]] via partitioning
- [[write-ahead-log]] for durability
- [[consistent-hashing]] for distribution

### Data Engineering
- [[downsampling]] for retention policies
- [[tag-based-indexing]] for time-series
- [[series-cardinality]] management
- [[inverted-index]] for label queries
- [[columnar-storage]] for compression
- [[delta-encoding]] for time-series

### Observability Concepts
- [[metrics]] vs [[logs]] vs [[traces]] (three pillars)
- [[high-cardinality]] label problems
- [[aggregation]] functions (avg, max, min, sum, count, percentiles)
- [[group-by]] queries for dimensional analysis
- [[threshold-based-alerting]] vs [[anomaly-detection]]

### Distributed Systems
- [[at-least-once-delivery]] semantics
- [[consumer-offset]] tracking for resumption
- [[partition-based-parallelism]]
- [[sharding]] strategies
- [[read-replicas]] for scaling reads

---

## Extensions to Explore

### 1. Distributed Tracing Integration
- Correlate metrics with traces for root cause analysis
- Add trace_id to metrics during collection
- Query metrics for specific trace IDs
- **Reference**: OpenTelemetry standard

### 2. Log Aggregation
- Complete the observability trifecta (metrics + logs + traces)
- Centralized log collection (like ELK stack)
- Correlate logs with metric spikes
- **Tool**: Elasticsearch + Filebeat

### 3. Predictive Alerting
- ML-based anomaly detection
- Forecast future values (ARIMA, Prophet)
- Alert before threshold is reached
- **Challenge**: Training data, model maintenance

### 4. Multi-Region Deployment
- Edge collectors in each region
- Cross-region replication for disaster recovery
- Global query federation
- **Trade-off**: Consistency vs availability

### 5. Cost Attribution
- Track metrics storage cost by tenant/team
- Implement quotas and rate limits
- Billing based on metrics volume
- **Use Case**: Multi-tenant SaaS

### 6. Custom Metrics SDK
- Client libraries for Python, Java, Go
- Automatic host/service labeling
- Built-in metric types (counter, gauge, histogram)
- **Reference**: Prometheus client libraries

### 7. Grafana Integration
- Build Grafana datasource plugin
- Support for Grafana query language
- Dashboard templating
- **Benefit**: Industry-standard visualization

---

## Related Implementations

| System | Overlap | Differences |
|--------|---------|-------------|
| **[[distributed-message-queue]]** | Kafka simulation | Focuses on queue internals, replication |
| **[[rate-limiter]]** | Request throttling | Different algorithm (token bucket vs threshold) |
| **[[distributed-cache]]** | Cache layer | Focus on eviction policies, consistency |
| **[[notification-service]]** | Alert delivery | Deeper on routing, templating, retries |
| **[[time-series-db]]** | Storage engine | Focuses on compression, indexing internals |

---

## Production System Comparisons

### Prometheus
- **Model**: Pull-based scraping
- **Storage**: Local time-series database
- **Query**: PromQL language
- **Alerting**: Separate Alertmanager component
- **Strength**: Kubernetes-native, simple deployment
- **Weakness**: No clustering, limited retention

### Datadog
- **Model**: Push-based agents
- **Storage**: Proprietary TSDB
- **Query**: Web UI + API
- **Alerting**: Integrated with ML anomaly detection
- **Strength**: SaaS, no ops overhead, beautiful UX
- **Weakness**: Expensive at scale, vendor lock-in

### InfluxDB
- **Model**: Push via HTTP or pull via Telegraf
- **Storage**: Custom TSM engine (columnar)
- **Query**: InfluxQL or Flux language
- **Alerting**: Kapacitor component
- **Strength**: High compression, flexible
- **Weakness**: Clustering complexity (InfluxDB Cloud vs OSS)

### Google Cloud Monitoring (Stackdriver)
- **Model**: Push via API
- **Storage**: Google Monarch backend
- **Query**: MQL (Monitoring Query Language)
- **Alerting**: Integrated with Cloud Functions
- **Strength**: Massive scale, GCP integration
- **Weakness**: GCP-only, learning curve

---

## Key Takeaways for Interviews

### What Interviewers Look For

1. **Understanding of Scale**:
   - Can you calculate storage requirements?
   - Do you consider network bandwidth?
   - Can you reason about trade-offs?

2. **System Thinking**:
   - How components interact
   - Failure modes and recovery
   - Observability of the observability system (meta!)

3. **Production Awareness**:
   - Operational complexity
   - Cost considerations
   - Monitoring and alerting for the system itself

4. **Communication**:
   - Structured thinking (requirements → design → deep dive → scale)
   - Whiteboard diagrams
   - Explaining trade-offs clearly

### Common Pitfalls to Avoid

1. **Jumping to Implementation**: Always clarify requirements first
2. **Ignoring Write Path**: Focusing only on querying, neglecting ingestion scale
3. **Over-Engineering**: Don't add every feature, focus on core use case
4. **Underestimating Cardinality**: High-cardinality labels can explode storage
5. **Forgetting Operational Costs**: Monitoring systems are expensive to run

### Phrases That Impress

- "Let me calculate the storage requirements..."
- "The trade-off here is X vs Y, I'd choose X because..."
- "At 10x scale, this component becomes the bottleneck, so we'd need to..."
- "In production, we'd also need to monitor X, handle failure mode Y..."
- "This is similar to how Prometheus/Datadog does it, but adapted for our scale"

---

## Personal Insights

### What Was Harder Than Expected

1. **Alert State Machine**: Preventing flapping while ensuring timely alerts required careful design
2. **Label Cardinality**: Easy to explode series count with high-cardinality labels (e.g., user_id)
3. **Query Performance**: JSONB queries are slow; production systems need inverted indexes
4. **Adaptive Caching**: Tuning TTL based on data age and query patterns required experimentation

### What Was Easier Than Expected

1. **Kafka Simulation**: Partition + offset model is simple, implementation was straightforward
2. **Django ORM**: JSONB support and composite indexes made TSDB simulation viable
3. **REST API Design**: DRF made it trivial to expose endpoints with validation

### What I'd Do Differently in Production

1. **Use InfluxDB/Prometheus**: Don't reinvent TSDB, use battle-tested solutions
2. **Add Sampling**: Implement reservoir sampling for high-volume metrics
3. **Streaming Aggregation**: Use Flink/Spark for real-time rollups instead of batch
4. **OpenTelemetry**: Integrate with OTEL for standard instrumentation
5. **Cost Controls**: Add tenant quotas, rate limits, storage caps from day one

---

## Changelog

### 2025-01-01
- Created comprehensive learnings and interview prep document
- Synthesized insights from implementation
- Added interview questions, follow-ups, and response scripts
- Documented trade-offs and production comparisons
- Included scaling considerations and extensions

---

## References

- System Design Interview Vol 2, Chapter 5 (Alex Xu)
- [Prometheus Documentation](https://prometheus.io/docs)
- [InfluxDB Architecture](https://docs.influxdata.com/influxdb/v2.0/reference/internals/)
- [Datadog Architecture Blog](https://www.datadoghq.com/blog/engineering/)
- [Google Monarch Paper](https://research.google/pubs/pub43838/)
- [Gorilla Time-Series Compression](https://www.vldb.org/pvldb/vol8/p1816-teller.pdf)
