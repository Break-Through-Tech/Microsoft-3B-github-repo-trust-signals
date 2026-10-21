"""Normalize preserved engagement evidence while keeping source scopes separate."""

import argparse
import hashlib
import json
from pathlib import Path

from screening import utc
from standardize_pilots import write_csv


def deduplicate(records):
    unique = {}
    for record in records:
        key = record["id"]
        if key in unique and record.get("created_at") != unique[key].get("created_at"):
            raise ValueError("Conflicting record creation time")
        unique[key] = record
    return list(unique.values())


def inside(stamp, start, end):
    return bool(stamp) and utc(start) <= utc(stamp) < utc(end)


def main(out):
    repos = json.loads((out / "repositories.json").read_text())
    search = json.loads((out / "search_counts.json").read_text())
    streams = json.loads((out / "streams.json").read_text())
    rows = []
    row_extra: dict[str, int | None]
    checks = []
    for row in search:
        repo = next(r for r in repos if r["repository"] == row["repository"])
        eligible = row["complete_at_original_reference"] and utc(repo["created_at"]) <= utc(row["start_utc"])
        count = row["search_reported_count"] if row["coverage"] == "indexed_count_complete_response" else None
        normalized = {
            "repository": row["repository"],
            "repo_id": repo["repo_id"],
            "period": row["period"],
            "event_kind": row["event_kind"] + "_opened",
            "period_start_utc": row["start_utc"],
            "period_end_exclusive_utc": row["end_exclusive_utc"],
            "nominal_weeks": row["nominal_weeks"],
            "full_period_eligible": eligible,
            "reported_count": count,
            "count_per_week": count / row["nominal_weeks"] if eligible and count is not None else None,
            "coverage": row["coverage"],
            "source_scope": "current_search_index_not_historical_census",
            "feature_available_at_utc": row.get("collected_at_utc"),
            "absence_reason": None if eligible else "partial_creation_or_unobserved_at_original_cutoff",
        }
        rows.append(normalized)
        if row.get("query") and row["coverage"] != "collection_error":
            raw = json.loads(
                (
                    out
                    / row["repository"].replace("/", "_")
                    / ("search_" + row["period"] + "_" + row["event_kind"] + ".json")
                ).read_text()
            )["body"]
            for item in raw.get("items", []):
                assert inside(item["created_at"], row["start_utc"], row["end_exclusive_utc"])
                assert ("pull_request" in item) == (row["event_kind"] == "pr")
            assert raw["total_count"] == row["search_reported_count"]
            checks.append(
                {
                    "repository": row["repository"],
                    "period": row["period"],
                    "kind": row["event_kind"],
                    "sample_count_checked": len(raw.get("items", [])),
                    "scope": "sample only; not full enumeration",
                }
            )
    for stream in streams:
        repo = next(r for r in repos if r["repository"] == stream["repository"])
        records = deduplicate(stream["records"])
        raw_pages = list((out / stream["repository"].replace("/", "_")).glob(stream["stream"] + "_page_*.json"))
        available = max((json.loads(p.read_text()).get("collected_at_utc", "") for p in raw_pages), default=None)
        for period in repo["periods"]:
            eligible = period["complete_at_original_reference"] and utc(repo["created_at"]) <= utc(period["start_utc"])
            count = None
            observed = 0
            rate = None
            scope = ""
            coverage = stream["coverage"]
            if stream["stream"] == "releases":
                selected = [
                    r
                    for r in records
                    if not r.get("draft", False)
                    and inside(r.get("published_at"), period["start_utc"], period["end_exclusive_utc"])
                ]
                observed = len(selected)
                scope = "currently_visible_public_releases_by_published_at_not_tags"
                if period["complete_at_original_reference"] and coverage == "all_current_public_records":
                    count = observed
                row_extra = {"prereleases_observed": sum(bool(r.get("prerelease")) for r in selected)}
            else:
                selected = [
                    r for r in records if inside(r["created_at"], period["start_utc"], period["end_exclusive_utc"])
                ]
                observed = len(selected)
                scope = "currently_visible_API_listed_forks_not_all_historical_forks"
                latest = max((utc(r["created_at"]) for r in records), default=None)
                if period["complete_at_original_reference"] and (
                    coverage == "all_current_public_records"
                    or (latest is not None and latest >= utc(period["end_exclusive_utc"]))
                ):
                    count = observed
                    coverage = "visible_forks_period_enumerated"
                elif latest is not None and latest < utc(period["start_utc"]):
                    coverage = "fork_window_not_reached"
                row_extra = {}
            if not period["complete_at_original_reference"]:
                coverage = "unobserved_period"
                count = None
                observed = None
                if "prereleases_observed" in row_extra:
                    row_extra["prereleases_observed"] = None
            elif not eligible:
                coverage = "partial_creation_period"
            if eligible and count is not None:
                rate = count / period["nominal_weeks"]
            rows.append(
                {
                    "repository": repo["repository"],
                    "repo_id": repo["repo_id"],
                    "period": period["period"],
                    "event_kind": stream["stream"],
                    "period_start_utc": period["start_utc"],
                    "period_end_exclusive_utc": period["end_exclusive_utc"],
                    "nominal_weeks": period["nominal_weeks"],
                    "full_period_eligible": eligible,
                    "reported_count": count,
                    "observed_lower_bound": observed,
                    "count_per_week": rate,
                    "coverage": coverage,
                    "source_scope": scope,
                    "feature_available_at_utc": available,
                    **row_extra,
                }
            )
    write_csv(out / "engagement_features.csv", rows)
    (out / "search_sample_checks.json").write_text(json.dumps(checks, indent=2))
    charts(out, rows, repos)
    manifest = [
        {
            "path": str(p.relative_to(out)),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "bytes": p.stat().st_size,
        }
        for p in out.rglob("*")
        if p.is_file() and p.name != "evidence_manifest.json"
    ]
    (out / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(
        json.dumps(
            [
                {
                    k: r.get(k)
                    for k in [
                        "repository",
                        "period",
                        "event_kind",
                        "reported_count",
                        "observed_lower_bound",
                        "coverage",
                        "count_per_week",
                    ]
                }
                for r in rows
            ],
            indent=2,
        )
    )


def charts(out, rows, repos):

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    import matplotlib.pyplot as plt
    import numpy as np

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
    folder.mkdir(exist_ok=True)
    navy, blue, teal, _orange = "#14283f", "#3277b3", "#188577", "#bd6327"
    periods = ["pre_4w", "peak_1w", "post_8w"]
    labels = ["Before (4 weeks)", "Peak (1 week)", "After (8 weeks)"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 7))
    fig.subplots_adjust(left=0.07, right=0.97, top=0.75, bottom=0.38, wspace=0.36)
    for ax, repo in zip(axes, repos, strict=False):
        for shift, kind, color in [(-0.18, "issue_opened", blue), (0.18, "pr_opened", teal)]:
            for i, period in enumerate(periods):
                row = next(
                    r
                    for r in rows
                    if r["repository"] == repo["repository"] and r["event_kind"] == kind and r["period"] == period
                )
                value = row["count_per_week"]
                if value is not None:
                    ax.bar(i + shift, value, width=0.34, color=color, label=kind if i == 0 else None)
                    ax.annotate(
                        f"{value:.1f}",
                        (i + shift, value),
                        xytext=(0, 5),
                        textcoords="offset points",
                        ha="center",
                        fontsize=9,
                    )
                else:
                    ax.text(
                        i, 0.03, "N/A", transform=ax.get_xaxis_transform(), ha="center", color="#687580", fontsize=10
                    )
        ax.set_xticks(range(3), labels, rotation=30, ha="right")
        ax.set_title(repo["repository"], fontsize=12, weight="bold")
        ax.set_xlim(-0.6, 2.6)
        ax.set_ylabel("Search-reported creations / week")
        ax.grid(axis="y", alpha=0.12)
        ax.set_axisbelow(True)
        ax.margins(y=0.2)
    fig.suptitle(
        "Attention is only one part of the activity picture",
        x=0.05,
        ha="left",
        y=0.96,
        fontsize=23,
        weight="bold",
        color=navy,
    )
    fig.text(
        0.05,
        0.84,
        "Issue and PR creations from GitHub's current search index; counts normalized by period length.\nPanel scales differ. N/A = incomplete period, creation-limited baseline, or unavailable count.",
        fontsize=12,
        color=navy,
    )
    fig.legend(
        handles=[Patch(color=blue, label="Issues opened (PRs excluded)"), Patch(color=teal, label="PRs opened")],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.17),
        ncol=2,
        frameon=False,
    )
    fig.text(
        0.05,
        0.055,
        "Creation counts do not measure responses, resolution, merges, contributor reputation, quality or trust.\nIndex totals are not an exhaustive historical census; deleted, private or unindexed records may be absent.\nFixed nominal UTC peak windows are retained; exact alignment to star-history boundaries remains provisional.",
        fontsize=10,
        color=navy,
    )
    save(fig, folder, "issue_pr_activity", plt)
    fig, ax = plt.subplots(figsize=(12, 8.3))
    fig.subplots_adjust(left=0.31, right=0.94, top=0.79, bottom=0.23)
    matrix = []
    texts = []
    ylabels = []
    kinds = ["issue_opened", "pr_opened", "releases", "forks"]
    for repo in repos:
        for period in periods:
            codes = []
            celltext = []
            ylabels.append(repo["repository"] + " / " + period)
            for kind in kinds:
                r = next(
                    r
                    for r in rows
                    if r["repository"] == repo["repository"] and r["period"] == period and r["event_kind"] == kind
                )
                if not r["full_period_eligible"]:
                    code = 0
                    label = "N/A"
                elif r["coverage"] == "indexed_count_complete_response":
                    code = 1
                    label = str(r["reported_count"]) + " index"
                elif r["reported_count"] is not None:
                    code = 2
                    label = str(r["reported_count"]) + " listed"
                else:
                    code = 3
                    label = (
                        str(r["observed_lower_bound"]) + "+ partial"
                        if r.get("observed_lower_bound", 0)
                        else "not covered"
                    )
                codes.append(code)
                celltext.append(label)
            matrix.append(codes)
            texts.append(celltext)
    colors = ["#e4e8ed", "#dcebf8", "#dff2ed", "#fae7d7"]
    ax.imshow(np.array(matrix), cmap=ListedColormap(colors), vmin=0, vmax=3, aspect="auto")
    for y, labelsrow in enumerate(texts):
        for x, text in enumerate(labelsrow):
            ax.text(x, y, text, ha="center", va="center", fontsize=10, color=navy)
    ax.set_xticks(range(4), ["Issues opened", "PRs opened", "Releases published", "Forks created"])
    ax.set_yticks(range(9), ylabels)
    ax.tick_params(length=0)
    ax.set_xticks([-0.5, 0.5, 1.5, 2.5, 3.5], minor=True)
    ax.set_yticks([i - 0.5 for i in range(10)], minor=True)
    ax.grid(which="minor", color="white", linewidth=3)
    ax.tick_params(which="minor", length=0)
    fig.suptitle(
        "Coverage matters as much as the count", x=0.05, ha="left", y=0.96, fontsize=23, weight="bold", color=navy
    )
    fig.text(
        0.05,
        0.86,
        "All four evidence types are recorded with distinct source and observation limits.",
        fontsize=13,
        color=navy,
    )
    fig.legend(
        handles=[
            Patch(color=color, label=label)
            for color, label in zip(
                colors,
                ["Ineligible period", "Search index count", "Current API-listed records", "Partial / lower bound"],
                strict=False,
            )
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.13),
        ncol=2,
        frameon=False,
        fontsize=10,
    )
    fig.text(
        0.05,
        0.045,
        "“Listed” means all currently visible records for that period; not every historical event. Fork sampling is capped.\nDeepSeek lacks a full pre-peak baseline; REA has no full eight-week follow-up at its original cutoff.\nZeros are counts within source scope, never proof that a project was abandoned.",
        fontsize=10,
        color=navy,
    )
    save(fig, folder, "engagement_coverage", plt)


def save(fig, folder, name, plt):
    fig.savefig(folder / (name + ".png"), dpi=180, facecolor="white")
    fig.savefig(folder / (name + ".svg"), facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--collection", type=Path, required=True)
    main(p.parse_args().collection)
