#!/usr/bin/env python
"""
Interactive Demo Script

Demonstrates the complete metrics monitoring and alerting system workflow.

Run: python scripts/demo.py

This script:
1. Collects metrics from simulated agents
2. Processes queue (consumer writes to storage)
3. Queries metrics with aggregations
4. Creates alert rules
5. Evaluates alerts and triggers notifications
6. Shows system statistics

System Design Concepts Demonstrated:
- [[push-model]]: Agents push metrics to collectors
- [[message-queue]]: Kafka-style buffering
- [[time-series-query]]: Range queries with aggregations
- [[alert-state-machine]]: Alert lifecycle management
"""

import os
import sys
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'metrics_system.settings')
django.setup()

from metrics.services.metrics_collector import MetricsCollector, CollectionAgent
from metrics.services.metrics_consumer import ConsumerPool
from metrics.services.query_service import QueryService
from metrics.services.alert_manager import AlertManager
from metrics.models import AlertRule, Metric, AlertInstance
from datetime import datetime, timedelta
from django.utils import timezone
import time


def print_header(text):
    """Print formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80 + "\n")


def print_step(step_num, text):
    """Print formatted step."""
    print(f"\n[Step {step_num}] {text}")
    print("-" * 80)


def demo_metrics_collection():
    """Demo 1: Metrics Collection (Push Model)"""
    print_header("DEMO 1: Metrics Collection (Push Model)")

    print_step(1, "Initializing Collection Agents")

    # Create agents for multiple hosts
    collector = MetricsCollector()

    agents = [
        CollectionAgent(
            collector=collector,
            host_labels={'host': f'web-{i:02d}', 'region': 'us-west', 'role': 'web'}
        )
        for i in range(1, 6)
    ]

    print(f"✓ Created {len(agents)} collection agents")

    print_step(2, "Collecting System Metrics")

    total_collected = 0

    for agent in agents:
        metrics = agent.collect_system_metrics()
        result = agent.push(metrics)

        total_collected += result['accepted']

        print(f"  Agent {agent.host_labels['host']}: Collected {len(metrics)} metrics")

    print(f"\n✓ Total metrics queued: {total_collected}")

    # Show queue statistics
    stats = collector.get_queue_stats()
    print(f"\nQueue Statistics:")
    print(f"  - Total events in queue: {stats['total_events']}")
    print(f"  - Unconsumed events: {stats['unconsumed_events']}")
    print(f"  - Partitions: {stats['partitions']}")


def demo_queue_processing():
    """Demo 2: Queue Processing (Consumer)"""
    print_header("DEMO 2: Queue Processing (Kafka Consumer Simulation)")

    print_step(1, "Processing Queued Metrics")

    pool = ConsumerPool(num_partitions=10)

    # Process all pending events
    stats = pool.process_all_once()

    print(f"✓ Consumed {stats['fetched']} events")
    print(f"✓ Wrote {stats['written']} metrics to storage")
    if stats['errors'] > 0:
        print(f"✗ {stats['errors']} errors")

    # Verify storage
    metric_count = Metric.objects.count()
    print(f"\n✓ Total metrics in storage: {metric_count}")


def demo_querying():
    """Demo 3: Querying Metrics"""
    print_header("DEMO 3: Querying Time-Series Data")

    qs = QueryService()

    print_step(1, "Listing Available Metrics")

    metric_names = qs.list_metrics()
    print(f"Available metrics:")
    for name in metric_names:
        print(f"  - {name}")

    print_step(2, "Querying CPU Load (Last Hour)")

    results = qs.query_last_hour(
        metric_name='cpu.load',
        aggregation='avg'
    )

    if results:
        avg_cpu = results[0]['value']
        count = results[0]['count']
        print(f"✓ Average CPU load: {avg_cpu:.2f} (across {count} data points)")
    else:
        print("✗ No data available")

    print_step(3, "Querying CPU by Host (Grouped)")

    results = qs.query_last_hour(
        metric_name='cpu.load',
        aggregation='avg',
        group_by=['host']
    )

    print(f"CPU load by host:")
    for result in results[:5]:  # Show first 5
        host = result['labels'].get('host', 'unknown')
        value = result['value']
        print(f"  - {host}: {value:.2f}")

    print_step(4, "Getting Latest Values")

    latest_cpu = qs.get_latest_value('cpu.load')
    latest_memory = qs.get_latest_value('memory.used_percent')

    print(f"Latest values:")
    print(f"  - CPU: {latest_cpu:.2f}" if latest_cpu else "  - CPU: No data")
    print(f"  - Memory: {latest_memory:.2f}%" if latest_memory else "  - Memory: No data")


def demo_alerting():
    """Demo 4: Alert Rules and Evaluation"""
    print_header("DEMO 4: Alert System (State Machine)")

    print_step(1, "Creating Alert Rules")

    # Delete existing rules to start fresh
    AlertRule.objects.all().delete()
    AlertInstance.objects.all().delete()

    # Create high CPU alert
    high_cpu_rule = AlertRule.objects.create(
        name='high_cpu_usage',
        metric_name='cpu.load',
        condition='>',
        threshold=0.7,
        duration_seconds=60,  # 1 minute
        label_filters={},
        severity='warning',
        notification_channels=['webhook'],
        webhook_url='https://hooks.example.com/alerts',
        annotations={
            'summary': 'High CPU usage detected on {{ host }}',
            'description': 'CPU load is {{ value }}, threshold is {{ threshold }}'
        },
        enabled=True
    )

    print(f"✓ Created alert rule: {high_cpu_rule.name}")
    print(f"  Condition: {high_cpu_rule.metric_name} {high_cpu_rule.condition} {high_cpu_rule.threshold}")
    print(f"  Duration: {high_cpu_rule.duration_seconds}s")

    # Create high memory alert
    high_memory_rule = AlertRule.objects.create(
        name='high_memory_usage',
        metric_name='memory.used_percent',
        condition='>',
        threshold=80.0,
        duration_seconds=120,
        severity='critical',
        notification_channels=['webhook'],
        webhook_url='https://hooks.example.com/alerts',
        enabled=True
    )

    print(f"✓ Created alert rule: {high_memory_rule.name}")

    print_step(2, "Evaluating Alert Rules")

    manager = AlertManager()
    stats = manager.evaluate_all_rules()

    print(f"✓ Evaluated {stats['rules_evaluated']} rules")
    print(f"  - Alerts triggered: {stats['alerts_triggered']}")
    print(f"  - Alerts resolved: {stats['alerts_resolved']}")
    print(f"  - Errors: {stats['errors']}")

    print_step(3, "Checking Alert States")

    alerts = AlertInstance.objects.all()

    print(f"Alert instances:")
    for alert in alerts:
        print(f"  - {alert.rule.name}: {alert.state} (value={alert.current_value:.2f})")

    firing_alerts = AlertInstance.objects.filter(state='firing')
    if firing_alerts.exists():
        print(f"\n⚠ {firing_alerts.count()} alerts are FIRING!")
    else:
        print(f"\n✓ No alerts firing")


def demo_statistics():
    """Demo 5: System Statistics"""
    print_header("DEMO 5: System Statistics")

    print_step(1, "Overall System Stats")

    total_metrics = Metric.objects.count()
    total_alerts = AlertInstance.objects.count()
    active_alerts = AlertInstance.objects.filter(state='firing').count()

    print(f"System Overview:")
    print(f"  - Total metrics stored: {total_metrics}")
    print(f"  - Total alert instances: {total_alerts}")
    print(f"  - Active (firing) alerts: {active_alerts}")

    print_step(2, "Metrics Breakdown")

    from django.db.models import Count

    breakdown = Metric.objects.values('name').annotate(
        count=Count('id')
    ).order_by('-count')

    print(f"Metrics by type:")
    for item in breakdown:
        print(f"  - {item['name']}: {item['count']} data points")

    print_step(3, "Time Range")

    from django.db.models import Min, Max

    time_range = Metric.objects.aggregate(
        start=Min('timestamp'),
        end=Max('timestamp')
    )

    if time_range['start'] and time_range['end']:
        duration = time_range['end'] - time_range['start']
        print(f"Data time range:")
        print(f"  - Start: {time_range['start']}")
        print(f"  - End: {time_range['end']}")
        print(f"  - Duration: {duration}")


def main():
    """Run complete demo."""
    print("\n" + "=" * 80)
    print("  METRICS MONITORING AND ALERTING SYSTEM - Interactive Demo")
    print("  Demonstrating System Design Concepts from Chapter 5")
    print("=" * 80)

    try:
        # Run all demos
        demo_metrics_collection()
        time.sleep(1)

        demo_queue_processing()
        time.sleep(1)

        demo_querying()
        time.sleep(1)

        demo_alerting()
        time.sleep(1)

        demo_statistics()

        # Final summary
        print_header("DEMO COMPLETE")

        print("System Design Concepts Demonstrated:")
        print("  ✓ Push-based metrics collection")
        print("  ✓ Message queue buffering (Kafka simulation)")
        print("  ✓ Time-series data storage and indexing")
        print("  ✓ Query service with caching")
        print("  ✓ Alert state machine (inactive → pending → firing → resolved)")
        print("  ✓ Multi-channel notification system")
        print("")
        print("Next Steps:")
        print("  - View data in Django admin: http://localhost:8000/admin")
        print("  - Query via API: http://localhost:8000/api/v1/query?metric_name=cpu.load")
        print("  - Check health: http://localhost:8000/api/v1/health")
        print("\n")

    except Exception as e:
        print(f"\n✗ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
