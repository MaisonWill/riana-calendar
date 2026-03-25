"""Occupancy calculations based on parsed booking events."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.parser import BookingEvent

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")


@dataclass(slots=True)
class MonthlyOccupancy:
    """Occupancy metrics for one calendar month."""

    year: int
    month: int
    month_name: str
    total_days: int
    reserved_days: int
    blocked_days: int
    available_days: int
    occupancy_rate: float
    occupancy_rate_with_blocked: float


@dataclass(slots=True)
class PropertyOccupancy:
    """Occupancy report for one property."""

    property_id: str
    property_name: str
    last_updated: str
    total_upcoming_reservations: int
    next_checkin: str | None
    monthly_data: list[MonthlyOccupancy]
    stale: bool = False
    unavailable_ranges_text: str = ""


def _month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def _next_month(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def _month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


def calculate_occupancy(
    property_id: str,
    property_name: str,
    events: list[BookingEvent],
    months_ahead: int = 6,
) -> PropertyOccupancy:
    """Calculate occupancy metrics for current and upcoming months.

    Args:
        property_id: Internal property identifier.
        property_name: Human-readable property name.
        events: Parsed booking events.
        months_ahead: Number of months to calculate from current month.

    Returns:
        Property occupancy report.
    """
    today = date.today()
    now_iso = datetime.now(BANGKOK_TZ).isoformat()

    reservation_events = [event for event in events if event.is_reservation]
    blocked_events = [event for event in events if event.is_blocked]

    next_checkin_date: date | None = None
    future_checkins = sorted(
        [event.start_date for event in reservation_events if event.start_date >= today]
    )
    if future_checkins:
        next_checkin_date = future_checkins[0]

    monthly_data: list[MonthlyOccupancy] = []
    cursor = _month_start(today.year, today.month)

    for _ in range(months_ahead):
        month_begin = cursor
        month_end = _next_month(month_begin)
        window_start = max(month_begin, today)
        window_end = month_end

        total_days = max(0, (window_end - window_start).days)
        month_dates = {window_start + timedelta(days=i) for i in range(total_days)}

        reserved_dates: set[date] = set()
        for event in reservation_events:
            overlap_start = max(event.start_date, window_start)
            overlap_end = min(event.end_date, window_end)
            if overlap_start >= overlap_end:
                continue
            day = overlap_start
            while day < overlap_end:
                reserved_dates.add(day)
                day += timedelta(days=1)

        blocked_dates: set[date] = set()
        for event in blocked_events:
            overlap_start = max(event.start_date, window_start)
            overlap_end = min(event.end_date, window_end)
            if overlap_start >= overlap_end:
                continue
            day = overlap_start
            while day < overlap_end:
                blocked_dates.add(day)
                day += timedelta(days=1)

        blocked_only_dates = blocked_dates - reserved_dates
        reserved_days = len(reserved_dates & month_dates)
        blocked_days = len(blocked_only_dates & month_dates)
        available_days = max(0, total_days - reserved_days - blocked_days)

        occupancy_rate = round((reserved_days / total_days * 100), 1) if total_days else 0.0
        occupancy_rate_with_blocked = (
            round(((reserved_days + blocked_days) / total_days * 100), 1) if total_days else 0.0
        )

        monthly_data.append(
            MonthlyOccupancy(
                year=month_begin.year,
                month=month_begin.month,
                month_name=_month_label(month_begin.year, month_begin.month),
                total_days=total_days,
                reserved_days=reserved_days,
                blocked_days=blocked_days,
                available_days=available_days,
                occupancy_rate=occupancy_rate,
                occupancy_rate_with_blocked=occupancy_rate_with_blocked,
            )
        )

        cursor = month_end

    return PropertyOccupancy(
        property_id=property_id,
        property_name=property_name,
        last_updated=now_iso,
        total_upcoming_reservations=len([event for event in reservation_events if event.end_date > today]),
        next_checkin=next_checkin_date.isoformat() if next_checkin_date else None,
        monthly_data=monthly_data,
        stale=False,
        unavailable_ranges_text="",
    )

