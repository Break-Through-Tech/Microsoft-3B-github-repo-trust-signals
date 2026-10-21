import unittest

import pytest
from screening import count_cached_commits, utc


def commit(sha, date, parents=1):
    return {"sha": sha, "commit": {"committer": {"date": date}}, "parents": [{"sha": str(i)} for i in range(parents)]}


class ScreeningTests(unittest.TestCase):
    def test_boundaries_merges_and_duplicates(self):
        records = [
            commit("start", "2026-07-08T20:27:35.264423Z"),
            commit("end", "2026-10-06T20:27:35.264423Z"),
            commit("before", "2026-07-08T20:27:35Z"),
            commit("merge", "2026-09-01T00:00:00Z", 2),
            commit("root", "2026-09-01T00:00:00Z", 0),
        ]
        result = count_cached_commits([*records, records[0]], "2026-10-06T20:27:35.264423Z", True)
        assert result["nonmerge_commits_90d"] == 2

    def test_missing_is_not_zero(self):
        assert count_cached_commits([], "2026-10-06T00:00:00Z")["nonmerge_commits_90d"] is None
        assert count_cached_commits([], "2026-10-06T00:00:00Z", True)["nonmerge_commits_90d"] == 0

    def test_timezone_required(self):
        with pytest.raises(ValueError, match=r"(?i)Timezone"):
            utc("2026-10-06T00:00:00")

    def test_conflicting_duplicate(self):
        with pytest.raises(ValueError, match=r"(?i)Conflicting duplicate"):
            count_cached_commits(
                [commit("x", "2026-09-01T00:00:00Z"), commit("x", "2026-09-02T00:00:00Z")], "2026-10-06T00:00:00Z"
            )


if __name__ == "__main__":
    unittest.main()
