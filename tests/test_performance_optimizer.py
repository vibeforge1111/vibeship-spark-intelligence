"""Unit tests for performance optimization utilities."""

import gc
import time
from unittest.mock import MagicMock, patch

import pytest

from lib.performance_optimizer import (
    LRUCache,
    MemoryManager,
    Profiler,
    ResourcePool,
    OptimizationEngine,
    get_memory_manager,
    get_profiler,
    get_optimization_engine,
    optimize_memory,
    profile_function,
    analyze_performance
)


class TestLRUCache:
    """Test LRU Cache functionality."""

    def test_basic_operations(self):
        """Test basic cache operations."""
        cache = LRUCache(max_size=3)

        # Test put and get
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

        # Test LRU behavior
        cache.put("key4", "value4")  # This should evict key1
        assert cache.get("key1") is None
        assert cache.get("key4") == "value4"

    def test_cache_stats(self):
        """Test cache statistics."""
        cache = LRUCache(max_size=2)

        # Initial stats
        stats = cache.get_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0

        # Add some items and test
        cache.put("key1", "value1")
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss

        stats = cache.get_stats()
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_cache_invalidation(self):
        """Test cache invalidation."""
        cache = LRUCache(max_size=3)
        cache.put("key1", "value1")
        cache.put("key2", "value2")

        assert cache.get("key1") == "value1"

        cache.invalidate("key1")
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

    def test_cache_clear(self):
        """Test cache clearing."""
        cache = LRUCache(max_size=3)
        cache.put("key1", "value1")
        cache.put("key2", "value2")

        assert cache.get_stats()["size"] == 2

        cache.clear()
        assert cache.get_stats()["size"] == 0
        assert cache.get_stats()["hits"] == 0
        assert cache.get_stats()["misses"] == 0


class TestMemoryManager:
    """Test Memory Manager functionality."""

    def test_memory_info(self):
        """Test memory information retrieval."""
        mm = get_memory_manager()
        info = mm.get_memory_info()

        # Should have basic memory info
        assert "rss" in info
        assert "vms" in info
        assert "percent" in info

        # Values should be numeric
        assert isinstance(info["rss"], int)
        assert isinstance(info["percent"], float)

    def test_system_memory(self):
        """Test system memory information."""
        mm = get_memory_manager()
        system_info = mm.get_system_memory()

        # Should have system memory info
        assert "total" in system_info
        assert "available" in system_info
        assert "percent" in system_info

    def test_object_tracking(self):
        """Test object tracking functionality."""
        mm = get_memory_manager()
        original_count = mm.get_memory_info()["tracked_objects"]

        # Track some objects
        test_obj1 = {"test": "data1"}
        test_obj2 = {"test": "data2"}

        mm.track_object(test_obj1, "test_category")
        mm.track_object(test_obj2, "test_category")

        new_info = mm.get_memory_info()
        assert new_info["tracked_objects"] >= original_count + 2
        assert new_info["object_counts"]["test_category"] >= 2

    def test_memory_snapshots(self):
        """Test memory snapshot functionality."""
        mm = get_memory_manager()
        mm._memory_snapshots.clear()  # Clear existing snapshots

        # Take snapshots
        snapshot1 = mm.take_memory_snapshot("before")
        time.sleep(0.01)  # Small delay
        snapshot2 = mm.take_memory_snapshot("after")

        snapshots = mm.get_memory_snapshots()
        assert len(snapshots) == 2
        assert snapshots[0]["label"] == "before"
        assert snapshots[1]["label"] == "after"

        # Test limited retrieval
        limited = mm.get_memory_snapshots(limit=1)
        assert len(limited) == 1
        assert limited[0]["label"] == "after"

    def test_memory_optimization_suggestions(self):
        """Test memory optimization suggestions."""
        mm = get_memory_manager()
        suggestions = mm.suggest_memory_optimizations()

        # Should return a list of suggestions
        assert isinstance(suggestions, list)
        assert len(suggestions) > 0

        # Suggestions should be strings
        for suggestion in suggestions:
            assert isinstance(suggestion, str)


class TestProfiler:
    """Test Profiler functionality."""

    def test_function_profiling(self):
        """Test function profiling decorator."""
        profiler = get_profiler()
        profiler._profiles.clear()  # Clear existing profiles

        @profiler.profile_function
        def slow_function():
            time.sleep(0.01)  # 10ms
            return "result"

        result = slow_function()
        assert result == "result"

        # Check that profile was recorded
        profiles = profiler._profiles
        assert len(profiles) == 1

        profile = profiles[0]
        assert profile["name"].endswith("slow_function")
        assert profile["duration"] >= 0.01
        assert profile["call_count"] == 1

    def test_context_manager_profiling(self):
        """Test context manager profiling."""
        profiler = get_profiler()
        profiler._profiles.clear()

        with profiler.profile("test_block") as profile_ctx:
            time.sleep(0.005)  # 5ms
            # Do some work
            result = sum(range(1000))

        profiles = profiler._profiles
        assert len(profiles) == 1

        profile = profiles[0]
        assert profile["name"] == "test_block"
        assert profile["duration"] >= 0.005
        assert "memory_change" in profile

    def test_profile_summary(self):
        """Test profile summary statistics."""
        profiler = get_profiler()
        profiler._profiles.clear()

        # Create some test profiles
        profiler._profiles = [
            {"duration": 0.1, "memory_change": 1000},
            {"duration": 0.2, "memory_change": 2000},
            {"duration": 0.15, "memory_change": 1500}
        ]

        summary = profiler.get_profile_summary()
        assert summary["total_profiles"] == 3
        assert summary["total_duration"] == 0.45
        assert summary["avg_duration"] == 0.15
        assert summary["max_duration"] == 0.2
        assert summary["min_duration"] == 0.1

    def test_top_profiles(self):
        """Test getting top profiles."""
        profiler = get_profiler()
        profiler._profiles.clear()

        # Create test profiles with different durations
        profiler._profiles = [
            {"name": "fast", "duration": 0.01},
            {"name": "medium", "duration": 0.05},
            {"name": "slow", "duration": 0.1}
        ]

        top_profiles = profiler.get_top_profiles(limit=2, metric="duration")
        assert len(top_profiles) == 2
        assert top_profiles[0]["name"] == "slow"
        assert top_profiles[1]["name"] == "medium"


