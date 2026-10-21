"""Audit REA native day bins and UTC commit counts without inventing alignment."""

import argparse
import collections
from datetime import UTC, datetime, timedelta
import hashlib
import itertools
import json
from pathlib import Path

from screening import utc
from standardize_pilots import read_log, write_csv

DOCS = {
    "star_history": "https://docs.github.com/en/rest/activity/starring#get-repository-star-history",
    "commit_statistics": "https://docs.github.com/en/rest/metrics/statistics#get-the-last-year-of-commit-activity",
}


def validate_weeks(records, require_uniform=True):
    by_week = {}
    for row in records:
        if not isinstance(row.get("week"), int):
            raise ValueError("Week timestamp missing")
        if len(row.get("days", [])) != 7:
            raise ValueError("Expected seven Sunday-first bins")
        if any(not isinstance(v, int) or v < 0 for v in row["days"]):
            raise ValueError("Invalid daily count")
        if sum(row["days"]) != row["total"]:
            raise ValueError("Daily sum disagrees with total")
        if row["week"] in by_week and row != by_week[row["week"]]:
            raise ValueError("Conflicting duplicate week")
        by_week[row["week"]] = row
    ordered = sorted(by_week)
    if require_uniform and any(b - a != 7 * 86400 for a, b in itertools.pairwise(ordered)):
        raise ValueError("Missing or nonweekly intervals")
    return by_week


def utc_counts(commits, start, end, offset_hours=0):
    """Illustrative civil-zone day bins; not a reconstruction of GitHub star bins."""
    offset = timedelta(hours=offset_hours)
    result = collections.Counter()
    for row in commits:
        if len(row["parents"]) <= 1:
            day = (row["committer"] + offset).date()
            if start.date() <= day < end.date():
                result[day.isoformat()] += 1
    return result


