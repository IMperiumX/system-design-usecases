"""
Alert Manager Service

System Design Concept:
    [[alert-state-machine]] - Alert lifecycle management

Simulates:
    Prometheus Alertmanager

At Scale:
    - Distributed alert state (Redis cluster)
    - High availability (active-active)
    - Alert grouping and aggregation
    - Silencing and inhibition rules
"""

from metrics.models import AlertRule, AlertInstance
from metrics.services.query_service import QueryService
from metrics.services.notification_service import NotificationService
from django.utils import timezone
from typing import List, Dict, Any
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


class AlertManager:
    """
    Evaluates alert rules and manages alert lifecycle.

    Responsibilities:
        - Periodic rule evaluation
        - Alert state machine management
        - Deduplication (fingerprinting)
        - Notification triggering

    Alert State Transitions:
        inactive → pending (condition true)
        pending → firing (duration threshold met)
        pending → inactive (condition false)
        firing → resolved (condition false)

    Usage:
        manager = AlertManager()

        # Evaluate all enabled rules once
        manager.evaluate_all_rules()

        # Run continuous evaluation loop
        manager.run(interval_seconds=30)
    """

    def __init__(
        self,
        query_service: QueryService = None,
        notification_service: NotificationService = None
    ):
        """
        Initialize alert manager.

        Args:
            query_service: QueryService for metric lookups
            notification_service: NotificationService for sending alerts
        """
        self.query_service = query_service or QueryService()
        self.notification_service = notification_service or NotificationService()

        logger.info("AlertManager initialized")

    def evaluate_all_rules(self) -> Dict[str, Any]:
        """
        Evaluate all enabled alert rules.

        Returns:
            Summary statistics
        """
        rules = AlertRule.objects.filter(enabled=True)

        stats = {
            'rules_evaluated': 0,
            'alerts_triggered': 0,
            'alerts_resolved': 0,
            'errors': 0
        }

        logger.info(f"Evaluating {rules.count()} alert rules")

        for rule in rules:
            try:
                result = self.evaluate_rule(rule)

                stats['rules_evaluated'] += 1
                stats['alerts_triggered'] += result['alerts_triggered']
                stats['alerts_resolved'] += result['alerts_resolved']

            except Exception as e:
                logger.error(f"Failed to evaluate rule {rule.name}: {e}")
                stats['errors'] += 1

        logger.info(
            f"Alert evaluation complete: {stats['alerts_triggered']} triggered, "
            f"{stats['alerts_resolved']} resolved"
        )

        return stats

    def evaluate_rule(self, rule: AlertRule) -> Dict[str, Any]:
        """
        Evaluate a single alert rule.

        Args:
            rule: AlertRule to evaluate

        Returns:
            Evaluation result:
                {
                    'rule': str,
                    'alerts_triggered': int,
                    'alerts_resolved': int,
                    'current_value': float
                }
        """
        logger.debug(f"Evaluating rule: {rule.name}")

        # Query current metric value
        try:
            current_value = self._get_metric_value(rule)

        except Exception as e:
            logger.error(f"Failed to query metrics for rule {rule.name}: {e}")
            return {
                'rule': rule.name,
                'alerts_triggered': 0,
                'alerts_resolved': 0,
                'error': str(e)
            }

        # No data available
        if current_value is None:
            logger.debug(f"No data available for rule {rule.name}")
            return {
                'rule': rule.name,
                'alerts_triggered': 0,
                'alerts_resolved': 0,
                'current_value': None
            }

        # Check if condition is met
        condition_met = rule.check_condition(current_value)

        logger.debug(
            f"Rule {rule.name}: value={current_value}, "
            f"threshold={rule.threshold}, condition_met={condition_met}"
        )

        # Get or create alert instance
        # For simplicity, using single fingerprint per rule (no label grouping)
        # In production, would create separate alerts per unique label combination
        fingerprint = AlertInstance.generate_fingerprint(
            rule.id,
            rule.label_filters
        )

        alert, created = AlertInstance.objects.get_or_create(
            rule=rule,
            fingerprint=fingerprint,
            defaults={
                'current_value': current_value,
                'labels': rule.label_filters,
                'state': 'inactive'
            }
        )

        # Update current value
        alert.current_value = current_value
        alert.save()

        # Process state transitions
        alerts_triggered = 0
        alerts_resolved = 0

        if condition_met:
            # Condition is true
            if alert.state == 'inactive':
                # inactive → pending
                alert.transition_to_pending(current_value)
                logger.info(f"Alert {rule.name} → pending (value={current_value})")

            elif alert.state == 'pending':
                # Check if duration threshold met
                if alert.should_fire():
                    # pending → firing
                    alert.transition_to_firing()
                    self.notification_service.send_alert(alert)
                    alerts_triggered += 1
                    logger.warning(f"Alert {rule.name} → FIRING (value={current_value})")

            elif alert.state == 'firing':
                # Still firing - could send repeated notifications
                # (implement notification throttling here)
                pass

        else:
            # Condition is false
            if alert.state == 'pending':
                # pending → inactive
                alert.transition_to_inactive()
                logger.info(f"Alert {rule.name} → inactive (condition no longer met)")

            elif alert.state == 'firing':
                # firing → resolved
                alert.transition_to_resolved()
                self.notification_service.send_resolved(alert)
                alerts_resolved += 1
                logger.info(f"Alert {rule.name} → RESOLVED (value={current_value})")

        return {
            'rule': rule.name,
            'alerts_triggered': alerts_triggered,
            'alerts_resolved': alerts_resolved,
            'current_value': current_value
        }

    def _get_metric_value(self, rule: AlertRule) -> float:
        """
        Query current metric value for alert rule.

        Uses max aggregation by default for gauges.
        Duration window = rule.duration_seconds.

        Args:
            rule: AlertRule with metric_name and label_filters

        Returns:
            Current metric value or None
        """
        duration = timedelta(seconds=rule.duration_seconds)

        results = self.query_service.query(
            metric_name=rule.metric_name,
            start_time=timezone.now() - duration,
            labels=rule.label_filters,
            aggregation='avg'  # Use average over duration window
        )

        if results and len(results) > 0:
            return results[0]['value']

        return None

    def get_active_alerts(self) -> List[AlertInstance]:
        """Get all currently firing alerts."""
        return list(AlertInstance.objects.filter(state='firing'))

    def get_all_alerts(self) -> List[AlertInstance]:
        """Get all alert instances (all states)."""
        return list(AlertInstance.objects.all().order_by('-updated_at'))

    def cleanup_old_alerts(self, days: int = 7) -> int:
        """
        Clean up old resolved alerts.

        Args:
            days: Delete resolved alerts older than N days

        Returns:
            Number of alerts deleted
        """
        cutoff = timezone.now() - timedelta(days=days)

        deleted_count, _ = AlertInstance.objects.filter(
            state='resolved',
            resolved_at__lt=cutoff
        ).delete()

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old resolved alerts")

        return deleted_count

    def run(self, interval_seconds: int = 30, max_iterations: int = None):
        """
        Run continuous alert evaluation loop.

        Args:
            interval_seconds: Evaluation frequency
            max_iterations: Stop after N iterations (None = forever)

        This would typically run as a background daemon/service.
        """
        import time

        iteration = 0

        logger.info(f"Starting alert evaluation loop (interval={interval_seconds}s)")

        while True:
            if max_iterations and iteration >= max_iterations:
                logger.info("Reached max iterations, stopping")
                break

            try:
                stats = self.evaluate_all_rules()

                logger.debug(
                    f"Evaluation cycle {iteration}: "
                    f"{stats['rules_evaluated']} rules, "
                    f"{stats['alerts_triggered']} triggered, "
                    f"{stats['alerts_resolved']} resolved"
                )

            except Exception as e:
                logger.error(f"Error in evaluation loop: {e}")

            time.sleep(interval_seconds)
            iteration += 1
