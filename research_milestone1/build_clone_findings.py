"""Offline evidence checks and charts for the bounded clone provenance pilot."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def provenance_kind(fork, parent, documented_relation):
    if fork is True and parent:
        return "github_recorded_fork"
    if fork is True:
        return "fork_parent_unresolved"
    if fork is False and documented_relation:
        return "documented_alternative_not_github_fork"
    return "relationship_unresolved"


def main(folder):
    rows = json.loads((folder / "provenance_results.json").read_text())
    early = json.loads((folder / "early_context.json").read_text())
    assert len(rows) == len({r["repo_id"] for r in rows}) == 5
    assert all("collection_error" not in r for r in rows)
    assert all("error" not in r and r["relationship_passages"] for r in early)
    source_by_name = {r["requested_repo"]: r for r in early}
    descriptions = {
        "HKUDS/nanobot": "Self-described inspiration from OpenClaw/Clawdbot in early README; current README wording has changed.",
        "nanocoai/nanoclaw": "Current README explicitly positions it as an alternative to OpenClaw; old requested name redirects.",
        "zeroclaw-labs/zeroclaw": "Early README compares with OpenClaw and documents migration compatibility; implementation independence unverified.",
        "Maxmount/hkuds-nanobot": "GitHub records parent and source as HKUDS/nanobot; README retains upstream identity and install target.",
    }
    for row in rows:
        name = row["canonical_full_name"]
        if name == "openclaw/openclaw":
            row["provenance_kind"] = "reference_project"
            continue
        row["provenance_kind"] = provenance_kind(row["fork"], row["parent"], True)
        row["review_note"] = descriptions[name]
        row["review_status"] = "provenance_reviewed_quality_and_code_derivation_unresolved"
        row["relationship_source"] = source_by_name.get(name, {}).get("source_url", row["readme_url"])
        row["candidate_label"] = "not_assigned_pending_user_and_task4"
    fork = next(r for r in rows if r["canonical_full_name"] == "Maxmount/hkuds-nanobot")
    upstream = next(r for r in rows if r["canonical_full_name"] == "HKUDS/nanobot")
    assert fork["parent_id"] == fork["source_id"] == upstream["repo_id"]
    (folder / "reviewed_provenance.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    fields = [
        "requested_full_name",
        "canonical_full_name",
        "repo_id",
        "created_at",
        "fork",
        "parent",
        "source",
        "head_sha",
        "name_changed_or_redirected",
        "days_created_after_openclaw_peak",
        "provenance_kind",
        "overlap_frozen_snapshot",
        "candidate_label",
        "relationship_source",
        "review_note",
    ]
    with (folder / "comparison_review.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    charts = folder / "charts"
    charts.mkdir(exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 12,
            "svg.fonttype": "none",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    navy, blue, teal, orange = "#14283f", "#3277b3", "#188577", "#bd6327"
    selected = sorted([r for r in rows if r["provenance_kind"] != "reference_project"], key=lambda r: r["created_at"])
    fig, ax = plt.subplots(figsize=(12, 6.8))
    fig.subplots_adjust(left=0.29, right=0.94, top=0.77, bottom=0.29)
    for i, row in enumerate(selected):
        day = row["days_created_after_openclaw_peak"]
        color = orange if row["fork"] else blue
        ax.hlines(i, 0, day, color=color, alpha=0.3, lw=3)
        ax.scatter(day, i, color=color, s=110, zorder=3)
        ax.annotate(
            f"{row['created_at'][:10]}  (+{day:.1f} days)",
            (day, i),
            xytext=(8, 12),
            textcoords="offset points",
            fontsize=11,
            color=navy,
        )
    ax.axvline(0, color=teal, linestyle="--", lw=1.5)
    ax.set_yticks(range(4), [r["canonical_full_name"] for r in selected])
    ax.invert_yaxis()
    ax.set_ylim(3.6, -0.6)
    ax.set_xlim(-2, 112)
    ax.set_xlabel("Days from the preserved OpenClaw peak week start (January 25, 2026 UTC)")
    ax.grid(axis="x", alpha=0.12)
    ax.set_axisbelow(True)
    fig.suptitle(
        "Repository creation dates do not measure build time",
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
        "Three non-fork repositories were created 6-20 days after the saved peak; one fork is later.",
        fontsize=13,
        color=navy,
    )
    fig.text(
        0.05,
        0.08,
        "Blue = not marked as a GitHub fork; orange = recorded fork of nanobot. Dates describe repository containers.\nWork may predate repository creation; commit timestamps may be inherited or rewritten.\nThe anchor is one preserved peak, not launch/onset of virality. Timing alone does not establish quality or copying.",
        fontsize=10,
        color=navy,
    )
    save(fig, charts, "creation_timing")
    fig, ax = plt.subplots(figsize=(12, 6.8))
    ax.set_position((0.05, 0.24, 0.9, 0.56))
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    def box(x, y, text, color):
        ax.text(
            x,
            y,
            text,
            ha="center",
            va="center",
            fontsize=13,
            color=navy,
            bbox={"boxstyle": "round,pad=.6", "facecolor": color, "edgecolor": "none"},
        )

    box(0.15, 0.52, "OpenClaw\nreference project", "#dff2ed")
    box(0.54, 0.86, "HKUDS/nanobot\nnot a GitHub fork", "#eaf1f8")
    box(0.54, 0.49, "nanocoai/nanoclaw\nnot a GitHub fork", "#eaf1f8")
    box(0.54, 0.12, "zeroclaw-labs/zeroclaw\nnot a GitHub fork", "#eaf1f8")
    box(0.86, 0.86, "Maxmount/\nhkuds-nanobot\nrecorded fork", "#f9eadc")
    for y in (0.86, 0.49, 0.12):
        ax.annotate(
            "",
            xy=(0.38, y),
            xytext=(0.26, 0.52),
            arrowprops={"arrowstyle": "->", "lw": 1.8, "linestyle": "--", "color": blue},
        )
    ax.annotate("", xy=(0.76, 0.86), xytext=(0.69, 0.86), arrowprops={"arrowstyle": "->", "lw": 2.5, "color": orange})
    fig.suptitle(
        "Related projects have different provenance", x=0.05, ha="left", y=0.96, fontsize=22, weight="bold", color=navy
    )
    fig.text(
        0.05,
        0.87,
        "One recorded fork; three alternatives with documented OpenClaw relationships.",
        fontsize=13,
        color=navy,
    )
    fig.text(
        0.05,
        0.08,
        "Dashed = README-documented inspiration, alternative positioning, or comparison; not proven code inheritance.\nSolid = GitHub parent/source metadata. qwibitai/nanoclaw redirects to nanocoai/nanoclaw.\nNo code-similarity or security evaluation was performed; no trust labels were assigned.",
        fontsize=10,
        color=navy,
    )
    save(fig, charts, "provenance_map")
    manifest = [
        {
            "path": str(p.relative_to(folder)),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "bytes": p.stat().st_size,
        }
        for p in folder.rglob("*")
        if p.is_file() and p.name != "evidence_manifest.json"
    ]
    (folder / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Saved reviewed table and two charts:", folder)


def save(fig, folder, name):
    fig.savefig(folder / (name + ".png"), dpi=180, facecolor="white")
    fig.savefig(folder / (name + ".svg"), facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--collection", type=Path, required=True)
    main(p.parse_args().collection)
