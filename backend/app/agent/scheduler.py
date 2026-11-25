from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger("spark.scheduler")


class BackgroundWorker:
    """Minimal in-process scheduler for a single-user deployment.

    Runs Gmail sync and reminder materialisation every N minutes. A separate
    worker container can run the same cycle via ``app.worker``.
    """

    def __init__(
        self,
        gmail_sync: Any,
        reminders: Any,
        store: Any,
        interval_minutes: int = 10,
        retention_days: int = 180,
    ) -> None:
        self.gmail_sync = gmail_sync
        self.reminders = reminders
        self.store = store
        self.interval = max(60, int(interval_minutes) * 60)
        self.retention_days = retention_days
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.cycle = 0

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="spark-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        # Tiny initial delay so the API can finish starting.
        self._stop.wait(5)
        while not self._stop.is_set():
            try:
                result = self.gmail_sync.sync()
                reminders = self.reminders.run()
                log.info("cycle=%s sync=%s reminders=%s", self.cycle, result, reminders)
                if self.cycle % 1440 == 0:
                    self.store.purge_old(self.retention_days)
            except Exception as exc:
                log.exception("background cycle failed: %s", exc)
            self.cycle += 1
            self._stop.wait(self.interval)
