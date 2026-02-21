"""Advanced monitoring and observability utilities for Spark Intelligence.

This module provides enhanced logging, performance metrics collection,
and system health monitoring capabilities that integrate seamlessly
with Spark's existing diagnostic infrastructure.

Key features:
- Structured logging with context enrichment
- Performance metrics collection and aggregation
- System resource monitoring
- Health check utilities
- Alerting mechanisms for anomaly detection
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import psutil

# Configure logger
logger = logging.getLogger(__name__)

# Constants
DEFAULT_MONITORING_INTERVAL = 30  # seconds
METRICS_BUFFER_SIZE = 1000
HEALTH_CHECK_TIMEOUT = 5.0
LOG_LEVEL = os.environ.get("SPARK_MONITORING_LOG_LEVEL", "INFO")

# Performance metrics storage


class MetricsStore:
    """Thread-safe storage for performance metrics and system statistics."""

    def __init__(self):
        self._metrics: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=METRICS_BUFFER_SIZE))
        self._lock = Lock()
        self._system_stats = {}
        self._last_update = 0

    def record_metric(self, name: str, value: Union[int, float], tags: Optional[Dict[str, str]] = None):
        """Record a metric with optional tags."""
        timestamp = time.time()
        entry = {
            "timestamp": timestamp,
            "value": value,
            "tags": tags or {}
        }

        with self._lock:
            self._metrics[name].append(entry)

    def get_metrics(self, name: str, limit: Optional[int] = None) -> List[Dict]:
        """Retrieve metrics for a specific name."""
        with self._lock:
            metrics = list(self._metrics[name])

        if limit:
            return metrics[-limit:]
        return metrics

    def get_all_metrics_summary(self) -> Dict[str, Any]:
        """Get summary statistics for all metrics."""
        summary = {}
        with self._lock:
            for name, entries in self._metrics.items():
                if entries:
                    values = [entry["value"] for entry in entries]
                    summary[name] = {
                        "count": len(values),
                        "min": min(values),
                        "max": max(values),
                        "avg": sum(values) / len(values),
                        "latest": values[-1] if values else None
                    }
        return summary

    def update_system_stats(self):
        """Update system-level statistics."""
        try:
            process = psutil.Process()
            self._system_stats = {
                "timestamp": time.time(),
                "cpu_percent": process.cpu_percent(),
                "memory_rss": process.memory_info().rss,
                "memory_percent": process.memory_percent(),
                "num_threads": process.num_threads(),
                "open_files": len(process.open_files()) if hasattr(process, 'open_files') else 0,
                "system_cpu_percent": psutil.cpu_percent(),
                "system_memory_percent": psutil.virtual_memory().percent,
                "disk_usage_percent": psutil.disk_usage('/').percent if os.name != 'nt' else psutil.disk_usage('C:').percent
            }
            self._last_update = time.time()
        except Exception as e:
            logger.warning(f"Failed to update system stats: {e}")

    def get_system_stats(self) -> Dict[str, Any]:
        """Get current system statistics."""
        if time.time() - self._last_update > 60:  # Update if older than 1 minute
            self.update_system_stats()
        return self._system_stats.copy()


# Global metrics store instance
metrics_store = MetricsStore()


@dataclass
class PerformanceContext:
    """Context for tracking performance of operations."""
    operation_name: str
    start_time: float = field(default_factory=time.time)
    tags: Dict[str, str] = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None

    def finish(self, success: bool = True, error: Optional[str] = None):
        """Mark operation as complete and record metrics."""
        duration = time.time() - self.start_time
        self.success = success
        self.error = error

        # Record duration metric
        metrics_store.record_metric(
            f"operation.{self.operation_name}.duration",
            duration,
            {**self.tags, "success": str(success)}
        )

        # Record success/failure
        metrics_store.record_metric(
            f"operation.{self.operation_name}.success",
            1 if success else 0,
            self.tags
        )

        if not success and error:
            metrics_store.record_metric(
                f"operation.{self.operation_name}.errors",
                1,
                {**self.tags, "error": error}
            )


class StructuredLogger:
    """Enhanced logger with structured logging capabilities."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.context: Dict[str, Any] = {}

    def with_context(self, **kwargs) -> 'StructuredLogger':
        """Add context to all subsequent log messages."""
        new_logger = StructuredLogger(self.logger.name)
        new_logger.context = {**self.context, **kwargs}
        return new_logger

    def _log(self, level: int, message: str, **kwargs):
        """Internal logging method with context enrichment."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": logging.getLevelName(level),
            "message": message,
            "context": self.context,
            **kwargs
        }

        # Add system context if available
        system_stats = metrics_store.get_system_stats()
        if system_stats:
            log_data["system_stats"] = {
                "cpu_percent": system_stats.get("cpu_percent"),
                "memory_rss": system_stats.get("memory_rss"),
                "memory_percent": system_stats.get("memory_percent")
            }

        self.logger.log(level, json.dumps(log_data))

    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)


def performance_monitor(operation_name: str, **tags):
    """Decorator for monitoring function performance."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            context = PerformanceContext(operation_name, tags=tags)
            try:
                result = func(*args, **kwargs)
                context.finish(success=True)
                return result
            except Exception as e:
                context.finish(success=False, error=str(e))
                raise
        return wrapper
    return decorator


