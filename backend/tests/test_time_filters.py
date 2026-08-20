from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.main import resolve_time_bounds


def test_resolves_exact_time_bounds_in_utc():
    start = datetime(2026, 7, 29, 10, 30, tzinfo=timezone.utc)
    end = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)

    since, until, window_minutes = resolve_time_bounds(start=start, end=end)

    assert since == start
    assert until == end
    assert window_minutes == 90


def test_exact_time_bounds_require_both_values():
    with pytest.raises(HTTPException, match="Both start and end"):
        resolve_time_bounds(start=datetime(2026, 7, 29, 10, 30, tzinfo=timezone.utc))


def test_exact_time_bounds_reject_reversed_range():
    start = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 29, 10, 30, tzinfo=timezone.utc)

    with pytest.raises(HTTPException, match="Start must be earlier"):
        resolve_time_bounds(start=start, end=end)
