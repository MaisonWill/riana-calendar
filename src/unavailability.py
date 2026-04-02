"""Build merged date ranges for nights unavailable for booking (reserved + blocked)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.parser import BookingEvent, get_occupied_dates


@dataclass(frozen=True, slots=True)
class FormatOptions:
    """Options for formatting booking events report."""

    include_blocks: bool = False
    full_year: bool = False
    iso_dates: bool = False


@dataclass(frozen=True, slots=True)
class UnavailableRange:
    """One contiguous stretch of unavailable nights.

    Airbnb iCal uses [start_date, end_date) for nights: first night is start_date,
    end_date is checkout (first morning the listing is free).
    """

    first_night: date
    checkout_day: date  # exclusive upper bound (first bookable morning after stay)

    @property
    def nights(self) -> int:
        """Number of unavailable nights in this range."""
        return (self.checkout_day - self.first_night).days


def merge_occupied_dates_to_ranges(occupied: set[date]) -> list[UnavailableRange]:
    """Merge consecutive calendar dates into half-open ranges [first_night, checkout_day).

    Args:
        occupied: Set of dates on which at least one night is unavailable.

    Returns:
        Sorted non-overlapping ranges.
    """
    if not occupied:
        return []

    sorted_dates = sorted(occupied)
    ranges: list[UnavailableRange] = []
    block_start = sorted_dates[0]
    block_last_night = sorted_dates[0]

    for current in sorted_dates[1:]:
        if current == block_last_night + timedelta(days=1):
            block_last_night = current
            continue
        ranges.append(
            UnavailableRange(
                first_night=block_start,
                checkout_day=block_last_night + timedelta(days=1),
            )
        )
        block_start = current
        block_last_night = current

    ranges.append(
        UnavailableRange(
            first_night=block_start,
            checkout_day=block_last_night + timedelta(days=1),
        )
    )
    return ranges


def build_unavailable_ranges(events: list[BookingEvent]) -> list[UnavailableRange]:
    """Collect reserved + blocked nights and merge into contiguous ranges.

    Args:
        events: Parsed VEVENT-derived events (future only in parse_ical).

    Returns:
        Merged ranges covering all nights unavailable for new bookings.
    """
    occupied = get_occupied_dates(events, include_blocked=True)
    return merge_occupied_dates_to_ranges(occupied)


def format_range_line_ru(rng: UnavailableRange, *, iso_dates: bool = False) -> str:
    """Format one range as a human-readable Russian line.

    Args:
        rng: Unavailability range.
        iso_dates: If True, use YYYY-MM-DD instead of DD.MM.YYYY.

    Returns:
        Single-line description.
    """
    if iso_dates:
        start_s = rng.first_night.isoformat()
        out_s = rng.checkout_day.isoformat()
        last_night_s = (rng.checkout_day - timedelta(days=1)).isoformat()
    else:
        start_s = rng.first_night.strftime("%d.%m.%Y")
        out_s = rng.checkout_day.strftime("%d.%m.%Y")
        last_night_s = (rng.checkout_day - timedelta(days=1)).strftime("%d.%m.%Y")

    n = rng.nights
    return (
        f"  • заезд {start_s}, выезд {out_s}  "
        f"({n} ноч.; заняты ночи с {start_s} по {last_night_s})"
    )


def format_range_line_ru_compact(rng: UnavailableRange) -> str:
    """Shorter line: заезд — выезд (ночей)."""
    start_s = rng.first_night.strftime("%d.%m.%Y")
    out_s = rng.checkout_day.strftime("%d.%m.%Y")
    return f"  • {start_s} → {out_s}  ({rng.nights} ноч.)"


def format_property_unavailability_text(
    property_id: str,
    property_name: str,
    events: list[BookingEvent],
    *,
    compact: bool = False,
    iso_dates: bool = False,
) -> str:
    """Build multi-line Russian report for one property.

    Args:
        property_id: Property id from config.
        property_name: Display name.
        events: Parsed events for this listing.
        compact: Use shorter bullet lines.
        iso_dates: Use ISO date format in non-compact lines.

    Returns:
        Full text block (may be empty if no unavailable nights).
    """
    ranges = build_unavailable_ranges(events)
    header = f"[{property_id}] {property_name}"
    if not ranges:
        return f"{header}\n  (нет будущих недоступных дат по iCal)\n"

    lines = [
        header,
        "  Недоступно для бронирования (диапазоны ночей; дата выезда — первый свободный день):",
    ]
    for rng in ranges:
        if compact:
            lines.append(format_range_line_ru_compact(rng))
        else:
            lines.append(format_range_line_ru(rng, iso_dates=iso_dates))
    lines.append("")
    return "\n".join(lines)


def format_full_report_text(
    sections: list[str],
    *,
    title: str = "Бронирования по объектам (iCal, каждое событие отдельно)",
) -> str:
    """Join property sections with a header."""
    body = "\n".join(sections).rstrip() + "\n"
    return f"{title}\n{'=' * len(title)}\n\n{body}"


def _format_event_one_line(event: BookingEvent, *, full_year: bool, iso_dates: bool) -> str:
    """One VEVENT as: dd.mm - dd.mm (N ноч.), optional ISO YYYY-MM-DD."""
    start_d = event.start_date
    end_d = event.end_date  # checkout day (exclusive)
    n = event.nights
    if iso_dates:
        line = f"{start_d.isoformat()} - {end_d.isoformat()} ({n} ноч.)"
    elif full_year or start_d.year != end_d.year:
        line = f"{start_d:%d.%m.%Y} - {end_d:%d.%m.%Y} ({n} ноч.)"
    else:
        line = f"{start_d:%d.%m} - {end_d:%d.%m} ({n} ноч.)"
    return f"  • {line}"


def format_property_bookings_per_event_text(
    property_id: str,
    property_name: str,
    events: list[BookingEvent],
    *,
    options: FormatOptions,
) -> str:
    """Text report: each calendar event on its own line, no merging.

    By default lists only non-blocked events (бронирования и синхронизация, не «Not available»).

    Args:
        property_id: Property id from config.
        property_name: Display name.
        events: Parsed future events from parse_ical.
        options: Formatting options (blocks, year format, ISO dates).

    Returns:
        Multi-line block for one property.
    """
    header = f"[{property_id}] {property_name}"
    rows: list[BookingEvent] = []
    for event in events:
        if options.include_blocks:
            rows.append(event)
        elif not event.is_blocked:
            rows.append(event)
    rows.sort(key=lambda e: (e.start_date, e.end_date, e.uid))

    if not rows:
        empty_note = (
            "(нет бронирований по iCal)"
            if not options.include_blocks
            else "(нет событий в iCal)"
        )
        hint = (
            ""
            if options.include_blocks
            else " — только блокировки? Запустите с --include-ical-blocks"
        )
        return f"{header}\n  {empty_note}{hint}\n"

    sub = (
        "  События календаря (каждое отдельно, без склейки):"
        if options.include_blocks
        else "  Бронирования (каждое событие отдельно, без склейки):"
    )
    lines = [header, sub]
    for event in rows:
        lines.append(
            _format_event_one_line(
                event, full_year=options.full_year, iso_dates=options.iso_dates
            )
        )
    lines.append("")
    return "\n".join(lines)
