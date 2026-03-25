"""iCal parsing and booking-event extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from icalendar import Calendar


@dataclass(slots=True)
class BookingEvent:
    """Normalized event extracted from a VEVENT block."""

    start_date: date
    end_date: date
    nights: int
    summary: str
    uid: str
    is_reservation: bool
    is_blocked: bool


def _to_date(value: date | datetime) -> date:
    """Convert datetime/date from iCalendar component to date."""
    if isinstance(value, datetime):
        return value.date()
    return value


def _classify_summary(summary: str) -> tuple[bool, bool]:
    """Classify event type from SUMMARY value.

    Airbnb iCal feeds only contain blocked/reserved dates (never available
    ones), so every event represents an unavailable period.  We distinguish
    between genuine guest reservations (``is_reservation=True``) and dates
    the host blocked manually (``is_blocked=True``).  When the summary is
    empty or unrecognised we still mark the event as blocked so it shows up
    as unavailable.
    """
    normalized = (summary or "").strip().lower()

    # Genuine reservation
    if normalized == "reserved":
        return True, False

    # Manually blocked by host – various Airbnb wordings
    if "not available" in normalized:
        return False, True

    # Any other or empty summary – treat as blocked/unavailable to be safe
    return False, True


def parse_ical(ical_content: str) -> list[BookingEvent]:
    """Parse Airbnb iCal payload into booking events.

    Args:
        ical_content: Raw .ics text content.

    Returns:
        Future events sorted by start date.
    """
    calendar = Calendar.from_ical(ical_content)
    today = date.today()
    events: list[BookingEvent] = []

    for component in calendar.walk("VEVENT"):
        dtstart = component.get("dtstart")
        dtend = component.get("dtend")
        if dtstart is None or dtend is None:
            continue

        start_date = _to_date(dtstart.dt)
        end_date = _to_date(dtend.dt)
        if end_date <= today:
            continue
        if end_date <= start_date:
            continue

        summary = str(component.get("summary", "")).strip()
        uid = str(component.get("uid", "")).strip()
        is_reservation, is_blocked = _classify_summary(summary)

        events.append(
            BookingEvent(
                start_date=start_date,
                end_date=end_date,
                nights=(end_date - start_date).days,
                summary=summary,
                uid=uid,
                is_reservation=is_reservation,
                is_blocked=is_blocked,
            )
        )

    events.sort(key=lambda item: item.start_date)
    return events


def get_occupied_dates(events: list[BookingEvent], include_blocked: bool = True) -> set[date]:
    """Expand booking ranges into occupied dates.

    Args:
        events: Booking events.
        include_blocked: Include blocked events in output set.

    Returns:
        Set of occupied dates where DTEND is excluded.
    """
    occupied: set[date] = set()
    for event in events:
        if event.is_reservation:
            use_event = True
        elif event.is_blocked and include_blocked:
            use_event = True
        else:
            use_event = False

        if not use_event:
            continue

        day = event.start_date
        while day < event.end_date:
            occupied.add(day)
            day += timedelta(days=1)

    return occupied


# Alias for integrations (e.g. HTML calendar export) that expect an "iCal event" type name.
ICalEvent = BookingEvent

