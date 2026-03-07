"""Performance optimization utilities for Spark Intelligence.

This module provides tools for memory management, resource cleanup,
performance profiling, and optimization recommendations.

Key features:
- Memory usage monitoring and optimization
- Resource cleanup utilities
- Performance profiling decorators
- Cache management utilities
- Optimization recommendations engine
"""

from __future__ import annotations

import gc
import logging
import os
import sys
import time
import weakref
from collections import defaultdict, OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from weakref import WeakValueDictionary

import psutil

# Configure logger
logger = logging.getLogger(__name__)

# Constants
DEFAULT_CACHE_SIZE = 1000
DEFAULT_CLEANUP_INTERVAL = 300  # 5 minutes
MEMORY_PRESSURE_THRESHOLD = 0.8  # 80% memory usage
DEFAULT_PROFILE_DEPTH = 10


class LRUCache:
    """Least Recently Used (LRU) cache implementation."""

    def __init__(self, max_size: int = DEFAULT_CACHE_SIZE):
        self.max_size = max_size
        self.cache: OrderedDict = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any) -> Optional[Any]:
        """Get item from cache, moving it to most recently used."""
        if key in self.cache:
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            self.hits += 1
            return self.cache[key]
        self.misses += 1
        return None

    def put(self, key: Any, value: Any):
        """Put item in cache, removing oldest if necessary."""
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value

        if len(self.cache) > self.max_size:
            # Remove least recently used item
            self.cache.popitem(last=False)

    def invalidate(self, key: Any):
        """Remove specific item from cache."""
        self.cache.pop(key, None)

    def clear(self):
        """Clear entire cache."""
        self.cache.clear()
        self.hits = 0
        self.misses = 0

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self.hits + self.misses
        hit_rate = self.hits / total_requests if total_requests > 0 else 0

        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate,
            "total_requests": total_requests
        }


