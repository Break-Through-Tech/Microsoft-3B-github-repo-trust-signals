from datetime import timedelta
import unittest

from analyze_rea_daily import utc_counts, validate_weeks
import pytest
from screening import utc


class ReaAlignmentTests(unittest.TestCase):
    def test_reorders_weeks_and_accepts_identical_duplicate(self):
        a = {"week": 1791072000, "days": [1, 0, 0, 0, 0, 0, 0], "total": 1}
        b = {"week": 1791676800, "days": [0] * 7, "total": 0}
        assert len(validate_weeks([b, a, a])) == 2

    def test_mismatching_sum_rejected(self):
        with pytest.raises(ValueError, match=r"(?i)Daily sum"):
            validate_weeks([{"week": 1, "days": [0] * 7, "total": 1}])

    def test_conflicting_duplicate_rejected(self):
        a = {"week": 1, "days": [0] * 7, "total": 0}
        b = {"week": 1, "days": [1, 0, 0, 0, 0, 0, 0], "total": 1}
        with pytest.raises(ValueError, match=r"(?i)Conflicting duplicate"):
            validate_weeks([a, b])

    def test_gap_not_silently_filled(self):
        with pytest.raises(ValueError, match=r"(?i)Missing or nonweekly"):
            validate_weeks(
                [{"week": 1, "days": [0] * 7, "total": 0}, {"week": 1 + 14 * 86400, "days": [0] * 7, "total": 0}]
            )

    def test_nonuniform_source_intervals_can_be_retained_explicitly(self):
        rows = [{"week": 1, "days": [0] * 7, "total": 0}, {"week": 1 + 7 * 86400 + 3600, "days": [0] * 7, "total": 0}]
        with pytest.raises(ValueError, match=r"(?i)Missing or nonweekly"):
            validate_weeks(rows)
        assert len(validate_weeks(rows, require_uniform=False)) == 2

    def test_offset_changes_calendar_day(self):
        records = [
            {"parents": [], "committer": utc("2026-10-04T01:00:00Z")},
            {"parents": ["a", "b"], "committer": utc("2026-10-04T01:00:00Z")},
        ]
        start = utc("2026-10-03T00:00:00Z")
        end = start + timedelta(days=3)
        assert utc_counts(records, start, end, 0)["2026-10-04"] == 1
        assert utc_counts(records, start, end, -12)["2026-10-03"] == 1


if __name__ == "__main__":
    unittest.main()
