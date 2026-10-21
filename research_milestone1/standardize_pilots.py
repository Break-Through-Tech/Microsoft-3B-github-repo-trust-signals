"""Offline, creation-aware weekly commit recount with explicit evidence versions."""

import argparse
import csv
from datetime import UTC, timedelta
import hashlib
import json
from pathlib import Path
import statistics

from screening import utc


def sunday(stamp):
    stamp = utc(stamp) if isinstance(stamp, str) else stamp.astimezone(UTC)
    return (stamp - timedelta(days=(stamp.weekday() + 1) % 7)).replace(hour=0, minute=0, second=0, microsecond=0)


def read_log(path):
    rows = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        sha, parents, author, committer = line.split("\t")
        if sha in seen:
            raise ValueError("Duplicate SHA in Git log")
        seen.add(sha)
        rows.append(
            {
                "sha": sha,
                "parents": parents.split(),
                "author": utc(author),
                "committer": utc(committer),
                "author_local_day": author[:10],
                "committer_local_day": committer[:10],
            }
        )
    return rows


def weekly_row(commits, start, created, reference):
    end = start + timedelta(days=7)
    observed = sum(len(c["parents"]) <= 1 and start <= c["committer"] < min(end, reference) for c in commits)
    if end <= created:
        status = "pre_creation"
        count = None
    elif end > reference:
        status = "incomplete_at_original_reference"
        count = None
    elif start < created:
        status = "partial_creation_week"
        count = observed
    else:
        status = "complete"
        count = observed
    return {
        "week_start_utc": start.isoformat(),
        "week_end_exclusive_utc": end.isoformat(),
        "nonmerge_commits_committer_utc": count,
        "observed_count": observed,
        "coverage_status": status,
    }


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main(folder, evidence):
    manifest = json.loads((folder / "history_manifest.json").read_text())
    if any(r["coverage"] != "complete_reachable_history" for r in manifest):
        raise ValueError("All three histories must have explicit complete coverage")
    temporal = next(evidence.glob("temporal-*/temporal"))
    oc = next((temporal / "openclaw_openclaw").iterdir())
    ds = next((temporal / "deepseek-ai_DeepSeek-R1").iterdir())
    rea = next((temporal / "morluto_rea").iterdir())
    raws = {
        "openclaw/openclaw": json.loads((oc / "raw_commit_activity.json").read_text()),
        "deepseek-ai/DeepSeek-R1": json.loads((ds / "source_responses.json").read_text()),
        "morluto/rea": json.loads((rea / "raw_evidence.json").read_text()),
    }
    settings = {
        "openclaw/openclaw": ("2026-01-25", raws["openclaw/openclaw"]["saved_at"], oc / "peak_event_window.csv"),
        "deepseek-ai/DeepSeek-R1": ("2025-01-26", raws["deepseek-ai/DeepSeek-R1"]["saved_at"], ds / "event_window.csv"),
        "morluto/rea": ("2026-10-04", raws["morluto/rea"]["metadata_collected_at"], rea / "weekly_activity.csv"),
    }
    allweeks = []
    summaries = []
    logs = {}
    for item in manifest:
        repo = item["requested_full_name"]
        peak_text, reference_text, oldpath = settings[repo]
        peak = utc(peak_text + "T00:00:00Z")
        reference = utc(reference_text)
        created = utc(item["created_at"])
        commits = read_log(folder / repo.replace("/", "_") / "all_reachable_commits.tsv")
        logs[repo] = commits
        old = list(csv.DictReader(oldpath.open(encoding="utf-8-sig")))
        old_by_week = {utc(r["week_display_utc"]).date().isoformat(): r for r in old}
        weeks = []
        for offset in range(-4, 9):
            start = peak + timedelta(weeks=offset)
            row = weekly_row(commits, start, created, reference)
            oldrow = old_by_week.get(start.date().isoformat())
            row.update(
                repository=repo,
                weeks_from_peak=offset,
                repo_id=item["repo_id"],
                head_sha=item["head_sha"],
                original_reference_utc=reference.isoformat(),
                feature_available_at_utc=item["log_saved_at_utc"],
                previous_method_count=int(oldrow["weekly_commits"])
                if oldrow and oldrow.get("weekly_commits", "")
                else None,
                previous_method="individual_committer_utc"
                if repo.startswith("deepseek")
                else "github_weekly_statistics",
                new_method="frozen_current_branch_nonmerge_committer_utc",
            )
            count = row["nonmerge_commits_committer_utc"]
            oldcount = row["previous_method_count"]
            row["new_minus_previous"] = count - oldcount if count is not None and oldcount is not None else None
            weeks.append(row)
        allweeks.extend(weeks)
        pre = [
            r["nonmerge_commits_committer_utc"]
            for r in weeks
            if -4 <= r["weeks_from_peak"] <= -1 and r["coverage_status"] == "complete"
        ]
        post = [
            r["nonmerge_commits_committer_utc"]
            for r in weeks
            if 1 <= r["weeks_from_peak"] <= 8 and r["coverage_status"] == "complete"
        ]
        valid_pre = len(pre) == 4
        valid_post = len(post) == 8
        summaries.append(
            {
                "repository": repo,
                "created_at": created.isoformat(),
                "peak_week_utc": peak.isoformat(),
                "repo_id": item["repo_id"],
                "head_sha": item["head_sha"],
                "feature_available_at_utc": item["log_saved_at_utc"],
                "method_version": "git_reachable_nonmerge_committer_utc_v1",
                "full_pre_weeks": len(pre),
                "full_post_weeks": len(post),
                "post_active_weeks_observed": sum(c > 0 for c in post),
                "post_active_week_share_8w": sum(c > 0 for c in post) / 8 if valid_post else None,
                "pre_median": statistics.median(pre) if valid_pre else None,
                "post_median_8w": statistics.median(post) if valid_post else None,
                "post_pre_ratio": statistics.median(post) / statistics.median(pre)
                if valid_pre and valid_post and statistics.median(pre) > 0
                else None,
                "full_history_commits": len(commits),
                "original_reference_utc": reference.isoformat(),
                "history_state_warning": "Current frozen branch recount; original collection head was not preserved",
            }
        )
    write_csv(folder / "standardized_event_weeks.csv", allweeks)
    write_csv(folder / "pilot_features_standardized.csv", summaries)
    with (oc / "commit_method_check_records.csv").open(encoding="utf-8-sig") as f:
        cached = list(csv.DictReader(f))
    assert len({r["sha"] for r in cached}) == len(cached)
    start = utc("2025-11-30T00:00:00Z")
    end = start + timedelta(days=7)
    rawstat = next(r for r in raws["openclaw/openclaw"]["response"] if r["week"] == int(start.timestamp()))
    assert sum(rawstat["days"]) == rawstat["total"] == 252
    diagnostic = []
    for i in range(7):
        d = start + timedelta(days=i)
        e = d + timedelta(days=1)
        date = d.date().isoformat()
        row = {"date_utc": date, "saved_statistics": rawstat["days"][i]}
        for basis in ("author", "committer"):
            row["saved_individual_" + basis + "_utc"] = sum(
                r["is_merge"].lower() == "false" and d <= utc(r[basis + "_date"]) < e for r in cached
            )
            row["current_history_" + basis + "_utc"] = sum(
                len(r["parents"]) <= 1 and d <= r[basis] < e for r in logs["openclaw/openclaw"]
            )
            row["current_history_" + basis + "_local_day"] = sum(
                len(r["parents"]) <= 1 and r[basis + "_local_day"] == date for r in logs["openclaw/openclaw"]
            )
        diagnostic.append(row)
    write_csv(folder / "discrepancy_daily_diagnostic.csv", diagnostic)
    preserved_shas = {
        r["sha"] for r in cached if r["is_merge"].lower() == "false" and start <= utc(r["committer_date"]) < end
    }
    current_shas = {
        r["sha"] for r in logs["openclaw/openclaw"] if len(r["parents"]) <= 1 and start <= r["committer"] < end
    }
    audit = {
        "saved_weekly_statistics": 252,
        "saved_nonmerge_committer_utc": len(preserved_shas),
        "saved_nonmerge_author_utc": sum(
            r["is_merge"].lower() == "false" and start <= utc(r["author_date"]) < end for r in cached
        ),
        "saved_merge_commits_in_week": sum(
            r["is_merge"].lower() == "true" and start <= utc(r["committer_date"]) < end for r in cached
        ),
        "current_history_nonmerge_committer_utc": len(current_shas),
        "preserved_shas_not_current_week": sorted(preserved_shas - current_shas),
        "current_week_shas_not_preserved": sorted(current_shas - preserved_shas),
        "totals_by_variant": {key: sum(r[key] for r in diagnostic) for key in diagnostic[0] if key != "date_utc"},
        "causal_resolution": "Not established by numerical agreement alone; original statistics head and per-commit membership unavailable",
    }
    assert audit["saved_nonmerge_committer_utc"] == audit["saved_nonmerge_author_utc"] == 249
    (folder / "discrepancy_audit.json").write_text(json.dumps(audit, indent=2))
    cached_deep = raws["deepseek-ai/DeepSeek-R1"]["historical_commit_response"]
    deep_start = utc("2024-12-29T00:00:00Z")
    deep_end = utc("2025-03-30T00:00:00Z")
    deep_cached = {
        r["sha"]
        for r in cached_deep
        if len(r["parents"]) <= 1 and deep_start <= utc(r["commit"]["committer"]["date"]) < deep_end
    }
    deep_new = {
        r["sha"]
        for r in logs["deepseek-ai/DeepSeek-R1"]
        if len(r["parents"]) <= 1 and deep_start <= r["committer"] < deep_end
    }
    (folder / "deepseek_cached_validation.json").write_text(
        json.dumps(
            {
                "cached_returned_commits": len(cached_deep),
                "cached_nonmerge_commits": len(deep_cached),
                "new_nonmerge_commits": len(deep_new),
                "same_sha_set": deep_cached == deep_new,
                "cached_only": sorted(deep_cached - deep_new),
                "new_only": sorted(deep_new - deep_cached),
            },
            indent=2,
        )
    )
    charts(folder, allweeks, diagnostic, summaries)
    inventory = [
        {
            "path": str(p.relative_to(folder)),
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in folder.rglob("*")
        if p.is_file() and "history.git" not in p.parts and p.name != "evidence_manifest.json"
    ]
    (folder / "evidence_manifest.json").write_text(json.dumps(inventory, indent=2))
    print(json.dumps({"features": summaries, "discrepancy": audit}, indent=2))


def charts(folder, weeks, daily, summaries):

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "svg.fonttype": "none",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    out = folder / "charts"
    out.mkdir(exist_ok=True)
    navy = "#14283f"
    blue = "#3277b3"
    orange = "#bd6327"
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    fig.subplots_adjust(top=0.84, bottom=0.17, hspace=0.48, left=0.12, right=0.96)
    for ax, summary in zip(axes, summaries, strict=False):
        selected = [r for r in weeks if r["repository"] == summary["repository"]]
        valid = [r for r in selected if r["coverage_status"] == "complete"]
        old = [r for r in valid if r["previous_method_count"] is not None]
        ax.plot(
            [r["weeks_from_peak"] for r in old],
            [r["previous_method_count"] for r in old],
            color=orange,
            marker="o",
            ls="--",
            label="Saved earlier method",
        )
        ax.plot(
            [r["weeks_from_peak"] for r in valid],
            [r["nonmerge_commits_committer_utc"] for r in valid],
            color=blue,
            marker="o",
            label="Standardized recount",
        )
        for r in selected:
            if r["coverage_status"] != "complete":
                ax.axvspan(r["weeks_from_peak"] - 0.45, r["weeks_from_peak"] + 0.45, color="#c9cfd5", alpha=0.3)
        ax.axvline(0, color=navy, lw=0.8, alpha=0.6)
        ax.set_title(summary["repository"], loc="left", weight="bold")
        ax.set_ylabel("Commits")
        ax.grid(axis="y", alpha=0.13)
        ax.set_xticks(range(-4, 9))
        ax.legend(frameon=False, fontsize=9, loc="upper right")
    axes[-1].set_xlabel("Weeks relative to the preserved star peak (0 = peak week)")
    fig.suptitle(
        "One commit method, explicit coverage limits", x=0.05, ha="left", y=0.96, fontsize=23, weight="bold", color=navy
    )
    fig.text(
        0.05,
        0.885,
        "Default-branch reachable non-merges, UTC committer dates, Sunday-start weeks.\nEach panel has its own vertical scale; repository purpose and size differ.",
        fontsize=12,
        color=navy,
    )
    fig.text(
        0.05,
        0.055,
        "Gray bands = pre-creation, partial-creation, or incomplete weeks at the original pilot reference; not zeros.\nNew counts use newly frozen branch histories. Earlier counts may differ in method and branch state.\nNo historical collection head was preserved; this recount does not recreate those exact earlier states.",
        fontsize=10,
        color=navy,
    )
    save(fig, out, "standardized_pilot_comparison", plt)
    fig, ax = plt.subplots(figsize=(12, 6.8))
    fig.subplots_adjust(top=0.77, bottom=0.25, left=0.1, right=0.96)
    x = list(range(7))
    width = 0.25
    variants = [
        ("saved_statistics", "Saved weekly-statistics daily counts", orange),
        ("saved_individual_committer_utc", "Saved individual commits (UTC)", blue),
        ("current_history_committer_utc", "New history recount (UTC)", "#188577"),
    ]
    for j, (key, label, color) in enumerate(variants):
        ax.bar([i + (j - 1) * width for i in x], [r[key] for r in daily], width, color=color, label=label)
    ax.set_xticks(x, [r["date_utc"][5:] for r in daily])
    ax.set_ylabel("Non-merge commits / day")
    ax.grid(axis="y", alpha=0.13)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=10)
    fig.suptitle(
        "The 252 vs. 249 gap hides larger daily differences",
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
        "OpenClaw: November 30-December 6, 2025. The original discrepancy is preserved.",
        fontsize=13,
        color=navy,
    )
    fig.text(
        0.05,
        0.065,
        "GitHub documents statistics as excluding merges. Author/committer and local-day diagnostics are saved separately.\nThe aggregate has no per-commit membership or original head SHA, so a numerical match cannot prove its cause.\nUse the standardized recount for new features; retain earlier results as a separate evidence version.",
        fontsize=10,
        color=navy,
    )
    save(fig, out, "openclaw_method_diagnostic", plt)


def save(fig, folder, name, plt):
    fig.savefig(folder / (name + ".png"), dpi=180, facecolor="white")
    fig.savefig(folder / (name + ".svg"), facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--collection", type=Path, required=True)
    p.add_argument("--evidence", type=Path, default=Path("local_evidence_20261014_01"))
    a = p.parse_args()
    main(a.collection, a.evidence)
