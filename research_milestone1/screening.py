"""Coverage-aware counting for cached GitHub commit records; no API calls."""

from datetime import UTC, datetime, timedelta


def utc(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Timezone is required")
    return date.astimezone(UTC)


def count_cached_commits(records, reference_time, coverage_complete=False):
    """Default-branch non-merge commits by committer time in [T-90d, T).

    Caller must establish pagination, branch, and time coverage before setting
    coverage_complete. A partial count is a lower bound, never a zero estimate.
    """
    end = utc(reference_time)
    start = end - timedelta(days=90)
    seen = {}
    count = 0
    for record in records:
        sha = record["sha"]
        stamp = utc(record["commit"]["committer"]["date"])
        parents = record["parents"]
        key = (stamp, tuple(p["sha"] for p in parents))
        if sha in seen:
            if seen[sha] != key:
                raise ValueError("Conflicting duplicate commit")
            continue
        seen[sha] = key
        if start <= stamp < end and len(parents) <= 1:
            count += 1
    return {
        "window_start": start.isoformat(),
        "window_end_exclusive": end.isoformat(),
        "nonmerge_commits_90d": count if coverage_complete else None,
        "observed_lower_bound": count,
        "coverage": "complete" if coverage_complete else "incomplete",
        "provisional_low_activity": count <= 5 if coverage_complete else None,
    }
