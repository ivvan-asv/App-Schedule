from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine.csp import find_optimal_slot
from app.services.llm import _parse_heuristic


def test_heuristic_extracts_spanish_meeting():
    tz = "America/Argentina/Buenos_Aires"
    parsed = _parse_heuristic(
        "Agendá mañana a las 15 una reunión con Ana en Palermo",
        tz,
        origin_location="Microcentro",
    )
    assert "Ana" in parsed.attendees
    assert parsed.location == "Palermo"
    assert parsed.start_time.hour == 15
    assert parsed.needs_travel is True
    assert parsed.duration_minutes == 30


def test_csp_avoids_busy_block():
    tz = ZoneInfo("UTC")
    start = datetime(2026, 10, 2, 9, 0, tzinfo=tz)
    end = datetime(2026, 10, 2, 18, 0, tzinfo=tz)
    busy = [
        (datetime(2026, 10, 2, 9, 0, tzinfo=tz), datetime(2026, 10, 2, 10, 0, tzinfo=tz)),
        (datetime(2026, 10, 2, 10, 15, tzinfo=tz), datetime(2026, 10, 2, 12, 0, tzinfo=tz)),
    ]
    suggested, solver = find_optimal_slot(
        busy=busy,
        duration_minutes=45,
        window_start=start,
        window_end=end,
        travel_before=15,
    )
    assert suggested is not None
    assert solver in {"ortools", "greedy"}
    assert suggested >= start + timedelta(minutes=15)
    for busy_start, busy_end in busy:
        block_start = suggested - timedelta(minutes=15)
        block_end = suggested + timedelta(minutes=45)
        assert not (block_start < busy_end and block_end > busy_start)
