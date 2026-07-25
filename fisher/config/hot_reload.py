import hashlib
import threading
import time
import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


class ConfigReloader:
    def __init__(self, config_dir: str, polling_interval: float = 5.0):
        self._config_dir = Path(config_dir)
        self._polling_interval = polling_interval
        self._hashes: dict[str, str] = {}
        self._callbacks: list[Callable[[str], None]] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._compute_hashes()

    def _compute_hashes(self):
        for f in self._config_dir.glob("*.yaml"):
            content = f.read_bytes()
            self._hashes[f.name] = hashlib.md5(content).hexdigest()

    def on_change(self, callback: Callable[[str], None]):
        self._callbacks.append(callback)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("ConfigReloader started (interval=%ds)", self._polling_interval)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self):
        while self._running:
            time.sleep(self._polling_interval)
            try:
                self._check_changes()
            except Exception:
                logger.exception("Config reload check failed")

    def _check_changes(self):
        for f in self._config_dir.glob("*.yaml"):
            content = f.read_bytes()
            new_hash = hashlib.md5(content).hexdigest()
            old_hash = self._hashes.get(f.name, "")
            if new_hash != old_hash:
                self._hashes[f.name] = new_hash
                logger.info("Config changed: %s", f.name)
                for cb in self._callbacks:
                    try:
                        cb(f.name)
                    except Exception:
                        logger.exception("Config change callback failed for %s", f.name)
