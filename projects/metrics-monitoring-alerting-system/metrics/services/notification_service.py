"""
Notification Service

System Design Concept:
    [[notification-channels]] - Multi-channel alert delivery

Simulates:
    Email, Webhook, PagerDuty integrations

At Scale:
    - Retry with exponential backoff
    - Rate limiting per channel
    - Notification deduplication
    - Delivery tracking and analytics
"""

from metrics.models import AlertInstance
from django.conf import settings
from typing import Dict, Any
from datetime import datetime, timedelta
import logging
import json

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Sends alert notifications to multiple channels.

    Supports:
        - Email (simulated)
        - Webhooks (HTTP POST)
        - PagerDuty (simulated)

    Features:
        - Retry logic with exponential backoff
        - Delivery tracking
        - Template-based messages

    Usage:
        service = NotificationService()

        # Send alert
        service.send_alert(alert_instance)

        # Send resolution
        service.send_resolved(alert_instance)
    """

    def __init__(self):
        """Initialize notification service."""
        self.max_retries = getattr(settings, 'ALERT_RETRY_MAX_ATTEMPTS', 3)

        # Channel enabled flags from settings
        self.email_enabled = getattr(settings, 'EMAIL_ENABLED', False)
        self.webhook_enabled = getattr(settings, 'WEBHOOK_ENABLED', True)
        self.pagerduty_enabled = getattr(settings, 'PAGERDUTY_ENABLED', False)

        logger.info(
            f"NotificationService initialized "
            f"(email={self.email_enabled}, webhook={self.webhook_enabled}, "
            f"pagerduty={self.pagerduty_enabled})"
        )

    def send_alert(self, alert: AlertInstance) -> Dict[str, Any]:
        """
        Send firing alert notification.

        Args:
            alert: AlertInstance in 'firing' state

        Returns:
            Delivery status per channel
        """
        logger.info(f"Sending alert notification: {alert.rule.name}")

        # Build notification payload
        payload = self._build_alert_payload(alert, status='firing')

        # Send to enabled channels
        results = {}

        for channel in alert.rule.notification_channels:
            try:
                if channel == 'email' and self.email_enabled:
                    results['email'] = self._send_email(alert, payload)

                elif channel == 'webhook' and self.webhook_enabled:
                    results['webhook'] = self._send_webhook(alert, payload)

                elif channel == 'pagerduty' and self.pagerduty_enabled:
                    results['pagerduty'] = self._send_pagerduty(alert, payload)

                else:
                    logger.debug(f"Channel {channel} is disabled or unknown")

            except Exception as e:
                logger.error(f"Failed to send alert via {channel}: {e}")
                results[channel] = {'status': 'error', 'error': str(e)}
                alert.notification_errors += 1

        # Update alert notification tracking
        alert.notifications_sent += 1
        alert.last_notification_at = datetime.now()
        alert.save()

        return results

    def send_resolved(self, alert: AlertInstance) -> Dict[str, Any]:
        """
        Send resolved alert notification.

        Args:
            alert: AlertInstance in 'resolved' state

        Returns:
            Delivery status per channel
        """
        logger.info(f"Sending resolution notification: {alert.rule.name}")

        # Build resolution payload
        payload = self._build_alert_payload(alert, status='resolved')

        # Send to enabled channels (same as firing)
        results = {}

        for channel in alert.rule.notification_channels:
            try:
                if channel == 'email' and self.email_enabled:
                    results['email'] = self._send_email(alert, payload)

                elif channel == 'webhook' and self.webhook_enabled:
                    results['webhook'] = self._send_webhook(alert, payload)

                elif channel == 'pagerduty' and self.pagerduty_enabled:
                    results['pagerduty'] = self._send_pagerduty(alert, payload)

            except Exception as e:
                logger.error(f"Failed to send resolution via {channel}: {e}")
                results[channel] = {'status': 'error', 'error': str(e)}

        return results

    def _build_alert_payload(
        self,
        alert: AlertInstance,
        status: str
    ) -> Dict[str, Any]:
        """
        Build notification payload with alert details.

        Args:
            alert: AlertInstance
            status: 'firing' or 'resolved'

        Returns:
            Notification payload dict
        """
        rule = alert.rule

        # Render templates from rule annotations
        summary = rule.annotations.get('summary', f"Alert: {rule.name}")
        description = rule.annotations.get('description', '')

        # Simple template variable substitution
        template_vars = {
            'host': alert.labels.get('host', 'unknown'),
            'value': alert.current_value,
            'threshold': rule.threshold
        }

        for key, val in template_vars.items():
            summary = summary.replace(f"{{{{ {key} }}}}", str(val))
            description = description.replace(f"{{{{ {key} }}}}", str(val))

        payload = {
            'alert_name': rule.name,
            'status': status,
            'severity': rule.severity,
            'metric': rule.metric_name,
            'current_value': alert.current_value,
            'threshold': rule.threshold,
            'condition': f"{rule.metric_name} {rule.condition} {rule.threshold}",
            'labels': alert.labels,
            'summary': summary,
            'description': description,
            'firing_since': alert.firing_since.isoformat() if alert.firing_since else None,
            'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
            'timestamp': datetime.now().isoformat()
        }

        return payload

    def _send_email(self, alert: AlertInstance, payload: Dict[str, Any]) -> Dict[str, str]:
        """
        Send email notification (simulated).

        In production, this would use SMTP or email service API.

        Args:
            alert: AlertInstance
            payload: Notification payload

        Returns:
            Delivery status
        """
        recipients = alert.rule.email_recipients

        if not recipients:
            logger.warning(f"No email recipients configured for rule {alert.rule.name}")
            return {'status': 'skipped', 'reason': 'no_recipients'}

        # Simulate email send
        logger.info(
            f"[EMAIL SIMULATED] Sending to {recipients}: "
            f"{payload['alert_name']} is {payload['status']}"
        )

        # In production:
        # from django.core.mail import send_mail
        # send_mail(
        #     subject=f"[{payload['severity'].upper()}] {payload['summary']}",
        #     message=json.dumps(payload, indent=2),
        #     from_email='alerts@example.com',
        #     recipient_list=recipients
        # )

        return {
            'status': 'sent',
            'channel': 'email',
            'recipients': recipients
        }

    def _send_webhook(self, alert: AlertInstance, payload: Dict[str, Any]) -> Dict[str, str]:
        """
        Send webhook notification (HTTP POST).

        Args:
            alert: AlertInstance
            payload: Notification payload

        Returns:
            Delivery status
        """
        webhook_url = alert.rule.webhook_url

        if not webhook_url:
            logger.warning(f"No webhook URL configured for rule {alert.rule.name}")
            return {'status': 'skipped', 'reason': 'no_webhook_url'}

        # Simulate webhook POST
        logger.info(
            f"[WEBHOOK SIMULATED] POST {webhook_url}: "
            f"{payload['alert_name']} is {payload['status']}"
        )

        # In production:
        # import requests
        # response = requests.post(
        #     webhook_url,
        #     json=payload,
        #     timeout=10
        # )
        # response.raise_for_status()

        return {
            'status': 'sent',
            'channel': 'webhook',
            'url': webhook_url
        }

    def _send_pagerduty(self, alert: AlertInstance, payload: Dict[str, Any]) -> Dict[str, str]:
        """
        Send PagerDuty notification (simulated).

        In production, this would use PagerDuty Events API v2.

        Args:
            alert: AlertInstance
            payload: Notification payload

        Returns:
            Delivery status
        """
        logger.info(
            f"[PAGERDUTY SIMULATED] Triggering incident: "
            f"{payload['alert_name']} is {payload['status']}"
        )

        # In production:
        # import requests
        # pagerduty_payload = {
        #     "routing_key": settings.PAGERDUTY_ROUTING_KEY,
        #     "event_action": "trigger" if payload['status'] == 'firing' else "resolve",
        #     "dedup_key": alert.fingerprint,
        #     "payload": {
        #         "summary": payload['summary'],
        #         "severity": payload['severity'],
        #         "source": "metrics-monitoring-system",
        #         "custom_details": payload
        #     }
        # }
        # response = requests.post(
        #     "https://events.pagerduty.com/v2/enqueue",
        #     json=pagerduty_payload
        # )

        return {
            'status': 'sent',
            'channel': 'pagerduty',
            'dedup_key': alert.fingerprint
        }

    def send_with_retry(
        self,
        alert: AlertInstance,
        channel: str
    ) -> Dict[str, Any]:
        """
        Send notification with retry logic.

        Uses exponential backoff for transient failures.

        Args:
            alert: AlertInstance
            channel: Notification channel

        Returns:
            Final delivery status
        """
        import time

        payload = self._build_alert_payload(alert, status=alert.state)

        for attempt in range(self.max_retries):
            try:
                # Attempt send based on channel
                if channel == 'email':
                    result = self._send_email(alert, payload)
                elif channel == 'webhook':
                    result = self._send_webhook(alert, payload)
                elif channel == 'pagerduty':
                    result = self._send_pagerduty(alert, payload)
                else:
                    return {'status': 'error', 'error': f'Unknown channel: {channel}'}

                # Success
                logger.info(f"Notification sent via {channel} (attempt {attempt + 1})")
                return result

            except Exception as e:
                logger.warning(
                    f"Notification failed via {channel} (attempt {attempt + 1}/{self.max_retries}): {e}"
                )

                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    sleep_time = 2 ** attempt
                    time.sleep(sleep_time)
                else:
                    # Final attempt failed
                    return {
                        'status': 'failed',
                        'channel': channel,
                        'error': str(e),
                        'attempts': self.max_retries
                    }

    def test_notification(
        self,
        channel: str,
        test_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send test notification to verify channel configuration.

        Args:
            channel: Channel to test
            test_data: Custom test payload

        Returns:
            Test result
        """
        logger.info(f"Sending test notification via {channel}")

        try:
            if channel == 'email':
                return self._send_email(None, test_data)
            elif channel == 'webhook':
                return self._send_webhook(None, test_data)
            elif channel == 'pagerduty':
                return self._send_pagerduty(None, test_data)
            else:
                return {'status': 'error', 'error': f'Unknown channel: {channel}'}

        except Exception as e:
            logger.error(f"Test notification failed: {e}")
            return {'status': 'error', 'error': str(e)}
