"""Unit tests for error handling and validation utilities."""

import re
import time
from unittest.mock import MagicMock, patch

import pytest

from lib.error_handling import (
    ErrorSeverity,
    ErrorCategory,
    ErrorContext,
    ValidationError,
    HandledError,
    ValidationErrorHandler,
    ErrorHandler,
    RequiredRule,
    TypeRule,
    RangeRule,
    LengthRule,
    PatternRule,
    Validator,
    GracefulDegradationManager,
    get_error_handler,
    get_degradation_manager,
    handle_errors,
    error_context,
    validate_data,
    report_component_health,
    should_degrade_component
)


class TestValidationError:
    """Test validation error handling."""

    def test_validation_error_creation(self):
        """Test ValidationError creation."""
        context = ErrorContext(component="test", operation="validate")
        error = ValidationError(
            field="username",
            message="Username is required",
            value="",
            error_type="RequiredRule",
            context=context
        )

        assert error.field == "username"
        assert error.message == "Username is required"
        assert error.value == ""
        assert error.error_type == "RequiredRule"
        assert error.context == context

    def test_validation_error_handler(self):
        """Test ValidationErrorHandler functionality."""
        handler = ValidationErrorHandler()

        # Initially no errors
        assert not handler.has_errors()
        assert len(handler.get_errors()) == 0

        # Add errors
        context = ErrorContext(component="test", operation="validate")
        handler.add_error("field1", "Required", None, "RequiredRule", context)
        handler.add_error("field2", "Invalid type",
                          "wrong", "TypeRule", context)

        # Check errors
        assert handler.has_errors()
        errors = handler.get_errors()
        assert len(errors) == 2
        assert errors[0].field == "field1"
        assert errors[1].field == "field2"

        # Clear errors
        handler.clear_errors()
        assert not handler.has_errors()
        assert len(handler.get_errors()) == 0

    def test_raise_if_errors(self):
        """Test raising exceptions for validation errors."""
        handler = ValidationErrorHandler()

        # No errors - should not raise
        handler.raise_if_errors()

        # Add errors and test raising
        handler.add_error("field1", "Required", None, "RequiredRule")
        handler.add_error("field2", "Invalid", "bad", "TypeRule")

        with pytest.raises(ValueError) as exc_info:
            handler.raise_if_errors()

        error_message = str(exc_info.value)
        assert "field1: Required" in error_message
        assert "field2: Invalid" in error_message


class TestErrorHandler:
    """Test error handling functionality."""

    def test_error_handling_basic(self):
        """Test basic error handling."""
        handler = get_error_handler()
        handler._handled_errors.clear()  # Clear existing errors

        context = ErrorContext(component="test", operation="process")
        try:
            raise ValueError("Test error")
        except Exception as e:
            handled_error = handler.handle_error(
                error=e,
                context=context,
                severity=ErrorSeverity.MEDIUM,
                category=ErrorCategory.PROCESSING
            )

        # Check handled error
        assert handled_error.error_type == "ValueError"
        assert handled_error.message == "Test error"
        assert handled_error.severity == ErrorSeverity.MEDIUM
        assert handled_error.category == ErrorCategory.PROCESSING
        assert handled_error.context == context
        assert "Traceback" in handled_error.traceback

        # Check error was stored
        assert len(handler._handled_errors) == 1
        assert handler._error_counts["ValueError"] == 1

    def test_error_statistics(self):
        """Test error statistics collection."""
        handler = get_error_handler()
        handler._handled_errors.clear()
        handler._error_counts.clear()

        context = ErrorContext(component="test", operation="process")

        # Handle different types of errors
        try:
            raise ValueError("Value error")
        except Exception as e:
            handler.handle_error(e, context)

        try:
            raise TypeError("Type error")
        except Exception as e:
            handler.handle_error(e, context)

        try:
            raise ValueError("Another value error")
        except Exception as e:
            handler.handle_error(e, context)

        # Check statistics
        stats = handler.get_error_statistics()
        assert stats["total_errors"] == 3
        assert stats["error_counts"]["ValueError"] == 2
        assert stats["error_counts"]["TypeError"] == 1

        # Check error types breakdown
        error_types = stats["error_types"]
        assert "ValueError" in error_types
        assert "TypeError" in error_types
        assert error_types["ValueError"]["count"] == 2
        assert error_types["TypeError"]["count"] == 1

    def test_recovery_strategies(self):
        """Test error recovery strategies."""
        handler = get_error_handler()
        handler._recovery_strategies.clear()

        def recovery_strategy(context):
            return {"status": "recovered", "action": "retry"}

        handler.register_recovery_strategy("ValueError", recovery_strategy)

        context = ErrorContext(component="test", operation="process")
        try:
            raise ValueError("Test error")
        except Exception as e:
            handled_error = handler.handle_error(
                e, context, attempt_recovery=True)

        # Check recovery was attempted
        assert handled_error.recovery_action is not None
        assert handled_error.recovery_successful is True
        assert "recovery_strategy" in handled_error.recovery_action


