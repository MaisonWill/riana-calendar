"""Scheduler setup for periodic occupancy updates."""

from __future__ import annotations

import logging
import signal
from collections.abc import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

LOGGER = logging.getLogger(__name__)


def _build_trigger(cron_expr: str) -> CronTrigger:
    """Create CronTrigger from standard 5-field cron expression."""
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 parts): {cron_expr}")

    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


def run_scheduler(job: Callable[[], None], cron_expr: str) -> None:
    """Run blocking scheduler with immediate first execution.

    Args:
        job: Function to execute per schedule.
        cron_expr: Five-part cron expression.
    """
    scheduler = BlockingScheduler()
    trigger = _build_trigger(cron_expr)

    scheduler.add_job(job, trigger=trigger, id="occupancy_job", replace_existing=True)

    def _shutdown_handler(signum: int, _frame: object) -> None:
        LOGGER.info("Received signal %s, shutting down scheduler...", signum)
        if scheduler.running:
            scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    LOGGER.info("Running immediate startup sync...")
    try:
        job()
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Immediate startup sync failed.")

    LOGGER.info("Starting scheduler with cron: %s", cron_expr)
    scheduler.start()

