"""Entry point for Airbnb iCal occupancy tracker."""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.calculator import PropertyOccupancy, calculate_occupancy
from src.config import AppConfig, load_config
from src.exporter import OccupancyReport, build_summary, export_to_json
from src.fetcher import fetch_all_icals
from src.parser import parse_ical
from src.property_meta import load_property_meta
from src.scheduler import run_scheduler
from src.deployer import deploy_to_github_pages
from src.unavailability import (
    FormatOptions,
    format_full_report_text,
    format_property_bookings_per_event_text,
)

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
LOGGER = logging.getLogger(__name__)


def _ensure_utf8_stdio() -> None:
    """Use UTF-8 for stdout/stderr when possible (fixes Cyrillic on Windows consoles)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def setup_logging(log_path: str, verbose: bool) -> None:
    """Configure root logging to file and stdout."""
    log_level = logging.DEBUG if verbose else logging.INFO
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    logging.basicConfig(level=log_level, handlers=[file_handler, stream_handler], force=True)


def _load_previous_properties(output_path: str) -> dict[str, dict]:
    """Load existing report properties by property_id for stale fallback."""
    target = Path(output_path)
    if not target.exists():
        return {}

    try:
        with target.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("Failed to read previous report for stale fallback: %s", exc)
        return {}

    properties = payload.get("properties", [])
    if not isinstance(properties, list):
        return {}

    indexed: dict[str, dict] = {}
    for item in properties:
        if isinstance(item, dict) and isinstance(item.get("property_id"), str):
            indexed[item["property_id"]] = item
    return indexed


def _property_from_stale(previous_item: dict, expected_name: str) -> PropertyOccupancy:
    """Convert stale JSON property payload into PropertyOccupancy."""
    monthly_data = previous_item.get("monthly_data", [])
    normalized_monthly = []
    for month in monthly_data:
        normalized_monthly.append(
            {
                "year": int(month.get("year", 0)),
                "month": int(month.get("month", 0)),
                "month_name": str(month.get("month_name", "")),
                "total_days": int(month.get("total_days", 0)),
                "reserved_days": int(month.get("reserved_days", 0)),
                "blocked_days": int(month.get("blocked_days", 0)),
                "available_days": int(month.get("available_days", 0)),
                "occupancy_rate": float(month.get("occupancy_rate", 0.0)),
                "occupancy_rate_with_blocked": float(month.get("occupancy_rate_with_blocked", 0.0)),
            }
        )

    # Reuse dataclass constructor from calculate module by creating through keyword unpacking.
    from src.calculator import MonthlyOccupancy

    month_objects = [MonthlyOccupancy(**item) for item in normalized_monthly]
    return PropertyOccupancy(
        property_id=str(previous_item.get("property_id", "")),
        property_name=str(previous_item.get("property_name", expected_name)),
        last_updated=str(previous_item.get("last_updated", "")),
        total_upcoming_reservations=int(previous_item.get("total_upcoming_reservations", 0)),
        next_checkin=previous_item.get("next_checkin"),
        monthly_data=month_objects,
        stale=True,
        unavailable_ranges_text=str(previous_item.get("unavailable_ranges_text", "")),
    )


def _reserved_nights_next_30_days(all_properties_events: list[list]) -> int:
    """Calculate total reserved nights for next 30 days across properties."""
    today = date.today()
    horizon = today + timedelta(days=30)
    total = 0
    for events in all_properties_events:
        for event in events:
            if not event.is_reservation:
                continue
            overlap_start = max(event.start_date, today)
            overlap_end = min(event.end_date, horizon)
            if overlap_start < overlap_end:
                total += (overlap_end - overlap_start).days
    return total


def run_pipeline(
    config: AppConfig,
    *,
    print_unavailable: bool = False,
    unavailable_compact: bool = False,
    unavailable_iso_dates: bool = False,
    include_ical_blocks: bool = False,
    no_html_calendar: bool = False,
) -> None:
    """Execute one full sync cycle: fetch, parse, calculate, export."""
    LOGGER.info("Starting occupancy update cycle for %s properties", len(config.properties))
    previous_properties = _load_previous_properties(config.settings.output_path)

    all_events_dict: dict[str, list] = {p.id: [] for p in config.properties}

    fetched = fetch_all_icals(
        properties=config.properties,
        timeout=config.settings.request_timeout,
        delay=config.settings.request_delay,
    )

    property_reports: list[PropertyOccupancy] = []
    all_events_for_summary = []
    unavailability_sections: list[str] = []

    for property_config in config.properties:
        content = fetched.get(property_config.id)
        if content is None:
            stale_data = previous_properties.get(property_config.id)
            if stale_data:
                stale_property = _property_from_stale(stale_data, expected_name=property_config.name)
                stale_property.stale = True
                property_reports.append(stale_property)
                if print_unavailable:
                    stale_txt = stale_property.unavailable_ranges_text.strip()
                    if stale_txt:
                        unavailability_sections.append(stale_txt + "\n  (данные из предыдущего отчёта, stale)")
                    else:
                        unavailability_sections.append(
                            f"[{property_config.id}] {property_config.name}\n"
                            "  (stale: текст диапазонов отсутствует в сохранённом файле)\n"
                        )
                LOGGER.warning("Using stale data for property=%s", property_config.id)
            else:
                LOGGER.warning(
                    "Skipping property=%s because fetch failed and no stale data is available",
                    property_config.id,
                )
            continue

        try:
            events = parse_ical(content)
            all_events_dict[property_config.id] = events
            occupancy = calculate_occupancy(
                property_id=property_config.id,
                property_name=property_config.name,
                events=events,
                months_ahead=config.settings.months_ahead,
            )
            occupancy.unavailable_ranges_text = format_property_bookings_per_event_text(
                property_config.id,
                property_config.name,
                events,
                options=FormatOptions(
                    include_blocks=include_ical_blocks,
                    full_year=unavailable_compact,
                    iso_dates=unavailable_iso_dates,
                ),
            )
            property_reports.append(occupancy)
            all_events_for_summary.append(events)
            if print_unavailable:
                unavailability_sections.append(occupancy.unavailable_ranges_text.rstrip())
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.error("Failed processing property=%s: %s", property_config.id, exc)
            stale_data = previous_properties.get(property_config.id)
            if stale_data:
                stale_property = _property_from_stale(stale_data, expected_name=property_config.name)
                stale_property.stale = True
                property_reports.append(stale_property)
                if print_unavailable:
                    stale_txt = stale_property.unavailable_ranges_text.strip()
                    if stale_txt:
                        unavailability_sections.append(stale_txt + "\n  (данные из предыдущего отчёта после ошибки парсинга)")
                    else:
                        unavailability_sections.append(
                            f"[{property_config.id}] {property_config.name}\n"
                            "  (ошибка обработки; нет сохранённых диапазонов)\n"
                        )
                LOGGER.warning("Fallback to stale data after processing failure for %s", property_config.id)

    property_reports.sort(key=lambda item: item.property_id)

    total_reserved_nights_30_days = _reserved_nights_next_30_days(all_events_for_summary)
    summary = build_summary(property_reports, total_reserved_nights_30_days)
    report = OccupancyReport(
        generated_at=datetime.now(BANGKOK_TZ).isoformat(),
        properties_count=len(config.properties),
        properties=property_reports,
        summary=summary,
    )

    export_to_json(report, config.settings.output_path)
    LOGGER.info(
        "Occupancy update finished. Exported %s properties to %s",
        len(property_reports),
        config.settings.output_path,
    )

    if not no_html_calendar:
        html_output_path = config.settings.output_path.replace(".json", "_calendar.html")
        try:
            from src.html_calendar import export_calendar_html

            export_calendar_html(
                config.properties,
                all_events_dict,
                html_output_path,
                property_meta=load_property_meta(),
            )
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.error("Failed to generate HTML calendar: %s", exc, exc_info=True)

        # Deploy to GitHub Pages
        if config.deployment:
            try:
                deploy_to_github_pages(html_output_path, config.deployment)
            except Exception:  # pylint: disable=broad-except
                LOGGER.exception("Deployment to GitHub Pages failed (non-fatal).")

    if print_unavailable and unavailability_sections:
        text = format_full_report_text(unavailability_sections)
        print(text, flush=True)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Airbnb iCal occupancy tracker")
    parser.add_argument("--config", default="./config.yaml", help="Path to config.yaml")
    parser.add_argument("--run-once", action="store_true", help="Run one sync and exit")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    parser.add_argument(
        "--print-unavailable",
        dest="print_unavailable",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Print merged unavailable date ranges to stdout (default: on with --run-once)",
    )
    parser.add_argument(
        "--unavailable-compact",
        action="store_true",
        help="Always dd.mm.yyyy - dd.mm.yyyy in booking lines (stored in JSON / --print-unavailable)",
    )
    parser.add_argument(
        "--unavailable-iso-dates",
        action="store_true",
        help="Booking lines as YYYY-MM-DD - YYYY-MM-DD (with --print-unavailable / JSON)",
    )
    parser.add_argument(
        "--include-ical-blocks",
        action="store_true",
        help="Also list «Not available» blocks as separate lines (default: only non-blocked / брони)",
    )
    parser.add_argument(
        "--no-html-calendar",
        action="store_true",
        help="Skip HTML calendar generation",
    )
    return parser.parse_args()


def main() -> None:
    """Application entry point."""
    _ensure_utf8_stdio()
    args = parse_args()
    config = load_config(args.config)
    setup_logging(config.settings.log_path, args.verbose)

    print_unavailable = args.print_unavailable
    if print_unavailable is None:
        print_unavailable = bool(args.run_once)

    if args.run_once:
        run_pipeline(
            config,
            print_unavailable=print_unavailable,
            unavailable_compact=args.unavailable_compact,
            unavailable_iso_dates=args.unavailable_iso_dates,
            include_ical_blocks=args.include_ical_blocks,
            no_html_calendar=args.no_html_calendar,
        )
        return

    run_scheduler(
        job=lambda: run_pipeline(
            config,
            print_unavailable=print_unavailable,
            unavailable_compact=args.unavailable_compact,
            unavailable_iso_dates=args.unavailable_iso_dates,
            include_ical_blocks=args.include_ical_blocks,
            no_html_calendar=args.no_html_calendar,
        ),
        cron_expr=config.settings.update_cron,
    )


if __name__ == "__main__":
    main()
