from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Iterable


@dataclass(frozen=True)
class CalendarSlotEvent:
    start: datetime
    end: datetime
    title: str = ""


def _parse_iso(iso_str: str) -> datetime:
    # Handles "YYYY-MM-DDTHH:MM:SS" and "YYYY-MM-DD HH:MM" variants.
    s = (iso_str or "").strip()
    if not s:
        raise ValueError("Empty ISO datetime")
    return datetime.fromisoformat(s.replace(" ", "T"))


def suggest_meeting_time(
    events: Iterable[CalendarSlotEvent],
    duration_hours: int = 1,
    *,
    working_start_hour: int = 9,
    working_end_hour: int = 17,
    now: datetime | None = None,
    search_days: int = 14,
) -> datetime:
    """
    Suggest the next available slot that doesn't overlap existing events.
    """
    now = now or datetime.now()
    candidate = now.replace(minute=0, second=0, microsecond=0)
    if candidate < now:
        candidate += timedelta(hours=1)

    events_list = list(events)

    for day_offset in range(search_days):
        day = (candidate + timedelta(days=day_offset)).date()

        work_start = datetime.combine(day, time(hour=working_start_hour))
        work_end = datetime.combine(day, time(hour=working_end_hour))

        # Start at the later of current candidate or working hours start.
        slot_start = max(candidate, work_start)

        while slot_start + timedelta(hours=duration_hours) <= work_end:
            slot_end = slot_start + timedelta(hours=duration_hours)
            overlaps = any(
                (e.start < slot_end and slot_start < e.end) for e in events_list
            )
            if not overlaps:
                return slot_start
            slot_start += timedelta(hours=1)

        # Move candidate to next day start.
        candidate = datetime.combine(day + timedelta(days=1), time(hour=working_start_hour))

    raise RuntimeError("No available meeting slot found in the search window.")


def events_from_db_rows(db_rows: Iterable[object]) -> list[CalendarSlotEvent]:
    out: list[CalendarSlotEvent] = []
    for row in db_rows:
        # Support both ORM-like objects (with attributes) and plain dict rows.
        start_iso = getattr(row, "start_iso", None) if not isinstance(row, dict) else row.get("start_iso")
        end_iso = getattr(row, "end_iso", None) if not isinstance(row, dict) else row.get("end_iso")
        title_val = getattr(row, "title", None) if not isinstance(row, dict) else row.get("title")
        out.append(
            CalendarSlotEvent(
                start=_parse_iso(start_iso),
                end=_parse_iso(end_iso),
                title=str(title_val or ""),
            )
        )
    return out

