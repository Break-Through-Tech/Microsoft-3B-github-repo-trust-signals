"""Recheck preserved evidence and create presentation-ready charts offline."""

import argparse
import collections
import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import matplotlib
from screening import count_cached_commits, utc

matplotlib.use("Agg")
import matplotlib.pyplot as plt

GIT = Path(shutil.which("git") or "git")


def main(folder, git):
    results = json.loads((folder / "activity_results.json").read_text())
    assert len(results) == 6
    assert len({r["repo_id"] for r in results}) == 6
    reference = results[0]["reference_time_utc"]
    rich = next(r for r in results if r["requested_full_name"] == "Textualize/rich")
    bare = folder / "Textualize_rich/history.git"
    shallow = subprocess.check_output(
        [str(git), "--git-dir=" + str(bare), "rev-parse", "--is-shallow-repository"], text=True
    ).strip()
    assert shallow == "false"
    # No --since optimization: inspect every reachable commit, including unusual dates.
    log = subprocess.check_output(
        [str(git), "--git-dir=" + str(bare), "log", rich["head_sha"], "--format=%H%x09%P%x09%cI"], text=True
    )
    (folder / "Textualize_rich/full_git_commit_log.tsv").write_text(log, encoding="utf-8")
    commits = []
    for line in log.splitlines():
        sha, parents, stamp = line.split("\t")
        commits.append(
            {"sha": sha, "parents": [{"sha": p} for p in parents.split()], "commit": {"committer": {"date": stamp}}}
        )
    rich.update(count_cached_commits(commits, reference, True))
    rich.update(
        coverage="complete_git_reachable_history",
        full_history_commits=len(commits),
        filtered_vs_full_agree=rich["filtered_api_observed_count"] == rich["nonmerge_commits_90d"],
        screen_status="passes_activity_only" if rich["nonmerge_commits_90d"] <= 5 else "fails_screen",
        git_verified_at_utc=datetime.now(UTC).isoformat(),
    )
    h11 = next(r for r in results if r["requested_full_name"] == "python-hyper/h11")
    historical = []
    for path in sorted((folder / "python-hyper_h11").glob("full_history_page_*.json")):
        historical.extend(json.loads(path.read_text())["body"])
    assert count_cached_commits(historical, reference, True)["nonmerge_commits_90d"] == h11["nonmerge_commits_90d"] == 0
    assert rich["filtered_vs_full_agree"]
    evidence = json.loads((folder / "adoption_evidence.json").read_text())
    for row in evidence:
        assert "error" not in row
        assert row["matching_lines"]
        row["review_status"] = "reviewed_declared_dependency"
        if row["candidate"] == "rust-lang/regex":
            row["review_status"] = "reviewed_regex_family_dependency"
            row["supported_claim"] = (
                "ripgrep grep-regex declares regex-automata and regex-syntax; no direct regex crate dependency in this manifest."
            )
        elif row["candidate"] == "BurntSushi/ripgrep":
            row["review_status"] = "reviewed_wrapper_integration"
            row["supported_claim"] = (
                "VS Code declares a ripgrep wrapper dependency; transitive binary provenance is not fully audited."
            )
        else:
            row["supported_claim"] = "The downstream project declares this package as a runtime dependency."
    for row in results:
        matches = [e for e in evidence if e["candidate"] == row["requested_full_name"]]
        row["independent_adoption_review"] = "declared_downstream_use_verified" if matches else "not_verified"
        row["downstream_sources_verified"] = len(matches)
        row["candidate_inclusion"] = "pending_user_interpretation_and_task4"
    (folder / "verified_activity_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (folder / "reviewed_adoption_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    fields = [
        "requested_full_name",
        "repo_id",
        "reference_time_utc",
        "default_branch",
        "head_sha",
        "age_days",
        "nonmerge_commits_90d",
        "observed_lower_bound",
        "coverage",
        "screen_status",
        "independent_adoption_review",
        "downstream_sources_verified",
        "candidate_inclusion",
    ]
    with (folder / "candidate_evidence_table.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    charts = folder / "charts"
    charts.mkdir(exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 12,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "svg.fonttype": "none",
        }
    )
    navy, blue, green, orange = "#14283f", "#3277b3", "#188577", "#bd6327"
    fig, ax = plt.subplots(figsize=(12, 6.8))
    fig.subplots_adjust(left=0.25, right=0.92, top=0.79, bottom=0.29)
    labels = [r["requested_full_name"] for r in results]
    for i, row in enumerate(results):
        exact = row["nonmerge_commits_90d"]
        value = exact if exact is not None else row["observed_lower_bound"]
        ax.barh(i, value, color=green if exact is not None and value <= 5 else blue, height=0.58)
        ax.scatter([value], [i], color=green if exact is not None else blue, s=70, zorder=3)
        ax.text(
            value + 0.5,
            i,
            str(value) + ("  complete history" if exact is not None else "+  observed minimum"),
            va="center",
            fontsize=11,
            color=navy,
        )
    ax.axvline(5, color=orange, linestyle="--", linewidth=1.6, label="Provisional screen: at most 5")
    ax.set_yticks(range(6), labels)
    ax.invert_yaxis()
    ax.set_xlim(-0.5, 39)
    ax.set_xlabel("Default-branch non-merge commits in the frozen 90-day window")
    ax.grid(axis="x", alpha=0.13)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", frameon=False, fontsize=10)
    fig.suptitle(
        "Two candidates pass the activity screen", x=0.05, ha="left", y=0.96, fontsize=23, color=navy, weight="bold"
    )
    fig.text(
        0.05,
        0.87,
        "h11 and Rich have zero counted commits; the other four already exceed the threshold.",
        fontsize=13,
        color=navy,
    )
    fig.text(
        0.05,
        0.07,
        "Window: July 15-October 13, 2026 (America/Chicago); exact UTC boundaries in the evidence table.\nCommits use committer time; merges excluded. “+” is a lower bound, not an exact total.\nSix selected, existing label-1 repos; these results do not certify trust or represent GitHub overall.",
        fontsize=10,
        color=navy,
    )
    save(fig, charts, "activity_screen")
    fig, ax = plt.subplots(figsize=(12, 6.8))
    ax.set_position((0.05, 0.26, 0.82, 0.52))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.suptitle(
        "Low activity can coexist with downstream use",
        x=0.05,
        ha="left",
        y=0.96,
        fontsize=21,
        color=navy,
        weight="bold",
    )
    fig.text(
        0.05,
        0.87,
        "Declared runtime dependencies provide evidence separate from stars and recent commits.",
        fontsize=13,
        color=navy,
    )

    def node(x, y, text, color):
        ax.text(
            x,
            y,
            text,
            ha="center",
            va="center",
            fontsize=14,
            color=navy,
            bbox={"boxstyle": "round,pad=.7", "facecolor": color, "edgecolor": "none"},
        )

    node(0.16, 0.64, "HTTPcore", "#eaf1f8")
    node(0.16, 0.34, "Uvicorn", "#eaf1f8")
    node(0.56, 0.49, "h11\n0 commits / 90 days", "#dff2ed")
    node(0.16, 0.04, "Typer", "#eaf1f8")
    node(0.56, 0.04, "Rich\n0 commits / 90 days", "#dff2ed")
    for y in (0.64, 0.34):
        ax.annotate("", xy=(0.43, 0.49), xytext=(0.25, y), arrowprops={"arrowstyle": "->", "color": blue, "lw": 2})
    ax.annotate("", xy=(0.43, 0.04), xytext=(0.25, 0.04), arrowprops={"arrowstyle": "->", "color": blue, "lw": 2})
    ax.text(
        0.79,
        0.56,
        "Verified:\n• Complete activity history\n• External dependency declarations\n\nStill uncertain:\n• Deployment volume\n• Abandonment vs. stability\n• Use-specific suitability",
        fontsize=11,
        va="center",
        color=navy,
    )
    fig.text(
        0.05,
        0.07,
        "Sources: pinned HTTPcore, Uvicorn and Typer manifests; source URLs and collection times saved.\nArrows mean “declares a dependency on.” HTTPcore and Uvicorn share ecosystem origins.\nDependency declarations establish use relationships, not a general trust score.",
        fontsize=10,
        color=navy,
    )
    save(fig, charts, "downstream_use")
    counts = collections.Counter(
        utc(c["commit"]["committer"]["date"]).year
        for c in historical
        if len(c["parents"]) <= 1 and utc(c["commit"]["committer"]["date"]) < utc(reference)
    )
    years = list(range(2016, 2027))
    fig, ax = plt.subplots(figsize=(12, 6.8))
    fig.subplots_adjust(top=0.79, bottom=0.22)
    bars = ax.bar(years, [counts[y] for y in years], color=blue, width=0.65)
    ax.bar_label(bars, fontsize=10, padding=3)
    ax.set_xticks(years, [str(y) + ("*" if y == 2026 else "") for y in years])
    ax.set_ylabel("Reachable non-merge commits by committer year")
    ax.set_ylim(0, max(counts.values()) * 1.32)
    ax.grid(axis="y", alpha=0.15)
    ax.set_axisbelow(True)
    fig.suptitle(
        "h11: a long history followed by low recent activity",
        x=0.05,
        ha="left",
        y=0.96,
        fontsize=20,
        color=navy,
        weight="bold",
    )
    fig.text(
        0.05,
        0.87,
        "Maintainers describe a largely feature-complete scope; downstream projects still declare it.",
        fontsize=13,
        color=navy,
    )
    ax.text(
        0.97,
        0.91,
        "April 2025: version 0.16.0\naddresses a documented security issue",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=11,
        color=orange,
    )
    fig.text(
        0.05,
        0.09,
        "*2026 is partial through the frozen October 13 reference. Counts describe the collected branch history.\nHistorical remediation supports context; it does not prove absence of other issues or future support.\nStability is a plausible explanation for low activity; abandonment or migration was not conclusively ruled out.",
        fontsize=10,
        color=navy,
    )
    save(fig, charts, "h11_history")
    manifest = []
    for path in folder.rglob("*"):
        if path.is_file() and "history.git" not in path.parts and path.name != "evidence_manifest.json":
            manifest.append(
                {
                    "path": str(path.relative_to(folder)),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    (folder / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Complete Rich history:", len(commits), "commits; recent non-merges:", rich["nonmerge_commits_90d"])
    print("Charts:", charts)


def save(fig, folder, name):
    fig.savefig(folder / (name + ".png"), dpi=180, facecolor="white")
    fig.savefig(folder / (name + ".svg"), facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--git", type=Path, default=GIT if GIT.exists() else shutil.which("git"))
    args = parser.parse_args()
    if args.git is None:
        parser.error("Git executable unavailable; supply --git")
    main(args.collection.resolve(), args.git)
