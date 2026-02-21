"""Unit tests for advanced monitoring functionality."""

import json
import logging
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from lib.advanced_monitoring import (
    StructuredLogger,
    performance_monitor,
    performance_context,
    metrics_store,
    health_checker,
    alert_manager,
    monitoring_daemon,
    initialize_monitoring
)


class TestMetricsStore:
    """Test the MetricsStore functionality."""

    def test_record_and_retrieve_metrics(self):
        """Test recording and retrieving metrics."""
        metrics_store.record_metric("test.metric", 42.5, {"source": "test"})
        metrics_store.record_metric("test.metric", 43.2, {"source": "test"})

        metrics = metrics_store.get_metrics("test.metric", limit=10)
        assert len(metrics) == 2
        assert metrics[0]["value"] == 42.5
        assert metrics[1]["value"] == 43.2
        assert metrics[0]["tags"]["source"] == "test"

    def test_metrics_summary(self):
        """Test metrics summary functionality."""
        # Clear existing metrics
        metrics_store._metrics.clear()

        # Add some test metrics
        metrics_store.record_metric("latency", 100)
        metrics_store.record_metric("latency", 150)
        metrics_store.record_metric("latency", 200)

        summary = metrics_store.get_all_metrics_summary()
        assert "latency" in summary
        assert summary["latency"]["count"] == 3
        assert summary["latency"]["min"] == 100
        assert summary["latency"]["max"] == 200
        assert summary["latency"]["avg"] == 150

    def test_metrics_buffer_limit(self):
        """Test that metrics buffer respects size limits."""
        metrics_store._metrics.clear()

        # Add more metrics than buffer size
        buffer_size = 1000  # from the code
        for i in range(buffer_size + 10):
            metrics_store.record_metric("test_buffer", i)

        metrics = metrics_store.get_metrics("test_buffer")
        assert len(metrics) <= buffer_size

    def test_system_stats_update(self):
        """Test system statistics updating."""
        # This will likely pass on most systems but skip on others
        try:
            old_stats = metrics_store.get_system_stats()
            # Force update
            metrics_store._last_update = 0
            new_stats = metrics_store.get_system_stats()

            # Should have basic system stats
            assert "cpu_percent" in new_stats
            assert "memory_rss" in new_stats
            assert "timestamp" in new_stats
        except Exception:
            # psutil might not be available or have permission issues
            pytest.skip("System stats not available")


class TestStructuredLogger:
    """Test the StructuredLogger functionality."""

    def test_basic_logging(self, caplog):
        """Test basic structured logging."""
        logger = StructuredLogger("test.logger")

        with caplog.at_level(logging.INFO):
            logger.info("Test message", custom_field="test_value")

        assert len(caplog.records) == 1
        # The log record should contain JSON
        log_output = caplog.records[0].getMessage()
        assert "Test message" in log_output
        assert "test_value" in log_output

    def test_context_enrichment(self, caplog):
        """Test context enrichment in logs."""
        logger = StructuredLogger("test.logger").with_context(
            user_id="123", session_id="abc")

        with caplog.at_level(logging.INFO):
            logger.info("Context test")

        log_output = caplog.records[0].getMessage()
        assert "user_id" in log_output
        assert "123" in log_output
        assert "session_id" in log_output
        assert "abc" in log_output

    def test_nested_context(self, caplog):
        """Test nested context inheritance."""
        base_logger = StructuredLogger(
            "test.logger").with_context(base="value")
        child_logger = base_logger.with_context(child="nested")

        with caplog.at_level(logging.INFO):
            child_logger.info("Nested context test")

        log_output = caplog.records[0].getMessage()
        assert "base" in log_output
        assert "value" in log_output
        assert "child" in log_output
        assert "nested" in log_output


class TestPerformanceMonitoring:
    """Test performance monitoring decorators and context managers."""

    def test_performance_monitor_decorator(self):
        """Test the performance monitor decorator."""
        @performance_monitor("test_operation")
        def slow_function():
            time.sleep(0.01)  # 10ms
            return "result"

        result = slow_function()
        assert result == "result"

        # Check that metrics were recorded
        metrics = metrics_store.get_metrics(
            "operation.test_operation.duration")
        assert len(metrics) > 0
        assert metrics[-1]["value"] >= 0.01  # Should be at least 10ms

    def test_performance_monitor_error_handling(self):
        """Test performance monitoring with exceptions."""
        @performance_monitor("failing_operation")
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            failing_function()

        # Check that error metrics were recorded
        success_metrics = metrics_store.get_metrics(
            "operation.failing_operation.success")
        error_metrics = metrics_store.get_metrics(
            "operation.failing_operation.errors")

        assert len(success_metrics) > 0
        assert success_metrics[-1]["value"] == 0  # Should be failure
        assert len(error_metrics) > 0

    def test_performance_context_manager(self):
        """Test performance context manager."""
        with performance_context("manual_operation") as ctx:
            time.sleep(0.005)  # 5ms
            # Simulate some work
            pass

        # Check that metrics were recorded
        metrics = metrics_store.get_metrics(
            "operation.manual_operation.duration")
        assert len(metrics) > 0
        assert metrics[-1]["value"] >= 0.005

    def test_performance_context_with_error(self):
        """Test performance context with error handling."""
        with pytest.raises(ValueError):
            with performance_context("error_operation") as ctx:
                raise ValueError("Context error")

        # Check that error was recorded
        success_metrics = metrics_store.get_metrics(
            "operation.error_operation.success")
        assert len(success_metrics) > 0
        assert success_metrics[-1]["value"] == 0


