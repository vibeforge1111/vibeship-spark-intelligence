"""Enhanced error handling and validation utilities for Spark Intelligence.

This module provides comprehensive error handling, validation,
and recovery mechanisms for robust system operation.

Key features:
- Structured error handling with context
- Validation framework with customizable rules
- Error recovery strategies
- Graceful degradation mechanisms
- Error reporting and aggregation
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union
from typing_extensions import Protocol

# Configure logger
logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error category types."""
    VALIDATION = "validation"
    CONFIGURATION = "configuration"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    MEMORY = "memory"
    PROCESSING = "processing"
    EXTERNAL_SERVICE = "external_service"
    UNKNOWN = "unknown"


@dataclass
class ErrorContext:
    """Context information for errors."""
    component: str
    operation: str
    timestamp: float = field(default_factory=time.time)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    additional_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationError:
    """Validation error information."""
    field: str
    message: str
    value: Any
    error_type: str
    context: Optional[ErrorContext] = None


@dataclass
class HandledError:
    """Structured error information."""
    error_id: str
    error_type: str
    message: str
    severity: ErrorSeverity
    category: ErrorCategory
    context: ErrorContext
    traceback: str
    timestamp: float = field(default_factory=time.time)
    recovery_action: Optional[str] = None
    recovery_successful: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "error_id": self.error_id,
            "error_type": self.error_type,
            "message": self.message,
            "severity": self.severity.value,
            "category": self.category.value,
            "context": {
                "component": self.context.component,
                "operation": self.context.operation,
                "timestamp": self.context.timestamp,
                "user_id": self.context.user_id,
                "session_id": self.context.session_id,
                "request_id": self.context.request_id,
                "additional_data": self.context.additional_data
            },
            "traceback": self.traceback,
            "timestamp": self.timestamp,
            "recovery_action": self.recovery_action,
            "recovery_successful": self.recovery_successful
        }


class ValidationErrorHandler:
    """Handler for validation errors."""

    def __init__(self):
        self._validation_errors: List[ValidationError] = []

    def add_error(self, field: str, message: str, value: Any, error_type: str, context: Optional[ErrorContext] = None):
        """Add a validation error."""
        error = ValidationError(field, message, value, error_type, context)
        self._validation_errors.append(error)
        logger.warning(f"Validation error in {field}: {message}")

    def has_errors(self) -> bool:
        """Check if there are validation errors."""
        return len(self._validation_errors) > 0

    def get_errors(self) -> List[ValidationError]:
        """Get all validation errors."""
        return self._validation_errors.copy()

    def clear_errors(self):
        """Clear all validation errors."""
        self._validation_errors.clear()

    def raise_if_errors(self, exception_class: Type[Exception] = ValueError):
        """Raise an exception if there are validation errors."""
        if self.has_errors():
            error_messages = [
                f"{e.field}: {e.message}" for e in self._validation_errors]
            raise exception_class("; ".join(error_messages))


