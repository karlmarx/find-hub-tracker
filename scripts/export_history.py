# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "asyncpg>=0.30.0",
#     "aiosqlite>=0.20.0",
#     "pydantic>=2.0",
#     "pydantic-settings>=2.0",
#     "click>=8.1",
#     "structlog>=24.0",
# ]
# ///
"""Export location history from the database to CSV or JSON.

Usage:
    uv run scripts/export_history.py --format csv --device "Pixel 9 Pro Fold" \
        --days 30 --output locations.csv
    uv run scripts/export_history.py --format json --output all_locations.json
"""

import asyncio
import csv
import io
import json
import sys
from pathlib import Path

import click

# Ensure the project src is on sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))


@click.command()
@click.option(
    "--format", "fmt", type=click.Choice(["csv", "json"]), default="json", help="Output format"
)
@click.option("--output", "-o", default=None, help="Output file (default: stdout)")
@click.option("--device", "-d", default=None, help="Filter by device name")
@click.option("--days", default=None, type=int, help="Limit to last N days")
def export(fmt: str, output: str | None, device: str | None, days: int | None) -> None:
    """Export location history to CSV or JSON."""
    asyncio.run(_export(fmt, output, device, days))


async def _export(fmt: str, output: str | None, device: str | None, days: int | None) -> None:
    from find_hub_tracker.config import get_settings
    from find_hub_tracker.db import create_backend

    settings = get_settings()
    db = create_backend(settings)
    await db.connect()
    await db.migrate()

    try:
        # Resolve device name to device_id if needed
        device_id = None
        if device:
            all_devices = await db.get_all_devices()
            for dev in all_devices:
                if dev.name.lower() == device.lower():
                    device_id = dev.device_id
                    break
            if device_id is None:
                click.echo(f"Device '{device}' not found in database.", err=True)
                sys.exit(1)

        rows = await db.export_locations(device_id, days)
        if not rows:
            click.echo("No location data found.", err=True)
            return

        if fmt == "json":
            text = json.dumps(rows, indent=2, default=str)
            if output:
                Path(output).write_text(text)
                click.echo(f"Exported {len(rows)} records to {output}")
            else:
                click.echo(text)

        elif fmt == "csv":
            fieldnames = list(rows[0].keys())
            if output:
                with open(output, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                click.echo(f"Exported {len(rows)} records to {output}")
            else:
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
                click.echo(buf.getvalue())
    finally:
        await db.close()


if __name__ == "__main__":
    export()
