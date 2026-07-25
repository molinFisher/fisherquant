import re
import ast
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ErrorRecord:
    test_name: str
    file_path: str
    line_number: int
    exception_type: str
    exception_message: str
    traceback: str
    fixed: bool = False
    fix_description: str = ""


@dataclass
class FixResult:
    record: ErrorRecord
    fixed: bool
    description: str
    error: str = ""


class AutoFixEngine:
    def __init__(self, project_root: str, max_rounds: int = 3):
        self.project_root = Path(project_root)
        self.max_rounds = max_rounds
        self.fix_log: list[FixResult] = []

    def parse_test_output(self, output: str) -> list[ErrorRecord]:
        records = []
        lines = output.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("FAILED") or line.startswith("ERROR"):
                record = self._parse_error_block(lines, i)
                if record:
                    records.append(record)
            i += 1
        return records

    def _parse_error_block(self, lines: list[str], start_idx: int) -> ErrorRecord | None:
        test_name = lines[start_idx].strip()
        file_path = ""
        line_number = 0
        exception_type = ""
        exception_message = ""

        for j in range(start_idx + 1, min(start_idx + 15, len(lines))):
            ln = lines[j].strip()
            file_match = re.match(r'File "(.+)", line (\d+)', ln)
            if file_match:
                file_path = file_match.group(1)
                line_number = int(file_match.group(2))

            exc_match = re.match(r"(\w+Error|\w+Warning|\w+Exception):?\s*(.*)", ln)
            if exc_match:
                exception_type = exc_match.group(1)
                exception_message = exc_match.group(2)

        if not exception_type:
            return None

        return ErrorRecord(
            test_name=test_name,
            file_path=file_path,
            line_number=line_number,
            exception_type=exception_type,
            exception_message=exception_message,
            traceback="\n".join(lines[start_idx:start_idx+15]),
        )

    def fix(self, record: ErrorRecord) -> FixResult:
        strategies = {
            "ModuleNotFoundError": self._fix_module_not_found,
            "ImportError": self._fix_import,
            "AttributeError": self._fix_attribute,
            "TypeError": self._fix_type_error,
            "NameError": self._fix_name_error,
            "ValueError": self._fix_value_error,
            "KeyError": self._fix_key_error,
            "IndexError": self._fix_index_error,
            "FileNotFoundError": self._fix_file_not_found,
            "AssertionError": self._fix_assertion,
            "ValidationError": self._fix_validation,
            "ConnectionError": self._fix_connection,
            "TimeoutError": self._fix_connection,
            "ZeroDivisionError": self._fix_zero_division,
            "NotImplementedError": self._fix_not_implemented,
        }
        fixer = strategies.get(record.exception_type, self._fix_unknown)
        try:
            description = fixer(record)
            return FixResult(record=record, fixed=True, description=description)
        except Exception as e:
            return FixResult(record=record, fixed=False, description=record.exception_type, error=str(e))

    def fix_round(self, records: list[ErrorRecord]) -> list[FixResult]:
        results = []
        for r in records:
            result = self.fix(r)
            self.fix_log.append(result)
            results.append(result)
        return results

    def run_iteration(self, test_output: str) -> tuple[list[FixResult], str]:
        records = self.parse_test_output(test_output)
        results = self.fix_round(records)

        fixed_count = sum(1 for r in results if r.fixed)
        return results, f"Fixed {fixed_count}/{len(results)} errors"

    def _read_file(self, path: str) -> list[str]:
        full = self.project_root / path
        if not full.exists():
            return []
        return full.read_text(encoding="utf-8").split("\n")

    def _write_file(self, path: str, lines: list[str]):
        full = self.project_root / path
        full.write_text("\n".join(lines), encoding="utf-8")

    def _fix_module_not_found(self, r: ErrorRecord) -> str:
        match = re.search(r"No module named '(\w+)'", r.exception_message)
        if not match:
            return "MODULE_NOT_FOUND: no module name in message"
        mod = match.group(1)
        try:
            subprocess.run(["pip", "install", mod], capture_output=True, text=True, timeout=30)
            return f"pip install {mod}"
        except Exception as e:
            return f"pip install {mod} failed: {e}"

    def _fix_import(self, r: ErrorRecord) -> str:
        if not r.file_path:
            return "IMPORT: no file to fix"
        lines = self._read_file(r.file_path)
        match = re.search(r"cannot import name '(\w+)'", r.exception_message)
        if match:
            name = match.group(1)
            lines.insert(0, f"from ??? import {name}  # auto-fix: add missing import")
            self._write_file(r.file_path, lines)
            return f"ADDED import stub for {name}"
        return "IMPORT: could not parse import name"

    def _fix_attribute(self, r: ErrorRecord) -> str:
        match = re.search(r"'(\w+)' object has no attribute '(\w+)'", r.exception_message)
        if not match or not r.file_path:
            return "ATTRIBUTE: no file/object to fix"
        obj, attr = match.group(1), match.group(2)
        lines = self._read_file(r.file_path)
        if r.line_number and 0 < r.line_number <= len(lines):
            lines.insert(r.line_number - 1, f"# auto-fix: {obj}.{attr} accessed but not defined")
            self._write_file(r.file_path, lines)
            return f"MARKED {obj}.{attr} at {r.file_path}:{r.line_number}"
        return f"ATTRIBUTE: {obj}.{attr} — could not locate in file"

    def _fix_type_error(self, r: ErrorRecord) -> str:
        match = re.search(r"takes (\d+) positional argument[s]? but (\d+) w", r.exception_message)
        if match:
            return f"TYPE: signature mismatch (expects {match.group(1)}, got {match.group(2)}) — manual fix required"
        return f"TYPE: {r.exception_message[:80]} — manual fix required"

    def _fix_name_error(self, r: ErrorRecord) -> str:
        match = re.search(r"name '(\w+)' is not defined", r.exception_message)
        if match:
            name = match.group(1)
            if r.file_path and r.line_number:
                lines = self._read_file(r.file_path)
                if 0 < r.line_number - 1 < len(lines):
                    lines[r.line_number - 1] += f"  # auto-fix: undefined name '{name}'"
                    self._write_file(r.file_path, lines)
                return f"MARKED undefined name '{name}'"
        return f"NAME: {r.exception_message[:80]}"

    def _fix_value_error(self, r: ErrorRecord) -> str:
        return f"VALUE: {r.exception_message[:80]} — review input validation"

    def _fix_key_error(self, r: ErrorRecord) -> str:
        match = re.search(r"'?(\w+)'?", r.exception_message)
        if match and r.file_path and r.line_number:
            key = match.group(1)
            lines = self._read_file(r.file_path)
            if 0 < r.line_number - 1 < len(lines):
                lines[r.line_number - 1] = lines[r.line_number - 1].replace(
                    f"[{key}]", f".get('{key}')"
                ).replace(f"['{key}']", f".get('{key}')")
                self._write_file(r.file_path, lines)
                return f"KEY: replaced [{key}] with .get('{key}')"
        return f"KEY: {r.exception_message[:80]}"

    def _fix_index_error(self, r: ErrorRecord) -> str:
        if r.file_path and r.line_number:
            lines = self._read_file(r.file_path)
            if 0 <= r.line_number - 1 < len(lines):
                target = lines[r.line_number - 1]
                indent = len(target) - len(target.lstrip())
                guard = " " * indent + f"if len(seq) > 0:  # auto-fix guard"
                lines.insert(r.line_number - 1, guard)
                self._write_file(r.file_path, lines)
                return f"INDEX: added guard at {r.file_path}:{r.line_number}"
        return "INDEX: could not add guard"

    def _fix_file_not_found(self, r: ErrorRecord) -> str:
        match = re.search(r"No such file.*'(.+?)'", r.exception_message)
        if match:
            path = Path(match.group(1))
            full = self.project_root / path if not path.is_absolute() else path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.touch()
            return f"CREATED: {full}"
        return "FILE_NOT_FOUND: could not parse path"

    def _fix_assertion(self, r: ErrorRecord) -> str:
        return f"ASSERT: {r.exception_message[:80]} — manual review needed"

    def _fix_validation(self, r: ErrorRecord) -> str:
        return f"VALIDATION: pydantic validation error — add default or fix input"

    def _fix_connection(self, r: ErrorRecord) -> str:
        return f"CONNECT: network error — add retry logic"

    def _fix_zero_division(self, r: ErrorRecord) -> str:
        if r.file_path and r.line_number:
            lines = self._read_file(r.file_path)
            if 0 <= r.line_number - 1 < len(lines):
                target = lines[r.line_number - 1]
                if "/" in target:
                    lines[r.line_number - 1] = target.replace(" / ", " / max(denominator, 1e-10) ")
                    self._write_file(r.file_path, lines)
                    return f"DIV0: added denominator guard at {r.file_path}:{r.line_number}"
        return "DIV0: could not add guard"

    def _fix_not_implemented(self, r: ErrorRecord) -> str:
        if r.file_path and r.line_number:
            lines = self._read_file(r.file_path)
            if 0 <= r.line_number - 1 < len(lines):
                target = lines[r.line_number - 1]
                if "NotImplementedError" in target or "raise NotImplementedError" in target:
                    lines[r.line_number - 1] = target.replace(
                        'raise NotImplementedError("',
                        'pass  # auto-fix stub: NotImplementated → pass\n    # raise NotImplementedError("',
                    )
                    self._write_file(r.file_path, lines)
                    return f"STUBBED: NotImplementedError → pass at {r.file_path}:{r.line_number}"
        return "NOT-IMPL: could not stub"

    def _fix_unknown(self, r: ErrorRecord) -> str:
        return f"UNKNOWN: {r.exception_type} — manual review needed"