class MemoryManager:
    """Memory management and optimization utilities."""

    def __init__(self):
        self._process = psutil.Process()
        self._tracked_objects: WeakValueDictionary = WeakValueDictionary()
        self._object_counts: Dict[str, int] = defaultdict(int)
        self._memory_snapshots: List[Dict[str, Any]] = []

    def track_object(self, obj: Any, category: str = "unknown"):
        """Track an object for memory monitoring."""
        obj_id = id(obj)
        self._tracked_objects[obj_id] = obj
        self._object_counts[category] += 1

    def get_memory_info(self) -> Dict[str, Any]:
        """Get detailed memory information."""
        try:
            memory_info = self._process.memory_info()
            return {
                "rss": memory_info.rss,  # Resident Set Size
                "vms": memory_info.vms,  # Virtual Memory Size
                "percent": self._process.memory_percent(),
                "tracked_objects": len(self._tracked_objects),
                "object_counts": dict(self._object_counts)
            }
        except Exception as e:
            logger.warning(f"Failed to get memory info: {e}")
            return {"error": str(e)}

    def get_system_memory(self) -> Dict[str, Any]:
        """Get system memory information."""
        try:
            virtual_memory = psutil.virtual_memory()
            return {
                "total": virtual_memory.total,
                "available": virtual_memory.available,
                "percent": virtual_memory.percent,
                "used": virtual_memory.used,
                "free": virtual_memory.free,
                "under_pressure": virtual_memory.percent > MEMORY_PRESSURE_THRESHOLD * 100
            }
        except Exception as e:
            logger.warning(f"Failed to get system memory: {e}")
            return {"error": str(e)}

    def take_memory_snapshot(self, label: str = "snapshot"):
        """Take a snapshot of current memory state."""
        snapshot = {
            "timestamp": time.time(),
            "label": label,
            "process_memory": self.get_memory_info(),
            "system_memory": self.get_system_memory(),
            "python_gc": {
                "counts": gc.get_count(),
                "thresholds": gc.get_threshold()
            }
        }
        self._memory_snapshots.append(snapshot)
        return snapshot

    def get_memory_snapshots(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get memory snapshots."""
        if limit:
            return self._memory_snapshots[-limit:]
        return self._memory_snapshots

    def suggest_memory_optimizations(self) -> List[str]:
        """Suggest memory optimization strategies based on current state."""
        suggestions = []
        process_info = self.get_memory_info()
        system_info = self.get_system_memory()

        # High memory usage suggestions
        if process_info.get("percent", 0) > 75:
            suggestions.append(
                "High process memory usage detected - consider optimizing data structures")
            suggestions.append("Run garbage collection with optimize_memory()")

        if system_info.get("percent", 0) > 80:
            suggestions.append(
                "System memory pressure high - close unused applications")
            suggestions.append(
                "Consider increasing virtual memory or adding more RAM")

        # Object tracking suggestions
        large_categories = {k: v for k,
                            v in self._object_counts.items() if v > 1000}
        if large_categories:
            for category, count in large_categories.items():
                suggestions.append(
                    f"Large number of {category} objects ({count}) - consider object pooling")

        # Garbage collection suggestions
        gc_counts = gc.get_count()
        if any(count > 1000 for count in gc_counts):
            suggestions.append(
                "High garbage collection counts - optimize object lifecycle")

        if not suggestions:
            suggestions.append("Memory usage appears normal")

        return suggestions

    def cleanup_large_objects(self, size_threshold: int = 1024 * 1024):  # 1MB
        """Identify and suggest cleanup of large objects."""
        large_objects = []
        for obj_id, obj in list(self._tracked_objects.items()):
            try:
                # This is a simplified check - in reality, you'd want to use
                # sys.getsizeof() with more care
                if hasattr(obj, '__sizeof__'):
                    size = sys.getsizeof(obj)
                    if size > size_threshold:
                        large_objects.append(
                            (obj_id, type(obj).__name__, size))
            except Exception:
                pass  # Some objects can't be sized safely

        return large_objects


class Profiler:
    """Performance profiling utilities."""

    def __init__(self):
        self._profiles: List[Dict[str, Any]] = []
        self._active_profiles: Dict[str, 'FunctionProfile'] = {}

    @contextmanager
    def profile(self, name: str, category: str = "general"):
        """Profile a block of code."""
        start_time = time.time()
        start_memory = 0
        try:
            mm = get_memory_manager()
            start_memory = mm.get_memory_info().get("rss", 0)
        except Exception:
            pass

        profile = FunctionProfile(name, category, start_time, start_memory)
        self._active_profiles[name] = profile

        try:
            yield profile
        finally:
            profile.end_time = time.time()
            try:
                end_memory = mm.get_memory_info().get("rss", 0)
                profile.end_memory = end_memory
            except Exception:
                pass
            profile.calculate_metrics()

            self._profiles.append(profile.to_dict())
            self._active_profiles.pop(name, None)

    def profile_function(self, func: Callable, category: str = "function"):
        """Decorator to profile function calls."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            func_name = f"{func.__module__}.{func.__name__}"
            with self.profile(func_name, category):
                return func(*args, **kwargs)
        return wrapper

    def get_top_profiles(self, limit: int = 10, metric: str = "duration") -> List[Dict[str, Any]]:
        """Get top performing/hottest functions."""
        sorted_profiles = sorted(
            self._profiles,
            key=lambda x: x.get(metric, 0),
            reverse=True
        )
        return sorted_profiles[:limit]

    def get_profile_summary(self) -> Dict[str, Any]:
        """Get summary statistics of all profiles."""
        if not self._profiles:
            return {}

        durations = [p.get("duration", 0) for p in self._profiles]
        memory_changes = [p.get("memory_change", 0) for p in self._profiles]

        return {
            "total_profiles": len(self._profiles),
            "total_duration": sum(durations),
            "avg_duration": sum(durations) / len(durations),
            "max_duration": max(durations),
            "min_duration": min(durations),
            "total_memory_change": sum(memory_changes),
            "avg_memory_change": sum(memory_changes) / len(memory_changes) if memory_changes else 0
        }


@dataclass
class FunctionProfile:
    """Profile data for a function or code block."""
    name: str
    category: str
    start_time: float
    start_memory: int
    end_time: float = 0
    end_memory: int = 0
    duration: float = 0
    memory_change: int = 0
    call_count: int = 1

    def calculate_metrics(self):
        """Calculate derived metrics."""
        self.duration = self.end_time - self.start_time
        self.memory_change = self.end_memory - self.start_memory

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "category": self.category,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "start_memory": self.start_memory,
            "end_memory": self.end_memory,
            "memory_change": self.memory_change,
            "call_count": self.call_count
        }


class ResourcePool:
    """Generic resource pool for managing expensive resources."""

    def __init__(self, factory: Callable, max_size: int = 10):
        self.factory = factory
        self.max_size = max_size
        self._pool: List[Any] = []
        self._in_use: Set[Any] = set()
        self._created_count = 0

    def acquire(self) -> Any:
        """Acquire a resource from the pool."""
        if self._pool:
            resource = self._pool.pop()
        else:
            if len(self._in_use) < self.max_size:
                resource = self.factory()
                self._created_count += 1
            else:
                raise RuntimeError("Resource pool exhausted")

        self._in_use.add(resource)
        return resource

    def release(self, resource: Any):
        """Release a resource back to the pool."""
        if resource in self._in_use:
            self._in_use.remove(resource)
            if len(self._pool) < self.max_size:
                self._pool.append(resource)
            # Otherwise, let it be garbage collected

    @contextmanager
    def get_resource(self):
        """Context manager for automatic resource management."""
        resource = self.acquire()
        try:
            yield resource
        finally:
            self.release(resource)

    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        return {
            "available": len(self._pool),
            "in_use": len(self._in_use),
            "max_size": self.max_size,
            "created_count": self._created_count,
            "utilization": len(self._in_use) / self.max_size if self.max_size > 0 else 0
        }