class ErrorHandler:
    """Comprehensive error handler with recovery capabilities."""

    def __init__(self):
        self._handled_errors: List[HandledError] = []
        self._error_counts: Dict[str, int] = {}
        self._recovery_strategies: Dict[str, Callable] = {}
        self._graceful_degradation_rules: Dict[str, Any] = {}

    def register_recovery_strategy(self, error_type: str, strategy: Callable):
        """Register a recovery strategy for a specific error type."""
        self._recovery_strategies[error_type] = strategy

    def register_degradation_rule(self, component: str, rule: Any):
        """Register a graceful degradation rule."""
        self._graceful_degradation_rules[component] = rule

    def handle_error(self,
                     error: Exception,
                     context: ErrorContext,
                     severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                     category: ErrorCategory = ErrorCategory.UNKNOWN,
                     attempt_recovery: bool = True) -> HandledError:
        """Handle an error with optional recovery."""
        import uuid

        error_id = str(uuid.uuid4())
        error_type = type(error).__name__
        message = str(error)
        tb = traceback.format_exc()

        handled_error = HandledError(
            error_id=error_id,
            error_type=error_type,
            message=message,
            severity=severity,
            category=category,
            context=context,
            traceback=tb
        )

        # Attempt recovery if requested
        if attempt_recovery:
            recovery_result = self._attempt_recovery(error_type, context)
            if recovery_result:
                handled_error.recovery_action = recovery_result["action"]
                handled_error.recovery_successful = recovery_result["successful"]

        # Log the error
        self._log_error(handled_error)

        # Store the error
        self._handled_errors.append(handled_error)
        self._error_counts[error_type] = self._error_counts.get(
            error_type, 0) + 1

        return handled_error

    def _attempt_recovery(self, error_type: str, context: ErrorContext) -> Optional[Dict[str, Any]]:
        """Attempt to recover from an error."""
        strategy = self._recovery_strategies.get(error_type)
        if not strategy:
            return None

        try:
            result = strategy(context)
            return {
                "action": getattr(strategy, '__name__', 'unknown_recovery'),
                "successful": True,
                "details": result
            }
        except Exception as recovery_error:
            logger.error(f"Recovery failed for {error_type}: {recovery_error}")
            return {
                "action": getattr(strategy, '__name__', 'unknown_recovery'),
                "successful": False,
                "details": str(recovery_error)
            }

    def _log_error(self, handled_error: HandledError):
        """Log the handled error."""
        log_level = {
            ErrorSeverity.LOW: logging.WARNING,
            ErrorSeverity.MEDIUM: logging.ERROR,
            ErrorSeverity.HIGH: logging.ERROR,
            ErrorSeverity.CRITICAL: logging.CRITICAL
        }[handled_error.severity]

        logger.log(log_level,
                   f"Error {handled_error.error_id}: {handled_error.message}",
                   extra={
                       "error_id": handled_error.error_id,
                       "error_type": handled_error.error_type,
                       "severity": handled_error.severity.value,
                       "component": handled_error.context.component
                   })

    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error statistics."""
        total_errors = len(self._handled_errors)
        if total_errors == 0:
            return {"total_errors": 0}

        # Group by type
        by_type = {}
        for error in self._handled_errors:
            error_type = error.error_type
            if error_type not in by_type:
                by_type[error_type] = {
                    "count": 0,
                    "severity_counts": {},
                    "categories": set()
                }
            by_type[error_type]["count"] += 1
            severity = error.severity.value
            by_type[error_type]["severity_counts"][severity] = \
                by_type[error_type]["severity_counts"].get(severity, 0) + 1
            by_type[error_type]["categories"].add(error.category.value)

        # Convert sets to lists for serialization
        for error_type in by_type:
            by_type[error_type]["categories"] = list(
                by_type[error_type]["categories"])

        return {
            "total_errors": total_errors,
            "error_types": by_type,
            "error_counts": self._error_counts.copy()
        }

    def get_recent_errors(self, limit: int = 50) -> List[HandledError]:
        """Get recent errors."""
        return self._handled_errors[-limit:] if self._handled_errors else []


class ValidationRule(Protocol):
    """Protocol for validation rules."""

    def validate(self, value: Any, field_name: str) -> List[str]:
        """Validate a value and return error messages."""
        ...


class RequiredRule:
    """Validation rule for required fields."""

    def __init__(self, message: str = "Field is required"):
        self.message = message

    def validate(self, value: Any, field_name: str) -> List[str]:
        if value is None or value == "":
            return [self.message]
        return []


class TypeRule:
    """Validation rule for type checking."""

    def __init__(self, expected_type: Type, message: Optional[str] = None):
        self.expected_type = expected_type
        self.message = message or f"Must be of type {expected_type.__name__}"

    def validate(self, value: Any, field_name: str) -> List[str]:
        if value is not None and not isinstance(value, self.expected_type):
            return [self.message]
        return []


class RangeRule:
    """Validation rule for numeric ranges."""

    def __init__(self, min_value: Optional[float] = None,
                 max_value: Optional[float] = None,
                 message: Optional[str] = None):
        self.min_value = min_value
        self.max_value = max_value
        self.message = message

    def validate(self, value: Any, field_name: str) -> List[str]:
        if value is None:
            return []

        errors = []
        if not isinstance(value, (int, float)):
            errors.append("Must be a number")
            return errors

        if self.min_value is not None and value < self.min_value:
            msg = self.message or f"Must be >= {self.min_value}"
            errors.append(msg)

        if self.max_value is not None and value > self.max_value:
            msg = self.message or f"Must be <= {self.max_value}"
            errors.append(msg)

        return errors


class LengthRule:
    """Validation rule for string/array length."""

    def __init__(self, min_length: Optional[int] = None,
                 max_length: Optional[int] = None,
                 message: Optional[str] = None):
        self.min_length = min_length
        self.max_length = max_length
        self.message = message

    def validate(self, value: Any, field_name: str) -> List[str]:
        if value is None:
            return []

        if not hasattr(value, '__len__'):
            return ["Must have length (string, list, etc.)"]

        errors = []
        length = len(value)

        if self.min_length is not None and length < self.min_length:
            msg = self.message or f"Length must be >= {self.min_length}"
            errors.append(msg)

        if self.max_length is not None and length > self.max_length:
            msg = self.message or f"Length must be <= {self.max_length}"
            errors.append(msg)

        return errors


class PatternRule:
    """Validation rule for regex patterns."""

    def __init__(self, pattern: str, message: Optional[str] = None):
        import re
        self.pattern = re.compile(pattern)
        self.message = message or f"Must match pattern: {pattern}"

    def validate(self, value: Any, field_name: str) -> List[str]:
        if value is None:
            return []

        if not isinstance(value, str):
            return ["Must be a string"]

        if not self.pattern.match(value):
            return [self.message]

        return []


class Validator:
    """Main validator class that combines multiple rules."""

    def __init__(self):
        self._rules: Dict[str, List[ValidationRule]] = {}
        self._error_handler = ValidationErrorHandler()

    def add_rule(self, field: str, rule: ValidationRule):
        """Add a validation rule for a field."""
        if field not in self._rules:
            self._rules[field] = []
        self._rules[field].append(rule)

    def validate(self, data: Dict[str, Any], context: Optional[ErrorContext] = None) -> bool:
        """Validate data against all rules."""
        self._error_handler.clear_errors()

        for field, rules in self._rules.items():
            value = data.get(field)
            for rule in rules:
                errors = rule.validate(value, field)
                for error in errors:
                    self._error_handler.add_error(
                        field=field,
                        message=error,
                        value=value,
                        error_type=type(rule).__name__,
                        context=context
                    )

        return not self._error_handler.has_errors()

    def get_errors(self) -> List[ValidationError]:
        """Get validation errors."""
        return self._error_handler.get_errors()

    def raise_errors(self):
        """Raise validation errors as exception."""
        self._error_handler.raise_if_errors()


class GracefulDegradationManager:
    """Manager for graceful degradation of system components."""

    def __init__(self):
        self._component_states: Dict[str, Dict[str, Any]] = {}
        self._degradation_policies: Dict[str, Callable] = {}

    def register_policy(self, component: str, policy: Callable):
        """Register a degradation policy for a component."""
        self._degradation_policies[component] = policy

    def report_component_health(self, component: str, healthy: bool,
                                metrics: Optional[Dict[str, Any]] = None):
        """Report component health status."""
        if component not in self._component_states:
            self._component_states[component] = {
                "healthy": True,
                "failure_count": 0,
                "last_check": time.time(),
                "metrics": {}
            }

        state = self._component_states[component]
        state["healthy"] = healthy
        state["last_check"] = time.time()
        if metrics:
            state["metrics"].update(metrics)

        if not healthy:
            state["failure_count"] += 1

    def should_degrade(self, component: str) -> bool:
        """Check if component should be degraded."""
        if component not in self._component_states:
            return False

        state = self._component_states[component]
        policy = self._degradation_policies.get(component)

        if policy:
            return policy(state)

        # Default policy: degrade if 3 consecutive failures
        return state["failure_count"] >= 3 and not state["healthy"]

    def get_component_status(self, component: str) -> Dict[str, Any]:
        """Get component status information."""
        return self._component_states.get(component, {
            "healthy": True,
            "failure_count": 0,
            "last_check": None,
            "metrics": {}
        })


# Global instances
_error_handler: Optional[ErrorHandler] = None
_degradation_manager: Optional[GracefulDegradationManager] = None


def get_error_handler() -> ErrorHandler:
    """Get singleton error handler instance."""
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler()
    return _error_handler


def get_degradation_manager() -> GracefulDegradationManager:
    """Get singleton degradation manager instance."""
    global _degradation_manager
    if _degradation_manager is None:
        _degradation_manager = GracefulDegradationManager()
    return _degradation_manager

# Decorators


def handle_errors(component: str,
                  severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                  category: ErrorCategory = ErrorCategory.UNKNOWN,
                  recoverable: bool = True):
    """Decorator for automatic error handling."""
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            context = ErrorContext(
                component=component,
                operation=func.__name__
            )

            try:
                return func(*args, **kwargs)
            except Exception as e:
                handler = get_error_handler()
                handled_error = handler.handle_error(
                    error=e,
                    context=context,
                    severity=severity,
                    category=category,
                    attempt_recovery=recoverable
                )

                # Re-raise critical errors
                if severity == ErrorSeverity.CRITICAL:
                    raise

                # Return None or default value for non-critical errors
                return None
        return wrapper
    return decorator


@contextmanager
def error_context(component: str, operation: str, **context_data):
    """Context manager for error context."""
    context = ErrorContext(
        component=component,
        operation=operation,
        **context_data
    )

    try:
        yield context
    except Exception as e:
        handler = get_error_handler()
        handler.handle_error(e, context)
        raise

# Convenience functions


def validate_data(data: Dict[str, Any], rules: Dict[str, List[ValidationRule]]) -> Tuple[bool, List[str]]:
    """Convenience function for data validation."""
    validator = Validator()

    for field, field_rules in rules.items():
        for rule in field_rules:
            validator.add_rule(field, rule)

    is_valid = validator.validate(data)
    errors = [f"{e.field}: {e.message}" for e in validator.get_errors()]

    return is_valid, errors


def report_component_health(component: str, healthy: bool, metrics: Optional[Dict[str, Any]] = None):
    """Convenience function for reporting component health."""
    manager = get_degradation_manager()
    manager.report_component_health(component, healthy, metrics)


def should_degrade_component(component: str) -> bool:
    """Convenience function for checking component degradation."""
    manager = get_degradation_manager()
    return manager.should_degrade(component)


# Export main interfaces
__all__ = [
    "ErrorSeverity",
    "ErrorCategory",
    "ErrorContext",
    "ValidationError",
    "HandledError",
    "ValidationErrorHandler",
    "ErrorHandler",
    "ValidationRule",
    "RequiredRule",
    "TypeRule",
    "RangeRule",
    "LengthRule",
    "PatternRule",
    "Validator",
    "GracefulDegradationManager",
    "get_error_handler",
    "get_degradation_manager",
    "handle_errors",
    "error_context",
    "validate_data",
    "report_component_health",
    "should_degrade_component"
]