def main(args):
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    rawpath = next(args.evidence.glob("temporal-*/temporal/morluto_rea/*/raw_evidence.json"))
    raw = json.loads(rawpath.read_text())
    old_ref = utc(raw["metadata_collected_at"])
    star_input = [r for page in raw["star_history_pages"] for r in page["response"]]
    stars = validate_weeks(star_input)
    stats = validate_weeks(raw["commit_statistics"], require_uniform=False)
    stat_times = sorted(stats)
    stat_interval_anomalies = [
        {"before": a, "after": b, "seconds": b - a} for a, b in itertools.pairwise(stat_times) if b - a != 7 * 86400
    ]
    hist = json.loads((args.histories / "history_manifest.json").read_text())
    meta = next(r for r in hist if r["requested_full_name"] == "morluto/rea")
    assert meta["coverage"] == "complete_reachable_history"
    commits = read_log(args.histories / "morluto_rea/all_reachable_commits.tsv")
    start = utc("2026-09-27T00:00:00Z")
    end = utc("2026-10-14T00:00:00Z")
    offsets = [-12, 0, 14]
    scenarios = {offset: utc_counts(commits, start, end, offset) for offset in offsets}
    daily = []
    for week in sorted(stars):
        timestamp = datetime.fromtimestamp(week, UTC)
        if not start <= timestamp < end:
            continue
        for index, value in enumerate(stars[week]["days"]):
            nominal = timestamp + timedelta(days=index)
            if nominal >= end:
                continue
            label = nominal.date().isoformat()
            row = {
                "source_week_timestamp": week,
                "day_index_sunday_zero": index,
                "nominal_calendar_label": label,
                "star_native_bin_count": value,
                "star_timezone_alignment": "unverified_not_guaranteed_UTC",
                "saved_statistics_native_bin_count": stats.get(week, {}).get("days", [None] * 7)[index],
                "git_committer_UTC_count": scenarios[0][label] if nominal + timedelta(days=1) <= old_ref else None,
                "utc_day_coverage": "complete"
                if nominal + timedelta(days=1) <= old_ref
                else "incomplete_original_reference",
                "star_coverage": "completed_source_week" if week < max(stars) else "partial_source_week",
                "native_to_utc_exact_join_verified": False,
            }
            for offset in offsets:
                row[f"commit_day_scenario_UTC{offset:+d}"] = (
                    scenarios[offset][label] if nominal + timedelta(days=1) <= old_ref else None
                )
            daily.append(row)
    write_csv(out / "rea_daily_evidence.csv", daily)
    history_total = sum(r["total"] for r in stars.values())
    metadata_total = raw["metadata"]["stargazers_count"]
    peak_week = 1791072000
    metrics = {
        "source_raw_evidence": str(rawpath),
        "source_raw_sha256": hashlib.sha256(rawpath.read_bytes()).hexdigest(),
        "analysis_created_at_utc": datetime.now(UTC).isoformat(),
        "original_metadata_collected_at": raw["metadata_collected_at"],
        "raw_saved_at": raw["saved_at"],
        "commit_head_sha": meta["head_sha"],
        "commit_log_available_at": meta["log_saved_at_utc"],
        "star_weeks": len(stars),
        "week_day_sum_checks": "passed",
        "sunday_first_documented": True,
        "observed_week_timestamps_UTC_midnight": all(w % 86400 == 0 for w in stars),
        "saved_commit_statistics_nonuniform_week_intervals": stat_interval_anomalies,
        "star_UTC_day_alignment_verified": False,
        "exact_daily_lag_or_correlation": None,
        "boundary_reason": "GitHub explicitly does not guarantee UTC week/day boundaries for star history.",
        "star_history_sum": history_total,
        "earlier_metadata_stars": metadata_total,
        "history_minus_metadata": history_total - metadata_total,
        "same_time_totals_reconciliation": "unavailable: source request collection times differ/not individually preserved",
        "completed_peak_star_week_total": stars[peak_week]["total"],
        "peak_week_largest_native_day_index": max(range(7), key=lambda i: stars[peak_week]["days"][i]),
        "peak_week_largest_native_day_count": max(stars[peak_week]["days"]),
        "original_partial_week_excluded": max(stars),
        "docs": DOCS,
        "sensitivity_offsets_hours": offsets,
        "sensitivity_is_assumption_not_verified_alignment": True,
    }
    (out / "alignment_audit.json").write_text(json.dumps(metrics, indent=2))
    (out / "source_semantics.json").write_text(
        json.dumps(
            {
                "verified": "Both API days arrays are Sunday first; newest star weeks appear first.",
                "not_verified": "Exact UTC boundary of star-history day bins.",
                "rule": "Never join star bins to UTC commit days as equivalent intervals without independent alignment evidence.",
                "documentation_checked_at_utc": datetime.now(UTC).isoformat(),
                "sources": DOCS,
            },
            indent=2,
        )
    )
    charts(out, daily)
    files = [
        {"path": str(p.relative_to(out)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in out.rglob("*")
        if p.is_file()
    ]
    (out / "evidence_manifest.json").write_text(json.dumps(files, indent=2))
    print(json.dumps(metrics, indent=2))


def charts(out, daily):

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "svg.fonttype": "none",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    folder = out / "charts"
    folder.mkdir()
    blue, teal, orange, navy = "#3277b3", "#188577", "#bd6327", "#14283f"
    x = list(range(len(daily)))
    labels = [r["nominal_calendar_label"][5:] for r in daily]
    fig, axes = plt.subplots(2, 1, figsize=(12, 8.5), sharex=True)
    fig.subplots_adjust(top=0.79, bottom=0.22, hspace=0.42, left=0.11, right=0.96)
    axes[0].bar(
        x,
        [r["star_native_bin_count"] for r in daily],
        color=[blue if r["star_coverage"] == "completed_source_week" else orange for r in daily],
    )
    axes[0].set_title(
        "Stars: native Sunday-first bins; exact UTC boundaries unverified", loc="left", fontsize=12, weight="bold"
    )
    axes[0].set_ylabel("Stars created / source day")
    values = [r["git_committer_UTC_count"] if r["git_committer_UTC_count"] is not None else float("nan") for r in daily]
    axes[1].bar(x, values, color=teal)
    axes[1].set_title(
        "Commits: frozen default-branch non-merges in explicit UTC days", loc="left", fontsize=12, weight="bold"
    )
    axes[1].set_ylabel("Commits / UTC day")
    axes[1].set_xticks(x, labels, rotation=45)
    axes[1].set_xlabel("Nominal calendar label ;  shared labels do not establish equal time intervals")
    for ax in axes:
        ax.grid(axis="y", alpha=0.15)
        ax.set_axisbelow(True)
    fig.suptitle(
        "REA: attention and activity rose, but day alignment is uncertain",
        x=0.05,
        ha="left",
        y=0.96,
        fontsize=19,
        weight="bold",
        color=navy,
    )
    fig.text(
        0.05,
        0.86,
        "Preserved October 13 evidence; separate scales and source time definitions.\nOrange stars = unfinished source week. October 13 UTC commit day is incomplete and omitted.",
        fontsize=12,
        color=navy,
    )
    fig.text(
        0.05,
        0.055,
        "Star array order and daily sums are verified. GitHub does not guarantee UTC boundaries for star history.\nA timestamp displayed at UTC midnight does not establish the underlying aggregation boundary.\nThese panels describe broad patterns; no exact daily lead, lag, correlation, causation or trust claim is supported.",
        fontsize=10,
        color=navy,
    )
    save(fig, folder, "rea_daily_patterns", plt)
    fig, ax = plt.subplots(figsize=(12, 6.8))
    fig.subplots_adjust(top=0.77, bottom=0.26, left=0.1, right=0.96)
    for offset, color in [(-12, blue), (0, teal), (14, orange)]:
        vals = [
            r[f"commit_day_scenario_UTC{offset:+d}"]
            if r[f"commit_day_scenario_UTC{offset:+d}"] is not None
            else float("nan")
            for r in daily
        ]
        ax.plot(x, vals, marker="o", color=color, label=f"Assumed calendar zone UTC{offset:+d}")
    ax.set_xticks(x, labels, rotation=45)
    ax.set_ylabel("Non-merge commits / assumed day")
    ax.set_xlabel("Nominal calendar label")
    ax.legend(frameon=False, fontsize=10)
    ax.grid(axis="y", alpha=0.15)
    fig.suptitle(
        "Moving day boundaries changes the commit curve",
        x=0.05,
        ha="left",
        y=0.96,
        fontsize=21,
        weight="bold",
        color=navy,
    )
    fig.text(
        0.05,
        0.87,
        "Illustrative UTC-12, UTC and UTC+14 scenarios; none is verified as the star API's boundary.",
        fontsize=12,
        color=navy,
    )
    fig.text(
        0.05,
        0.055,
        "Same frozen branch, commit timestamps and merge policy; only hypothetical calendar boundaries change.\nThis is sensitivity analysis, not an uncertainty interval or a reconstruction of the star-history bins.\nNo estimated star-to-commit lag is reported. Original October 13 cutoff is retained.",
        fontsize=10,
        color=navy,
    )
    save(fig, folder, "rea_boundary_sensitivity", plt)


def save(fig, folder, name, plt):
    fig.savefig(folder / (name + ".png"), dpi=180, facecolor="white")
    fig.savefig(folder / (name + ".svg"), facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--evidence", type=Path, default=Path("local_evidence_20261014_01"))
    p.add_argument("--histories", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    main(p.parse_args())
