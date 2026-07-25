import json
import logging
from pathlib import Path
import pytest
from fisher.logging.setup import init_logging
from fisher.config.schemas import LoggingConfig


@pytest.fixture
def _cleanup_handlers():
    yield
    root = logging.getLogger()
    for h in root.handlers[:]:
        h.close()
        root.removeHandler(h)


class TestInitLogging:
    def test_json_handler_writes_structured(self, tmp_path, _cleanup_handlers):
        d = str(tmp_path)
        cfg = LoggingConfig(dir=d, rotation="1h", retention="1d")
        init_logging(cfg)

        logger = logging.getLogger("test_json")
        logger.info("hello", extra={"key": "val"})

        logs = list(Path(d).glob("*.log*"))
        assert len(logs) > 0
        line = logs[0].read_text()
        record = json.loads(line)
        assert record["message"] == "hello"
        assert record.get("key") == "val"

    def test_module_level_override(self, tmp_path, _cleanup_handlers):
        d = str(tmp_path)
        cfg = LoggingConfig(
            dir=d, rotation="1h", retention="1d",
            modules={"test_mod": "WARNING"}
        )
        init_logging(cfg)

        logger = logging.getLogger("test_mod")
        assert logger.level == logging.WARNING

    def test_root_level_is_set(self, tmp_path, _cleanup_handlers):
        d = str(tmp_path)
        cfg = LoggingConfig(dir=d, level="DEBUG")
        init_logging(cfg)

        root = logging.getLogger()
        assert root.level == logging.DEBUG
