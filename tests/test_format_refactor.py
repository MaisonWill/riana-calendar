from datetime import date
from dataclasses import dataclass

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

import sys
from unittest.mock import MagicMock

# Mock src.parser before importing src.unavailability
mock_parser = MagicMock()
mock_parser.BookingEvent = BookingEvent
sys.modules["src.parser"] = mock_parser

from src.unavailability import format_property_bookings_per_event_text, FormatOptions

def test_refactor():
    events = [
        BookingEvent(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            nights=4,
            is_blocked=False,
            is_reservation=True,
            summary="Reservation 1",
            uid="uid1"
        ),
        BookingEvent(
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 5),
            nights=4,
            is_blocked=True,
            is_reservation=False,
            summary="Blocked 1",
            uid="uid2"
        )
    ]

    # Test default options
    options_default = FormatOptions()
    text_default = format_property_bookings_per_event_text("prop1", "Property 1", events, options=options_default)
    print("--- Default Options ---")
    print(text_default)
    # assert "Reservation 1" not in text_default # Summary is not in output
    assert "01.01 - 05.01 (4 ноч.)" in text_default
    assert "01.02 - 05.02" not in text_default
    assert "События календаря" not in text_default
    assert "Бронирования" in text_default

    # Test include_blocks=True
    options_blocks = FormatOptions(include_blocks=True)
    text_blocks = format_property_bookings_per_event_text("prop1", "Property 1", events, options=options_blocks)
    print("--- Include Blocks ---")
    print(text_blocks)
    assert "01.01 - 05.01 (4 ноч.)" in text_blocks
    assert "01.02 - 05.02 (4 ноч.)" in text_blocks
    assert "События календаря" in text_blocks

    # Test full_year=True
    options_year = FormatOptions(full_year=True)
    text_year = format_property_bookings_per_event_text("prop1", "Property 1", events, options=options_year)
    print("--- Full Year ---")
    print(text_year)
    assert "01.01.2024 - 05.01.2024 (4 ноч.)" in text_year

    # Test iso_dates=True
    options_iso = FormatOptions(iso_dates=True)
    text_iso = format_property_bookings_per_event_text("prop1", "Property 1", events, options=options_iso)
    print("--- ISO Dates ---")
    print(text_iso)
    assert "2024-01-01 - 2024-01-05 (4 ноч.)" in text_iso

    print("All tests passed!")

if __name__ == "__main__":
    test_refactor()
