from datetime import datetime, timedelta

from app.engine.travel import event_window

SLOT_MINUTES = 5


def find_optimal_slot(
    busy: list[tuple[datetime, datetime]],
    duration_minutes: int,
    window_start: datetime,
    window_end: datetime,
    travel_before: int = 0,
    travel_after: int = 0,
) -> tuple[datetime | None, str]:
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return _greedy_slot(busy, duration_minutes, window_start, window_end, travel_before, travel_after), "greedy"

    total_minutes = int((window_end - window_start).total_seconds() // 60)
    needed = (duration_minutes + travel_before + travel_after + SLOT_MINUTES - 1) // SLOT_MINUTES
    horizon = total_minutes // SLOT_MINUTES
    if needed <= 0 or horizon <= 0 or needed > horizon:
        return None, "ortools"

    model = cp_model.CpModel()
    start_slot = model.NewIntVar(0, horizon - needed, "start_slot")
    end_slot = model.NewIntVar(needed, horizon, "end_slot")
    model.Add(end_slot == start_slot + needed)

    interval = model.NewIntervalVar(start_slot, needed, end_slot, "candidate")
    busy_intervals = []
    for index, (busy_start, busy_end) in enumerate(busy):
        start_offset = int((busy_start - window_start).total_seconds() // 60) // SLOT_MINUTES
        end_offset = int((busy_end - window_start).total_seconds() // 60 + SLOT_MINUTES - 1) // SLOT_MINUTES
        start_offset = max(0, min(horizon, start_offset))
        end_offset = max(0, min(horizon, end_offset))
        if end_offset <= start_offset:
            continue
        size = end_offset - start_offset
        busy_intervals.append(
            model.NewFixedSizeIntervalVar(start_offset, size, f"busy_{index}")
        )

    if busy_intervals:
        model.AddNoOverlap([interval, *busy_intervals])
    model.Minimize(start_slot)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1.5
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, "ortools"

    chosen = window_start + timedelta(minutes=solver.Value(start_slot) * SLOT_MINUTES + travel_before)
    return chosen, "ortools"


def _greedy_slot(
    busy: list[tuple[datetime, datetime]],
    duration_minutes: int,
    window_start: datetime,
    window_end: datetime,
    travel_before: int,
    travel_after: int,
) -> datetime | None:
    cursor = window_start
    occupied = sorted(busy, key=lambda item: item[0])
    while cursor + timedelta(minutes=duration_minutes) <= window_end:
        block_start, block_end = event_window(cursor + timedelta(minutes=travel_before), duration_minutes, travel_before, travel_after)
        conflict = any(block_start < end and block_end > start for start, end in occupied)
        if not conflict and block_start >= window_start and block_end <= window_end:
            return cursor + timedelta(minutes=travel_before)
        cursor += timedelta(minutes=SLOT_MINUTES)
    return None
