"""Tests for executable JUnit test-source validation (Phase 9)."""

import pytest

from app.services.execution.validation import (
    file_name_for,
    validate_executable_test,
)
from app.services.execution.workspace import derive_class_name

VALID_JUNIT = """import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class UserServiceTest {
    @Test
    void acceptsValidLogin() {
        assertTrue(true);
    }

    @Test
    void rejectsInvalidLogin() {
        assertTrue(true);
    }
}
"""


def test_valid_junit_source_passes():
    errors = validate_executable_test(
        VALID_JUNIT,
        {"case-1": "acceptsValidLogin", "case-2": "rejectsInvalidLogin"},
    )

    assert errors == []


def test_empty_method_map_is_allowed_at_validation_time():
    """Linkage is enforced at execution time, not authoring time."""
    errors = validate_executable_test(VALID_JUNIT, {})

    assert errors == []


def test_missing_junit_import_fails():
    source = "public class UserServiceTest {\n    @Test\n    void x() {}\n}\n"

    errors = validate_executable_test(source, {})

    assert any("JUnit" in error for error in errors)


def test_missing_test_annotation_fails():
    source = (
        "import org.junit.jupiter.api.Test;\n\n"
        "public class UserServiceTest {\n}\n"
    )

    errors = validate_executable_test(source, {})

    assert any("@Test" in error for error in errors)


def test_structural_failure_short_circuits():
    errors = validate_executable_test("public class A { ", {})

    assert errors  # structural errors only


def test_method_map_method_must_exist():
    errors = validate_executable_test(
        VALID_JUNIT, {"case-1": "doesNotExist"}
    )

    assert any("doesNotExist" in error for error in errors)


def test_method_map_requires_valid_method_name():
    errors = validate_executable_test(
        VALID_JUNIT, {"case-1": "not a method!"}
    )

    assert any("valid Java method name" in error for error in errors)


def test_method_map_rejects_shared_methods():
    errors = validate_executable_test(
        VALID_JUNIT, {"case-1": "acceptsValidLogin", "case-2": "acceptsValidLogin"}
    )

    assert any("same method" in error for error in errors)


def test_method_map_rejects_empty_case_id():
    errors = validate_executable_test(VALID_JUNIT, {"": "acceptsValidLogin"})

    assert any("empty test case id" in error for error in errors)


def test_file_name_for_derives_safe_name():
    assert file_name_for("UserServiceTest") == "UserServiceTest.java"
    assert file_name_for("bad name") is None
    assert file_name_for(None) is None