class TestHealthChecker:
    """Test health checking functionality."""

    def test_register_and_run_check(self):
        """Test registering and running health checks."""
        def always_healthy():
            return True, "All good"

        def always_unhealthy():
            return False, "Something wrong"

        health_checker.checks.clear()  # Clear existing checks
        health_checker.register_check("healthy_check", always_healthy)
        health_checker.register_check("unhealthy_check", always_unhealthy)

        results = health_checker.run_checks()

        assert "healthy_check" in results
        assert "unhealthy_check" in results
        assert results["healthy_check"]["success"] is True
        assert results["unhealthy_check"]["success"] is False
        assert results["healthy_check"]["message"] == "All good"
        assert results["unhealthy_check"]["message"] == "Something wrong"

    def test_health_status_calculation(self):
        """Test health status calculation."""
        health_checker.checks.clear()

        # All healthy
        health_checker.register_check("check1", lambda: (True, ""))
        health_checker.register_check("check2", lambda: (True, ""))
        assert health_checker.get_health_status() == "healthy"

        # Partially degraded
        health_checker.checks.clear()
        health_checker.register_check("check1", lambda: (False, ""))
        health_checker.register_check("check2", lambda: (True, ""))
        health_checker.register_check("check3", lambda: (True, ""))
        assert health_checker.get_health_status() == "degraded"

        # Mostly unhealthy
        health_checker.checks.clear()
        health_checker.register_check("check1", lambda: (False, ""))
        health_checker.register_check("check2", lambda: (False, ""))
        health_checker.register_check("check3", lambda: (True, ""))
        assert health_checker.get_health_status() == "unhealthy"


class TestAlertManager:
    """Test alert management functionality."""

    def test_set_and_check_thresholds(self):
        """Test setting thresholds and checking alerts."""
        alert_manager.alert_thresholds.clear()

        # Set a threshold
        alert_manager.set_threshold("test_metric", 100.0, "gt")

        # Record a metric that should trigger alert
        metrics_store.record_metric("test_metric", 150.0)

        # Check alerts
        alerts = alert_manager.check_alerts()

        assert len(alerts) > 0
        assert alerts[0]["metric"] == "test_metric"
        assert alerts[0]["current_value"] == 150.0
        assert alerts[0]["threshold"] == 100.0
        assert alerts[0]["comparison"] == "gt"

    def test_alert_severity_calculation(self):
        """Test alert severity calculation."""
        # Test different severity levels
        assert alert_manager._calculate_severity(200, 100, "gt") == "critical"
        assert alert_manager._calculate_severity(150, 100, "gt") == "high"
        assert alert_manager._calculate_severity(120, 100, "gt") == "medium"
        assert alert_manager._calculate_severity(110, 100, "gt") == "low"

    def test_get_recent_alerts(self):
        """Test retrieving recent alerts."""
        alert_manager.alerts.clear()

        # Add some alerts
        alert_manager.alerts.extend([
            {"metric": "test1", "timestamp": "2023-01-01T00:00:00"},
            {"metric": "test2", "timestamp": "2023-01-01T00:01:00"}
        ])

        recent = alert_manager.get_recent_alerts(limit=1)
        assert len(recent) == 1
        assert recent[0]["metric"] == "test2"  # Most recent


class TestMonitoringDaemon:
    """Test monitoring daemon functionality."""

    def test_daemon_lifecycle(self):
        """Test daemon start and stop lifecycle."""
        daemon = monitoring_daemon

        # Start daemon
        daemon.start()
        assert daemon._running is True
        assert daemon._thread is not None
        assert daemon._thread.is_alive()

        # Stop daemon
        daemon.stop()
        assert daemon._running is False

    def test_daemon_monitoring_loop(self):
        """Test that daemon monitoring loop records system metrics."""
        # Clear existing metrics
        metrics_store._metrics.clear()

        # Run a brief monitoring cycle
        daemon = monitoring_daemon
        daemon.interval = 1  # Short interval for testing

        daemon.start()
        time.sleep(2)  # Let it run for a bit
        daemon.stop()

        # Check that system metrics were recorded
        system_metrics = metrics_store.get_metrics("system.cpu_percent")
        assert len(system_metrics) > 0


def test_initialize_monitoring():
    """Test monitoring initialization."""
    # This should not raise exceptions
    initialize_monitoring()

    # Check that basic components are initialized
    assert len(health_checker.checks) > 0
    assert len(alert_manager.alert_thresholds) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
