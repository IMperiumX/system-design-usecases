"""
URL routing for Metrics Monitoring API.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from metrics.views import (
    MetricsIngestView, QueryView, MetricsMetadataView,
    AlertRuleViewSet, AlertInstanceViewSet,
    SystemOperationsView, StatsView, HealthCheckView
)

# Router for viewsets
router = DefaultRouter()
router.register(r'alerts/rules', AlertRuleViewSet, basename='alertrule')
router.register(r'alerts/instances', AlertInstanceViewSet, basename='alertinstance')

urlpatterns = [
    # Health check
    path('health', HealthCheckView.as_view(), name='health'),

    # Metrics ingestion (POST)
    path('metrics', MetricsIngestView.as_view(), name='metrics-ingest'),

    # Metrics query (GET)
    path('query', QueryView.as_view(), name='query'),

    # Metrics metadata
    path('metrics/names', MetricsMetadataView.as_view(), name='metrics-names'),
    path('metrics/<str:metric_name>/labels', MetricsMetadataView.as_view(), name='metrics-labels'),
    path('metrics/<str:metric_name>/labels/<str:label_key>/values', MetricsMetadataView.as_view(), name='metrics-label-values'),

    # System operations
    path('ops/<str:operation>', SystemOperationsView.as_view(), name='system-ops'),

    # Statistics
    path('stats/<str:stat_type>', StatsView.as_view(), name='stats'),

    # Alert rules and instances (viewsets)
    path('', include(router.urls)),
]
