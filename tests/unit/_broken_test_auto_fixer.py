from fisher_temp.auto_fixer import AutoFixEngine, ErrorRecord
from pathlib import Path
import tempfile


class TestParseTestOutput:
    def test_parse_module_not_found(self):
        eng = AutoFixEngine(".")
        output = """FAILED tests/unit/test_foo.py::TestFoo::test_bar
E   ModuleNotFoundError: No module named 'numpy'"""
        records = eng.parse_test_output(output)
        assert len(records) >= 1
        assert records[0].exception_type == "ModuleNotFoundError"

    def test_parse_attribute_error(self):
        eng = AutoFixEngine(".")
        output = """ERROR tests/test_x.py - AttributeError: 'str' object has no attribute 'get'"""
        records = eng.parse_test_output(output)
        assert len(records) >= 1
        assert records[0].exception_type == "AttributeError"

    def test_parse_with_file_line(self):
        eng = AutoFixEngine(".")
        output = """FAILED tests/test_x.py::test_x
E   File "fisher/foo.py", line 42, in bar
E   TypeError: takes 2 positional arguments but 3 were given"""
        records = eng.parse_test_output(output)
        assert len(records) >= 1
        assert records[0].line_number == 42
        assert records[0].file_path == "fisher/foo.py"


class TestFixString:
    def test_fix_key_error(self):
        eng = AutoFixEngine(".")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "test.py"
            f.write_text("result = d['missing']")
            r = ErrorRecord("test", str(f), 1, "KeyError", "'missing'", "")
            result = eng.fix(r)
            assert result.fixed
            content = f.read_text()
            assert ".get('missing')" in content

    def test_fix_module_not_found_attempts_pip(self):
        eng = AutoFixEngine(".")
        r = ErrorRecord("test", "", 0, "ModuleNotFoundError", "No module named 'numpy'", "")
        result = eng.fix(r)
        assert result.fixed

    def test_parse_empty_output(self):
        eng = AutoFixEngine(".")
        records = eng.parse_test_output("")
        assert records == []

    def test_parse_multiple_errors(self):
        eng = AutoFixEngine(".")
        output = """FAILED test_a::test1
E   ImportError: cannot import name 'foo'
FAILED test_b::test2
E   KeyError: 'bar'
ERROR test_c::test3"""
        records = eng.parse_test_output(output)
        assert len(records) == 3
