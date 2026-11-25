from __future__ import annotations

import logging
import time

from .config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("spark.worker")


def main() -> None:
    settings = Settings.load()
    settings.background_sync = False  # the worker runs its own loop
    from .main import create_app

    app = create_app(settings)
    ctx = app.state.ctx
    interval = max(60, int(settings.sync_interval_minutes) * 60)
    log.info("Spark worker started (interval=%ss, mode=%s)", interval, settings.mode)
    cycle = 0
    while True:
        try:
            sync = ctx.gmail_sync.sync()
            reminders = ctx.reminders.run()
            log.info("cycle=%s sync=%s reminders=%s", cycle, sync, reminders)
            if cycle % 1440 == 0:
                purged = ctx.store.purge_old(settings.retention_days)
                if purged:
                    log.info("purged %s old messages", purged)
        except Exception as exc:
            log.exception("worker cycle failed: %s", exc)
        cycle += 1
        time.sleep(interval)


if __name__ == "__main__":
    main()
