"""Validation of executable JUnit 5 test sources.

An executable test is a *complete Java source file* implementing descriptive
test cases.  Before one is stored or executed it must:

* pass the structural Java validator (complete, balanced, real newlines);
* import JUnit Jupiter and declare at least one ``@Test``;
* declare a class whose name can be mapped to a safe ``.java`` file name;
* declare every method referenced in ``method_map`` as a real method
  (``method_map`` links each descriptive test-case id to its JUnit method).

These checks keep untrusted or malformed sources out of the runner and keep
the test-case → method association honest.
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.java_validator import validate_java_source
from app.services.execution.workspace import derive_class_name

# A method declaration: modifiers/return type, then the method name.
_METHOD_DECL_TEMPLATE = r"\b(?:void|[A-Za-z_$][\w$<>[\],\s]*)\s+{name}\s*\("
_METHOD_NAME_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _method_declared(content: str, method_name: str) -> bool:
    pattern = _METHOD_DECL_TEMPLATE.format(name=re.escape(method_name))
    return re.search(pattern, content) is not None


def validate_executable_test(content: str, method_map: dict) -> list[str]:
    """Return a list of human-readable problems; empty list means valid."""
    errors: list[str] = []

    structural = validate_java_source(content)
    if not structural.ok:
        errors.extend(structural.errors)
        # Remaining checks would be noise on top of structural failures.
        return errors

    if "org.junit" not in content:
        errors.append("Test source does not import JUnit (expected an 'import org.junit...' declaration).")
    if "@Test" not in content and "@ParameterizedTest" not in content:
        errors.append("Test source declares no @Test (or @ParameterizedTest) methods.")

    class_name = derive_class_name(content)
    if not class_name:
        errors.append("No class, interface, enum, or record declaration found.")

    if not isinstance(method_map, dict):
        errors.append("method_map must be an object mapping test_case_id -> method name.")
        return errors

    seen_methods: dict[str, str] = {}
    for case_id, method_name in method_map.items():
        if not str(case_id).strip():
            errors.append("method_map contains an empty test case id.")
            continue
        if not isinstance(method_name, str) or not _METHOD_NAME_RE.fullmatch(method_name):
            errors.append(
                f"method_map[{case_id!r}] = {method_name!r} is not a valid Java method name."
            )
            continue
        if not _method_declared(content, method_name):
            errors.append(
                f"method_map[{case_id!r}] references method '{method_name}' which is not "
                "declared in the test source."
            )
        previous = seen_methods.get(method_name)
        if previous is not None:
            errors.append(
                f"method_map maps both {previous!r} and {case_id!r} to the same method "
                f"'{method_name}'; each test case needs its own method."
            )
        seen_methods[method_name] = str(case_id)

    return errors


def file_name_for(class_name: Optional[str]) -> Optional[str]:
    if not class_name or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", class_name):
        return None
    return f"{class_name}.java"
