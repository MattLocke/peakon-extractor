from __future__ import annotations

import asyncio
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings
from .http import PeakonClient
from .ingest import ingest_all
from .storage import MongoStorage

logger = logging.getLogger(__name__)


def _run_once(settings: Settings) -> None:
    async def _main() -> None:
        client = PeakonClient(
            base_url=settings.peakon_base_url,
            app_token=settings.peakon_app_token,
            timeout_seconds=settings.http_timeout_seconds,
        )
        storage = MongoStorage(settings.mongo_uri, settings.mongo_db)
        try:
            stats = await ingest_all(
                client,
                storage,
                company_id=settings.peakon_company_id,
                engagement_group=settings.peakon_engagement_group,
                per_page=settings.peakon_per_page,
                full_sync=settings.full_sync,
            )
            logger.info("Ingestion completed: %s", stats)
        finally:
            await client.aclose()

    asyncio.run(_main())


def run_daemon(settings: Settings) -> None:
    scheduler = BackgroundScheduler()

    trigger = CronTrigger.from_crontab(settings.schedule_cron)
    scheduler.add_job(_run_once, trigger, args=[settings], id="weekly_ingest", replace_existing=True)

    scheduler.start()
    logger.info("Scheduler started with cron '%s'.", settings.schedule_cron)

    if settings.run_on_start:
        logger.info("RUN_ON_START=true; running ingestion once immediately.")
        _run_once(settings)

    try:
        # Keep process alive
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown()