@contextmanager
def performance_context(operation_name: str, **tags):
    """Context manager for performance monitoring."""
    context = PerformanceContext(operation_name, tags=tags)
    try:
        yield context
    except Exception as e:
        context.finish(success=False, error=str(e))
        raise
    else:
        context.finish(success=True)


class HealthChecker:
    """System health checking utilities."""

    def __init__(self):
        self.checks: Dict[str, Callable[[], Tuple[bool, str]]] = {}

    def register_check(self, name: str, check_func: Callable[[], Tuple[bool, str]]):
        """Register a health check function."""
        self.checks[name] = check_func

    def run_checks(self, timeout: float = HEALTH_CHECK_TIMEOUT) -> Dict[str, Dict[str, Any]]:
        """Run all registered health checks."""
        results = {}

        for name, check_func in self.checks.items():
            try:
                start_time = time.time()
                success, message = check_func()
                duration = time.time() - start_time

                results[name] = {
                    "success": success,
                    "message": message,
                    "duration": duration,
                    "timestamp": datetime.utcnow().isoformat()
                }

                # Record health check metrics
                metrics_store.record_metric(
                    f"health_check.{name}.duration",
                    duration,
                    {"success": str(success)}
                )

            except Exception as e:
                results[name] = {
                    "success": False,
                    "message": f"Check failed with exception: {e}",
                    "duration": time.time() - start_time,
                    "timestamp": datetime.utcnow().isoformat()
                }

        return results

    def get_health_status(self) -> str:
        """Get overall health status."""
        results = self.run_checks()
        failed_checks = [name for name,
                         result in results.items() if not result["success"]]

        if not failed_checks:
            return "healthy"
        elif len(failed_checks) <= len(results) // 2:
            return "degraded"
        else:
            return "unhealthy"


# Global health checker instance
health_checker = HealthChecker()


