from datetime import timedelta
import unittest
from unittest.mock import Mock

import pytest
from screening import utc
from standardize_pilots import read_log, sunday, weekly_row


def record(sha, stamp, parents=0):
    return {"sha": sha, "committer": utc(stamp), "parents": ["p"] * parents}


class PilotMethodTests(unittest.TestCase):
    def test_utc_week_rollover(self):
        assert sunday("2026-01-24T20:00:00-06:00") == utc("2026-01-25T00:00:00Z")
        assert sunday("2026-01-25T00:00:00Z") == utc("2026-01-25T00:00:00Z")

    def test_window_boundaries_and_merges(self):
        start = utc("2026-01-25T00:00:00Z")
        records = [
            record("root", "2026-01-25T00:00:00Z"),
            record("end", "2026-02-01T00:00:00Z"),
            record("merge", "2026-01-26T00:00:00Z", 2),
        ]
        row = weekly_row(records, start, start - timedelta(days=30), start + timedelta(days=7))
        assert row["nonmerge_commits_committer_utc"] == 1

    def test_precreation_not_zero(self):
        start = utc("2026-01-25T00:00:00Z")
        row = weekly_row([], start, start + timedelta(days=8), start + timedelta(days=20))
        assert row["nonmerge_commits_committer_utc"] is None
        assert row["coverage_status"] == "pre_creation"

    def test_partial_creation_separate_from_full_week(self):
        start = utc("2026-01-25T00:00:00Z")
        row = weekly_row([], start, start + timedelta(days=1), start + timedelta(days=8))
        assert row["nonmerge_commits_committer_utc"] == 0
        assert row["coverage_status"] == "partial_creation_week"

    def test_incomplete_week_count_is_null(self):
        start = utc("2026-01-25T00:00:00Z")
        row = weekly_row(
            [record("x", "2026-01-26T00:00:00Z")], start, start - timedelta(days=1), start + timedelta(days=2)
        )
        assert row["nonmerge_commits_committer_utc"] is None
        assert row["observed_count"] == 1

    def test_duplicate_log_rejected(self):
        p = Mock()
        line = "abc\t\t2026-01-25T00:00:00Z\t2026-01-25T00:00:00Z\n"
        p.read_text.return_value = line + line
        with pytest.raises(ValueError, match=r"(?i)Duplicate"):
            read_log(p)


if __name__ == "__main__":
    unittest.main()
