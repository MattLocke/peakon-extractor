from __future__ import annotations

import asyncio
import typer

from .config import get_settings
from .logging_utils import setup_logging
from .http import PeakonClient
from .storage import MongoStorage
from .ingest import ingest_all
from .scheduler import run_daemon

app = typer.Typer(add_completion=False)


@app.command()
def ingest(full_sync: bool = typer.Option(None, help="Override FULL_SYNC env var (true/false)")) -> None:
    """Run ingestion once and exit."""
    settings = get_settings()
    setup_logging(settings.log_level)

    if full_sync is not None:
        settings.full_sync = full_sync

    async def _main() -> None:
        client = PeakonClient(
            base_url=settings.peakon_base_url,
            app_token=settings.peakon_app_token,
            timeout_seconds=settings.http_timeout_seconds,
        )
        storage = MongoStorage(settings.mongo_uri, settings.mongo_db)
        try:
            await ingest_all(
                client,
                storage,
                company_id=settings.peakon_company_id,
                engagement_group=settings.peakon_engagement_group,
                per_page=settings.peakon_per_page,
                full_sync=settings.full_sync,
            )
        finally:
            await client.aclose()

    asyncio.run(_main())


@app.command()
def daemon() -> None:
    """Run a long-lived scheduler process that executes ingestion weekly."""
    settings = get_settings()
    setup_logging(settings.log_level)
    run_daemon(settings)


if __name__ == "__main__":
    app()
