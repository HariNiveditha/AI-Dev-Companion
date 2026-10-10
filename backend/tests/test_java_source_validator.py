
import shutil
import subprocess

import pytest

from app.services.java.source_validator import (
    validate_and_format_java_source,
    validate_java_source,
)


def test_valid_multiline_java_is_accepted():
    source = """
public class ValidatorTest {
    public static void main(String[] args) {
        System.out.println("Hello");
    }
}
"""
    result = validate_java_source(source)
    assert result.is_valid, result.diagnostics


def test_missing_closing_brace_is_rejected():
    source = 'public class Broken { public void run() { System.out.println("Hi");'
    result = validate_java_source(source)
    assert not result.is_valid
    assert any("Unclosed" in d.message for d in result.failures)


def test_malformed_top_level_import_like_statement_is_rejected():
    result = validate_java_source("java.util.Base64;")
    assert not result.is_valid
    assert any("Top-level statement" in d.message for d in result.failures)


def test_braces_inside_strings_and_comments_do_not_break_validation():
    source = r'''
public class ValidatorTest {
    public void run() {
        String text = "{ not a block }";
        /* } this is a comment { */
        System.out.println(text);
    }
}
'''
    result = validate_java_source(source)
    assert result.is_valid, result.diagnostics


def test_multiline_source_is_preserved():
    source = (
        "public class ValidatorTest {\n"
        "    public void run() {}\n"
        "}\n"
    )
    result = validate_and_format_java_source(source)
    assert result.is_valid
    assert result.formatted_content == source
    assert not result.formatting_applied


@pytest.mark.skipif(shutil.which("javac") is None, reason="JDK is not installed")
def test_javac_rejects_invalid_java_even_if_structure_is_balanced(tmp_path):
    source = """
public class InvalidJava {
    public void run() {
        int number = ;
    }
}
"""
    # Structural validation is not a full Java parser.
    result = validate_java_source(source)
    assert result.is_valid, result.diagnostics

    java_file = tmp_path / "InvalidJava.java"
    java_file.write_text(source, encoding="utf-8")

    completed = subprocess.run(
        ["javac", str(java_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "error" in completed.stderr.lower()
