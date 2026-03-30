"""External ping (Healthchecks.io) + internal DB heartbeat record."""

from __future__ import annotations

import platform

import httpx
import structlog

log = structlog.get_logger()


async def ping_healthchecks(url: str | None, *, success: bool = True) -> None:
    """Fire-and-forget HTTP GET to Healthchecks.io ping URL.

    Args:
        url: The Healthchecks.io ping URL. If None or empty, silently returns.
        success: If True, ping the success endpoint. If False, ping /fail.
    """
    if not url:
        return

    target = url if success else f"{url.rstrip('/')}/fail"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(target)
            log.debug("healthchecks_pinged", url=target, status=resp.status_code)
    except Exception:
        log.warning("healthchecks_ping_failed", url=target, exc_info=True)


async def record_heartbeat(
    db,
    *,
    service_name: str = "find-hub-tracker",
    host: str | None = None,
    poll_count: int = 0,
    error_count: int = 0,
    version: str | None = None,
) -> None:
    """Write a heartbeat record to the database.

    Args:
        db: Database backend implementing upsert_heartbeat().
        service_name: Name of the service.
        host: Hostname where the service is running. Defaults to platform.node().
        poll_count: Total successful polls since startup.
        error_count: Total failed polls since startup.
        version: Service version (git hash or semver).
    """
    resolved_host = host or platform.node() or "unknown"

    try:
        await db.upsert_heartbeat(
            service_name=service_name,
            host=resolved_host,
            poll_count=poll_count,
            error_count=error_count,
            version=version,
        )
        log.debug(
            "heartbeat_recorded",
            service=service_name,
            host=resolved_host,
            polls=poll_count,
            errors=error_count,
        )
    except Exception:
        log.warning("heartbeat_record_failed", exc_info=True)


async def get_heartbeat_status(
    db,
    service_name: str = "find-hub-tracker",
    host: str | None = None,
) -> dict | None:
    """Retrieve current heartbeat info for the CLI status command.

    Args:
        db: Database backend implementing get_heartbeat().
        service_name: Name of the service.
        host: Hostname to query. Defaults to platform.node().

    Returns:
        Dict with heartbeat info, or None if no heartbeat found.
    """
    resolved_host = host or platform.node() or "unknown"
    return await db.get_heartbeat(service_name, resolved_host)
