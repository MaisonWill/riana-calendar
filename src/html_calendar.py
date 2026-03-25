"""Generate standalone HTML calendar page from parsed iCal data."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import PropertyConfig
    from src.parser import ICalEvent

from src.property_meta import PropertyExtras

LOGGER = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "calendar.html"


def _build_calendar_data(
    properties: list[PropertyConfig],
    all_events: dict[str, list[ICalEvent]],
    property_meta: dict[str, PropertyExtras] | None = None,
) -> dict:
    """Build JSON structure for the HTML template."""
    today = date.today()
    horizon = today + timedelta(days=366)

    meta = property_meta or {}
    props_list: list[dict] = []
    bookings_dict: dict[str, list[dict[str, str]]] = {}

    blocked_dict: dict[str, list[dict[str, str]]] = {}

    for prop in properties:
        ex = meta.get(prop.id, PropertyExtras())
        label = (ex.display_name or "").strip() or prop.name
        props_list.append(
            {
                "id": prop.id,
                "name": label,
                "display_name": label,
                "bedrooms": ex.bedrooms,
                "bathrooms": ex.bathrooms,
                "photos_url": ex.google_drive_photos_url or "",
            }
        )
        events = all_events.get(prop.id, [])
        reservation_ranges: list[dict[str, str]] = []
        blocked_ranges: list[dict[str, str]] = []
        for ev in events:
            # Clip to [today, horizon); ev.end_date is exclusive checkout in iCal
            s = max(ev.start_date, today)
            e = min(ev.end_date, horizon)
            if s >= e:
                continue
            last_night = e - timedelta(days=1)
            nights = (e - s).days  # number of nights
            entry = {
                "start": s.isoformat(),
                # inclusive last night for the template JS (loops d0..d1 inclusive)
                "end": last_night.isoformat(),
                "nights": nights,
            }
            if ev.is_reservation:
                reservation_ranges.append(entry)
            elif ev.is_blocked:
                blocked_ranges.append(entry)
            else:
                # Safety net: treat any unclassified event as blocked
                blocked_ranges.append(entry)
        bookings_dict[prop.id] = reservation_ranges
        blocked_dict[prop.id] = blocked_ranges

    return {
        "properties": props_list,
        "bookings": bookings_dict,
        "blocked": blocked_dict,
        "generated_at": datetime.now().isoformat(),
    }


def export_calendar_html(
    properties: list[PropertyConfig],
    all_events: dict[str, list[ICalEvent]],
    output_path: str,
    property_meta: dict[str, PropertyExtras] | None = None,
) -> None:
    """Generate standalone HTML calendar file."""
    if not _TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f"Calendar template not found: {_TEMPLATE_PATH}")

    data = _build_calendar_data(properties, all_events, property_meta=property_meta)
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    data_json = data_json.replace("</", "<\\/")

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    marker_start = "// ===CALENDAR_DATA_START==="
    marker_end = "// ===CALENDAR_DATA_END==="

    idx_start = template.index(marker_start)
    idx_end = template.index(marker_end) + len(marker_end)

    html = (
        template[:idx_start]
        + f"const CALENDAR_DATA = {data_json};"
        + template[idx_end:]
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    LOGGER.info("Calendar HTML exported to %s", output_path)