class TestValidationRules:
    """Test validation rules."""

    def test_required_rule(self):
        """Test RequiredRule validation."""
        rule = RequiredRule("Field is mandatory")

        # Test valid values
        assert len(rule.validate("test", "field")) == 0
        assert len(rule.validate(0, "field")) == 0
        assert len(rule.validate([], "field")) == 0

        # Test invalid values
        errors = rule.validate(None, "field")
        assert len(errors) == 1
        assert "mandatory" in errors[0]

        errors = rule.validate("", "field")
        assert len(errors) == 1
        assert "mandatory" in errors[0]

    def test_type_rule(self):
        """Test TypeRule validation."""
        rule = TypeRule(int, "Must be integer")

        # Test valid values
        assert len(rule.validate(42, "field")) == 0
        assert len(rule.validate(0, "field")) == 0

        # Test invalid values
        errors = rule.validate("not an int", "field")
        assert len(errors) == 1
        assert "integer" in errors[0]

        errors = rule.validate(3.14, "field")
        assert len(errors) == 1
        assert "integer" in errors[0]

    def test_range_rule(self):
        """Test RangeRule validation."""
        rule = RangeRule(min_value=1, max_value=10, message="Between 1 and 10")

        # Test valid values
        assert len(rule.validate(5, "field")) == 0
        assert len(rule.validate(1, "field")) == 0
        assert len(rule.validate(10, "field")) == 0
        assert len(rule.validate(None, "field")) == 0  # None is allowed

        # Test invalid values
        errors = rule.validate(0, "field")
        assert len(errors) == 1
        assert "Between 1 and 10" in errors[0]

        errors = rule.validate(15, "field")
        assert len(errors) == 1
        assert "Between 1 and 10" in errors[0]

        # Test non-numeric
        errors = rule.validate("not a number", "field")
        assert len(errors) == 1
        assert "Must be a number" in errors[0]

    def test_length_rule(self):
        """Test LengthRule validation."""
        rule = LengthRule(min_length=2, max_length=5, message="Length 2-5")

        # Test valid values
        assert len(rule.validate("abc", "field")) == 0
        assert len(rule.validate([1, 2, 3], "field")) == 0
        assert len(rule.validate("ab", "field")) == 0
        assert len(rule.validate("abcde", "field")) == 0
        assert len(rule.validate(None, "field")) == 0  # None is allowed

        # Test invalid values
        errors = rule.validate("a", "field")  # Too short
        assert len(errors) == 1
        assert "Length 2-5" in errors[0]

        errors = rule.validate("abcdef", "field")  # Too long
        assert len(errors) == 1
        assert "Length 2-5" in errors[0]

        # Test non-length objects
        errors = rule.validate(42, "field")
        assert len(errors) == 1
        assert "length" in errors[0].lower()

    def test_pattern_rule(self):
        """Test PatternRule validation."""
        rule = PatternRule(r"^[a-zA-Z0-9]+$", "Alphanumeric only")

        # Test valid values
        assert len(rule.validate("abc123", "field")) == 0
        assert len(rule.validate("ABC", "field")) == 0
        assert len(rule.validate(None, "field")) == 0  # None is allowed

        # Test invalid values
        errors = rule.validate("abc-123", "field")
        assert len(errors) == 1
        assert "Alphanumeric only" in errors[0]

        errors = rule.validate("", "field")  # Empty string
        assert len(errors) == 1
        assert "Alphanumeric only" in errors[0]

        # Test non-string
        errors = rule.validate(123, "field")
        assert len(errors) == 1
        assert "Must be a string" in errors[0]


class TestValidator:
    """Test Validator functionality."""

    def test_validator_basic(self):
        """Test basic validator functionality."""
        validator = Validator()

        # Add rules
        validator.add_rule("username", RequiredRule())
        validator.add_rule("username", LengthRule(min_length=3, max_length=20))
        validator.add_rule("age", TypeRule(int))
        validator.add_rule("age", RangeRule(min_value=0, max_value=150))

        # Test valid data
        valid_data = {
            "username": "john_doe",
            "age": 25
        }

        assert validator.validate(valid_data)
        assert len(validator.get_errors()) == 0

        # Test invalid data
        invalid_data = {
            "username": "jo",  # Too short
            "age": "not_a_number"  # Wrong type
        }

        assert not validator.validate(invalid_data)
        errors = validator.get_errors()
        assert len(errors) == 2

        # Check error details
        error_fields = {e.field for e in errors}
        assert "username" in error_fields
        assert "age" in error_fields

    def test_validator_with_context(self):
        """Test validator with error context."""
        validator = Validator()
        validator.add_rule("email", RequiredRule())
        validator.add_rule("email", PatternRule(r"^[^@]+@[^@]+\.[^@]+$"))

        context = ErrorContext(component="user_service",
                               operation="create_user")
        data = {"email": "invalid-email"}

        is_valid = validator.validate(data, context)
        assert not is_valid

        errors = validator.get_errors()
        assert len(errors) == 1
        assert errors[0].context == context