class TestResourcePool:
    """Test Resource Pool functionality."""

    def test_basic_pool_operations(self):
        """Test basic resource pool operations."""
        def create_resource():
            return {"id": time.time(), "data": "test_resource"}

        pool = ResourcePool(create_resource, max_size=3)

        # Acquire resources
        resource1 = pool.acquire()
        resource2 = pool.acquire()

        assert resource1 is not None
        assert resource2 is not None
        assert resource1 != resource2

        # Release resources
        pool.release(resource1)
        pool.release(resource2)

        # Acquire again - should get the same resources
        resource3 = pool.acquire()
        resource4 = pool.acquire()

        assert resource3 in [resource1, resource2]
        assert resource4 in [resource1, resource2]

    def test_pool_stats(self):
        """Test pool statistics."""
        def create_resource():
            return {"id": time.time()}

        pool = ResourcePool(create_resource, max_size=5)

        # Initial stats
        stats = pool.get_stats()
        assert stats["available"] == 0
        assert stats["in_use"] == 0
        assert stats["max_size"] == 5
        assert stats["utilization"] == 0

        # Acquire some resources
        resources = [pool.acquire() for _ in range(3)]
        stats = pool.get_stats()
        assert stats["in_use"] == 3
        assert stats["utilization"] == 0.6

        # Release resources
        for resource in resources:
            pool.release(resource)
        stats = pool.get_stats()
        assert stats["available"] == 3
        assert stats["in_use"] == 0
        assert stats["utilization"] == 0

    def test_context_manager(self):
        """Test resource pool context manager."""
        def create_resource():
            return {"id": time.time(), "acquired": True}

        pool = ResourcePool(create_resource, max_size=2)

        with pool.get_resource() as resource:
            assert resource["acquired"] is True
            assert len(pool._in_use) == 1

        # Resource should be released
        assert len(pool._in_use) == 0
        assert len(pool._pool) == 1

    def test_pool_exhaustion(self):
        """Test pool exhaustion behavior."""
        def create_resource():
            return {"id": time.time()}

        pool = ResourcePool(create_resource, max_size=2)

        # Acquire all available resources
        resources = [pool.acquire() for _ in range(2)]

        # Next acquisition should raise an exception
        with pytest.raises(RuntimeError, match="Resource pool exhausted"):
            pool.acquire()


class TestOptimizationEngine:
    """Test Optimization Engine functionality."""

    def test_performance_analysis(self):
        """Test performance analysis."""
        engine = get_optimization_engine()

        # Mock memory manager for consistent results
        with patch('lib.performance_optimizer.get_memory_manager') as mock_mm:
            mock_mm_instance = MagicMock()
            mock_mm_instance.get_memory_info.return_value = {"percent": 75}
            mock_mm_instance.get_system_memory.return_value = {"percent": 80}
            mock_mm.return_value = mock_mm_instance

            analysis = engine.analyze_performance()

        assert "timestamp" in analysis
        assert "memory_analysis" in analysis
        assert "cpu_analysis" in analysis
        assert "recommendations" in analysis

        # Check memory analysis
        memory_analysis = analysis["memory_analysis"]
        assert memory_analysis["process_memory_percent"] == 75
        assert memory_analysis["system_memory_percent"] == 80

    def test_memory_recommendations(self):
        """Test memory optimization recommendations."""
        engine = get_optimization_engine()

        # Test high memory usage recommendation
        with patch('lib.performance_optimizer.get_memory_manager') as mock_mm:
            mock_mm_instance = MagicMock()
            mock_mm_instance.get_memory_info.return_value = {"percent": 85}
            mock_mm_instance.get_system_memory.return_value = {"percent": 70}
            mock_mm.return_value = mock_mm_instance

            analysis = engine.analyze_performance()

        recommendations = analysis["recommendations"]
        assert len(recommendations) > 0

        # Should have memory-related recommendations
        memory_recommendations = [
            r for r in recommendations if "memory" in r.lower()]
        assert len(memory_recommendations) > 0


def test_convenience_functions():
    """Test convenience functions."""
    # Test optimize_memory
    memory_info = optimize_memory()
    assert "rss" in memory_info
    assert "percent" in memory_info

    # Test analyze_performance
    analysis = analyze_performance()
    assert isinstance(analysis, dict)
    assert "timestamp" in analysis


def test_singleton_instances():
    """Test that singleton instances work correctly."""
    mm1 = get_memory_manager()
    mm2 = get_memory_manager()
    assert mm1 is mm2  # Should be the same instance

    profiler1 = get_profiler()
    profiler2 = get_profiler()
    assert profiler1 is profiler2  # Should be the same instance

    engine1 = get_optimization_engine()
    engine2 = get_optimization_engine()
    assert engine1 is engine2  # Should be the same instance


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
