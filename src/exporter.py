"""JSON report models and exporting helpers."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from src.calculator import PropertyOccupancy


@dataclass(slots=True)
class OccupancyReport:
    """Final report model written to JSON."""

    generated_at: str
    properties_count: int
    properties: list[PropertyOccupancy]
    summary: dict[str, float | int | str]


def build_summary(
    properties: list[PropertyOccupancy],
    total_reserved_nights_30_days: int,
) -> dict[str, float | int | str]:
    """Build aggregated metrics for all properties."""
    if not properties:
        return {
            "average_occupancy_current_month": 0.0,
            "average_occupancy_next_month": 0.0,
            "most_occupied_property": "",
            "least_occupied_property": "",
            "total_reserved_nights_30_days": 0,
        }

    current_month_values: list[float] = []
    next_month_values: list[float] = []
    score_map: dict[str, float] = {}

    for property_report in properties:
        if property_report.monthly_data:
            current_month_values.append(property_report.monthly_data[0].occupancy_rate)
            score_map[property_report.property_id] = property_report.monthly_data[0].occupancy_rate
        if len(property_report.monthly_data) > 1:
            next_month_values.append(property_report.monthly_data[1].occupancy_rate)

    most_occupied_property = max(score_map, key=score_map.get) if score_map else ""
    least_occupied_property = min(score_map, key=score_map.get) if score_map else ""

    return {
        "average_occupancy_current_month": round(
            sum(current_month_values) / len(current_month_values), 1
        )
        if current_month_values
        else 0.0,
        "average_occupancy_next_month": round(sum(next_month_values) / len(next_month_values), 1)
        if next_month_values
        else 0.0,
        "most_occupied_property": most_occupied_property,
        "least_occupied_property": least_occupied_property,
        "total_reserved_nights_30_days": total_reserved_nights_30_days,
    }


def export_to_json(report: OccupancyReport, output_path: str) -> None:
    """Write report JSON atomically.

    Args:
        report: Fully prepared report.
        output_path: Target JSON path.
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = target.with_suffix(f"{target.suffix}.tmp")
    payload = asdict(report)

    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    os.replace(tmp_path, target)