class TestGracefulDegradationManager:
    """Test graceful degradation functionality."""

    def test_component_health_reporting(self):
        """Test component health reporting."""
        manager = get_degradation_manager()
        manager._component_states.clear()

        # Report healthy state
        manager.report_component_health(
            "database", True, {"response_time": 0.1})
        status = manager.get_component_status("database")
        assert status["healthy"] is True
        assert status["failure_count"] == 0
        assert status["metrics"]["response_time"] == 0.1

        # Report unhealthy state
        manager.report_component_health("database", False, {"error_rate": 0.5})
        status = manager.get_component_status("database")
        assert status["healthy"] is False
        assert status["failure_count"] == 1
        assert status["metrics"]["error_rate"] == 0.5

    def test_degradation_policies(self):
        """Test degradation policies."""
        manager = get_degradation_manager()
        manager._component_states.clear()

        # Register policy: degrade after 2 failures
        def failure_policy(state):
            return state["failure_count"] >= 2

        manager.register_policy("api_service", failure_policy)

        # Initially should not degrade
        assert not manager.should_degrade("api_service")

        # Report 1 failure
        manager.report_component_health("api_service", False)
        assert not manager.should_degrade("api_service")

        # Report 2nd failure
        manager.report_component_health("api_service", False)
        assert manager.should_degrade("api_service")

    def test_default_degradation_policy(self):
        """Test default degradation policy."""
        manager = get_degradation_manager()
        manager._component_states.clear()
        manager._degradation_policies.clear()  # Remove custom policies

        # Should degrade after 3 consecutive failures
        for _ in range(3):
            manager.report_component_health("test_service", False)

        assert manager.should_degrade("test_service")


def test_error_decorators():
    """Test error handling decorators."""
    handler = get_error_handler()
    handler._handled_errors.clear()

    @handle_errors(component="test_service", severity=ErrorSeverity.HIGH)
    def failing_function():
        raise RuntimeError("Something went wrong")

    # Function should handle error and return None
    result = failing_function()
    assert result is None

    # Error should be recorded
    assert len(handler._handled_errors) == 1
    handled_error = handler._handled_errors[0]
    assert handled_error.error_type == "RuntimeError"
    assert handled_error.context.component == "test_service"

    # Test critical errors are re-raised
    @handle_errors(component="critical_service", severity=ErrorSeverity.CRITICAL)
    def critical_function():
        raise SystemError("Critical failure")

    with pytest.raises(SystemError):
        critical_function()


def test_error_context_manager():
    """Test error context manager."""
    handler = get_error_handler()
    handler._handled_errors.clear()

    with error_context("test_component", "test_operation", user_id="123") as ctx:
        assert ctx.component == "test_component"
        assert ctx.operation == "test_operation"
        assert ctx.user_id == "123"
        raise ValueError("Context error")

    # Error should be handled
    assert len(handler._handled_errors) == 1
    handled_error = handler._handled_errors[0]
    assert handled_error.context.component == "test_component"
    assert handled_error.context.user_id == "123"


def test_convenience_functions():
    """Test convenience functions."""
    # Test validate_data
    rules = {
        "name": [RequiredRule(), LengthRule(min_length=2)],
        "age": [TypeRule(int), RangeRule(min_value=0, max_value=120)]
    }

    # Valid data
    valid_data = {"name": "John", "age": 25}
    is_valid, errors = validate_data(valid_data, rules)
    assert is_valid
    assert len(errors) == 0

    # Invalid data
    invalid_data = {"name": "J", "age": "not_a_number"}
    is_valid, errors = validate_data(invalid_data, rules)
    assert not is_valid
    assert len(errors) == 2

    # Test component health reporting
    manager = get_degradation_manager()
    manager._component_states.clear()

    report_component_health("test_service", True, {"uptime": 0.99})
    status = manager.get_component_status("test_service")
    assert status["healthy"] is True

    # Test degradation check
    assert not should_degrade_component("test_service")


def test_singleton_instances():
    """Test that singleton instances work correctly."""
    handler1 = get_error_handler()
    handler2 = get_error_handler()
    assert handler1 is handler2  # Should be the same instance

    manager1 = get_degradation_manager()
    manager2 = get_degradation_manager()
    assert manager1 is manager2  # Should be the same instance


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
