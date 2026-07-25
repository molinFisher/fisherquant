import json
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from ..config.schemas import LoggingConfig


class _StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, self.datefmt),
            "module": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for key, val in record.__dict__.items():
            if key not in ("args", "asctime", "created", "exc_info", "exc_text",
                           "filename", "funcName", "id", "levelname", "levelno",
                           "lineno", "module", "msecs", "message", "msg",
                           "name", "pathname", "process", "processName",
                           "relativeCreated", "stack_info", "thread", "threadName"):
                base[key] = val
        return json.dumps(base, ensure_ascii=False, default=str)


class _ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        ts = self.formatTime(record, self.datefmt)
        msg = f"{ts} [{record.name}] {record.levelname}: {record.getMessage()}"
        if sys.stderr.isatty():
            return f"{color}{msg}{self.RESET}"
        return msg


def init_logging(cfg: LoggingConfig) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg.level.upper(), logging.INFO))

    log_dir = Path(cfg.dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    rotation = cfg.rotation
    if rotation[0].isdigit():
        when = rotation[-1]
    else:
        when = rotation[0]
    json_log = log_dir / "fisher.log"
    backup_count = int(cfg.retention.rstrip("d"))
    json_handler = TimedRotatingFileHandler(
        str(json_log), when=when, backupCount=backup_count
    )
    json_handler.setFormatter(_StructuredFormatter())
    root.addHandler(json_handler)

    term_handler = logging.StreamHandler(sys.stderr)
    term_handler.setFormatter(_ColorFormatter())
    root.addHandler(term_handler)

    for mod_name, level in cfg.modules.items():
        logging.getLogger(mod_name).setLevel(
            getattr(logging, level.upper(), logging.DEBUG)
        )
