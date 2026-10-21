import unittest

from build_engagement import deduplicate, inside
from collect_engagement import periods, search_query
import pytest


class EngagementTests(unittest.TestCase):
    def test_search_prs_and_issues_separated(self):
        q = search_query("a/b", "pr", "2026-01-25T00:00:00Z", "2026-02-01T00:00:00Z")
        assert "is:pr" in q
        assert "2026-01-31T23:59:59Z" in q
        assert "2026-02-01" not in q

    def test_window_end_is_excluded(self):
        assert inside("2026-01-25T00:00:00Z", "2026-01-25T00:00:00Z", "2026-02-01T00:00:00Z")
        assert not inside("2026-02-01T00:00:00Z", "2026-01-25T00:00:00Z", "2026-02-01T00:00:00Z")
        assert not inside(None, "2026-01-25T00:00:00Z", "2026-02-01T00:00:00Z")

    def test_incomplete_followup_not_observed_zero(self):
        bins = periods("2026-10-04", "2026-10-13T23:05:20Z")
        assert bins[1]["complete_at_original_reference"]
        assert not bins[2]["complete_at_original_reference"]

    def test_duplicates_do_not_double_count(self):
        r = {"id": 1, "created_at": "2026-01-25T00:00:00Z"}
        assert len(deduplicate([r, r])) == 1

    def test_conflicting_creation_times_rejected(self):
        with pytest.raises(ValueError, match=r"Conflicting record creation time"):
            deduplicate([{"id": 1, "created_at": "a"}, {"id": 1, "created_at": "b"}])


if __name__ == "__main__":
    unittest.main()
