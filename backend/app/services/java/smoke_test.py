import sys
import os
from pathlib import Path

# Ensure the backend directory is on the path so the app package is importable.
_backend = Path(__file__).resolve().parents[3]
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.services.java.source_validator import (
    validate_and_format_java_source,
    validate_java_source,
)

# ---- Test 1: single-line Java output ----
single_line = "public class Foo { public static void main(String[] args) { System.out.println(\"hi\"); } }"
r1 = validate_and_format_java_source(single_line)
print("TEST1 single-line valid:", r1.is_valid, "formatted:", r1.formatting_applied, "newlines:", r1.formatted_content.count(chr(10)))

# ---- Test 2: missing import keyword ----
bad_import = "java.util.Base64;"
r2 = validate_java_source(bad_import)
print("TEST2 bad import detected:", len(r2.failures) > 0, [d.message for d in r2.failures])

# ---- Test 3: missing closing brace ----
truncated = "public class Foo {\n    public void bar() {\n        System.out.println(\"oops\");"
r3 = validate_java_source(truncated)
print("TEST3 truncated missing brace detected:", len(r3.failures) > 0, [d.message for d in r3.failures])

# ---- Test 4: valid multi-line Java ----
valid = "import java.util.Base64;\n\npublic class Foo {\n    public byte[] hash(String s) { return Base64.getEncoder().encode(s.getBytes()); }\n}"
r4 = validate_and_format_java_source(valid)
print("TEST4 valid multi-line:", r4.is_valid, "unchanged:", not r4.formatting_applied)

# ---- Test 5: jumbled source missing closing brace ----
jumbled = "public class Foo { public void bar() { System.out.println(\"hi\");"
r5 = validate_java_source(jumbled)
print("TEST5 jumble invalid:", len(r5.failures) > 0)

# ---- Test 6: string/comment preserved by validator ----
with_strings = 'public class Foo { public void m() { String s = "a\\nb"; /* comment */ System.out.println(s); } }'
r6 = validate_java_source(with_strings)
print("TEST6 string/comment preserved:", r6.is_valid)

print("ALL_SMOKE_TESTS_DONE")