class AlertManager:
    """Simple alert management for system anomalies."""

    def __init__(self):
        self.alerts: List[Dict[str, Any]] = []
        self.alert_thresholds: Dict[str, float] = {}
        self._lock = Lock()

    def set_threshold(self, metric_name: str, threshold: float, comparison: str = "gt"):
        """Set alert threshold for a metric."""
        self.alert_thresholds[metric_name] = {
            "threshold": threshold,
            "comparison": comparison  # 'gt', 'lt', 'eq'
        }

    def check_alerts(self) -> List[Dict[str, Any]]:
        """Check for triggered alerts."""
        triggered_alerts = []
        summary = metrics_store.get_all_metrics_summary()

        for metric_name, threshold_config in self.alert_thresholds.items():
            if metric_name in summary:
                current_value = summary[metric_name].get("latest")
                if current_value is not None:
                    threshold = threshold_config["threshold"]
                    comparison = threshold_config["comparison"]

                    should_alert = False
                    if comparison == "gt" and current_value > threshold:
                        should_alert = True
                    elif comparison == "lt" and current_value < threshold:
                        should_alert = True
                    elif comparison == "eq" and current_value == threshold:
                        should_alert = True

                    if should_alert:
                        alert = {
                            "metric": metric_name,
                            "current_value": current_value,
                            "threshold": threshold,
                            "comparison": comparison,
                            "timestamp": datetime.utcnow().isoformat(),
                            "severity": self._calculate_severity(current_value, threshold, comparison)
                        }
                        triggered_alerts.append(alert)

        with self._lock:
            self.alerts.extend(triggered_alerts)

        return triggered_alerts

    def _calculate_severity(self, current: float, threshold: float, comparison: str) -> str:
        """Calculate alert severity based on deviation from threshold."""
        if comparison == "gt":
            deviation = current / threshold if threshold > 0 else float('inf')
        elif comparison == "lt":
            deviation = threshold / current if current > 0 else float('inf')
        else:
            deviation = abs(current - threshold)

        if deviation >= 2.0:
            return "critical"
        elif deviation >= 1.5:
            return "high"
        elif deviation >= 1.2:
            return "medium"
        else:
            return "low"

    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        with self._lock:
            return self.alerts[-limit:] if self.alerts else []


# Global alert manager instance
alert_manager = AlertManager()


class MonitoringDaemon:
    """Background daemon for continuous monitoring."""

    def __init__(self, interval: int = DEFAULT_MONITORING_INTERVAL):
        self.interval = interval
        self._running = False
        self._thread: Optional[Thread] = None
        self._lock = Lock()

    def start(self):
        """Start the monitoring daemon."""
        with self._lock:
            if self._running:
                return

            self._running = True
            self._thread = Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()
            logger.info("Monitoring daemon started")

    def stop(self):
        """Stop the monitoring daemon."""
        with self._lock:
            self._running = False
            if self._thread:
                self._thread.join(timeout=5)
            logger.info("Monitoring daemon stopped")

    def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                # Update system stats
                metrics_store.update_system_stats()

                # Record system metrics
                system_stats = metrics_store.get_system_stats()
                for key, value in system_stats.items():
                    if isinstance(value, (int, float)) and key != "timestamp":
                        metrics_store.record_metric(f"system.{key}", value)

                # Check alerts
                alert_manager.check_alerts()

                time.sleep(self.interval)

            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                time.sleep(5)  # Brief pause before retry


# Global monitoring daemon instance
monitoring_daemon = MonitoringDaemon()

# Initialize monitoring when module is imported


def initialize_monitoring():
    """Initialize monitoring components."""
    try:
        # Register basic health checks
        health_checker.register_check("system_resources", lambda: (
            metrics_store.get_system_stats().get("memory_percent", 0) < 90 and
            metrics_store.get_system_stats().get("cpu_percent", 0) < 95,
            "System resources within normal limits"
        ))

        health_checker.register_check("disk_space", lambda: (
            metrics_store.get_system_stats().get("disk_usage_percent", 0) < 85,
            "Disk space usage acceptable"
        ))

        # Set up basic alert thresholds
        alert_manager.set_threshold("system.memory_percent", 80.0, "gt")
        alert_manager.set_threshold("system.cpu_percent", 85.0, "gt")
        alert_manager.set_threshold("system.disk_usage_percent", 80.0, "gt")

        # Start monitoring daemon
        monitoring_daemon.start()

        logger.info("Advanced monitoring initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize monitoring: {e}")


# Export main interfaces
__all__ = [
    "StructuredLogger",
    "performance_monitor",
    "performance_context",
    "metrics_store",
    "health_checker",
    "alert_manager",
    "monitoring_daemon",
    "initialize_monitoring"
]