class OptimizationEngine:
    """Engine for generating optimization recommendations."""

    def __init__(self):
        self._memory_manager = get_memory_manager()
        self._profiler = get_profiler()

    def analyze_performance(self) -> Dict[str, Any]:
        """Analyze overall performance and generate recommendations."""
        analysis = {
            "timestamp": time.time(),
            "memory_analysis": self._analyze_memory(),
            "cpu_analysis": self._analyze_cpu(),
            "io_analysis": self._analyze_io(),
            "recommendations": []
        }

        # Generate recommendations based on analysis
        recommendations = []

        # Memory recommendations
        memory_issues = analysis["memory_analysis"].get("issues", [])
        for issue in memory_issues:
            recommendations.extend(
                self._generate_memory_recommendations(issue))

        # CPU recommendations
        cpu_issues = analysis["cpu_analysis"].get("issues", [])
        for issue in cpu_issues:
            recommendations.extend(self._generate_cpu_recommendations(issue))

        # IO recommendations
        io_issues = analysis["io_analysis"].get("issues", [])
        for issue in io_issues:
            recommendations.extend(self._generate_io_recommendations(issue))

        analysis["recommendations"] = recommendations
        return analysis

    def _analyze_memory(self) -> Dict[str, Any]:
        """Analyze memory usage patterns."""
        memory_info = self._memory_manager.get_memory_info()
        system_info = self._memory_manager.get_system_memory()

        issues = []
        if memory_info.get("percent", 0) > 80:
            issues.append("high_memory_usage")
        if system_info.get("percent", 0) > 85:
            issues.append("system_memory_pressure")

        return {
            "process_memory_percent": memory_info.get("percent", 0),
            "system_memory_percent": system_info.get("percent", 0),
            "tracked_objects": memory_info.get("tracked_objects", 0),
            "issues": issues
        }

    def _analyze_cpu(self) -> Dict[str, Any]:
        """Analyze CPU usage patterns."""
        try:
            cpu_percent = psutil.Process().cpu_percent()
            issues = []
            if cpu_percent > 80:
                issues.append("high_cpu_usage")
            return {"cpu_percent": cpu_percent, "issues": issues}
        except Exception:
            return {"cpu_percent": 0, "issues": ["cpu_monitoring_failed"]}

    def _analyze_io(self) -> Dict[str, Any]:
        """Analyze I/O patterns."""
        # Simplified IO analysis
        return {"issues": ["io_analysis_not_implemented"]}

    def _generate_memory_recommendations(self, issue: str) -> List[str]:
        """Generate recommendations for memory issues."""
        recommendations = {
            "high_memory_usage": [
                "Implement object pooling for frequently created objects",
                "Use __slots__ for classes with many instances",
                "Consider using weak references for caches",
                "Profile memory usage with memory_profiler"
            ],
            "system_memory_pressure": [
                "Close unnecessary applications",
                "Increase swap space if possible",
                "Consider distributed processing for large datasets"
            ]
        }
        return recommendations.get(issue, [f"Address memory issue: {issue}"])

    def _generate_cpu_recommendations(self, issue: str) -> List[str]:
        """Generate recommendations for CPU issues."""
        recommendations = {
            "high_cpu_usage": [
                "Profile CPU hotspots with cProfile",
                "Consider algorithmic optimizations",
                "Implement caching for expensive computations",
                "Use multiprocessing for CPU-bound tasks"
            ],
            "cpu_monitoring_failed": [
                "Install psutil for better CPU monitoring",
                "Check process permissions"
            ]
        }
        return recommendations.get(issue, [f"Address CPU issue: {issue}"])

    def _generate_io_recommendations(self, issue: str) -> List[str]:
        """Generate recommendations for I/O issues."""
        return [f"Address I/O issue: {issue}"]


# Global instances
_memory_manager: Optional[MemoryManager] = None
_profiler: Optional[Profiler] = None
_optimization_engine: Optional[OptimizationEngine] = None


def get_memory_manager() -> MemoryManager:
    """Get singleton memory manager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


def get_profiler() -> Profiler:
    """Get singleton profiler instance."""
    global _profiler
    if _profiler is None:
        _profiler = Profiler()
    return _profiler


def get_optimization_engine() -> OptimizationEngine:
    """Get singleton optimization engine instance."""
    global _optimization_engine
    if _optimization_engine is None:
        _optimization_engine = OptimizationEngine()
    return _optimization_engine

# Convenience functions


def optimize_memory():
    """Perform memory optimization routine."""
    mm = get_memory_manager()
    gc.collect()  # Force garbage collection

    # Log memory state
    memory_info = mm.get_memory_info()
    logger.info(
        f"Memory optimization completed. RSS: {memory_info.get('rss', 0) / 1024 / 1024:.2f} MB")

    return memory_info


def profile_function(func: Callable, category: str = "function"):
    """Convenience decorator for function profiling."""
    return get_profiler().profile_function(func, category)


def analyze_performance() -> Dict[str, Any]:
    """Convenience function for performance analysis."""
    return get_optimization_engine().analyze_performance()


# Export main interfaces
__all__ = [
    "LRUCache",
    "MemoryManager",
    "Profiler",
    "ResourcePool",
    "OptimizationEngine",
    "get_memory_manager",
    "get_profiler",
    "get_optimization_engine",
    "optimize_memory",
    "profile_function",
    "analyze_performance"
]
