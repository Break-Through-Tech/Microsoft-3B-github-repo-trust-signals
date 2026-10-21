"""Visualize handoff coverage, not feature quality or model performance."""

import argparse
import csv
from pathlib import Path


def main(folder):

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.colors import LinearSegmentedColormap
    import matplotlib.pyplot as plt
    import numpy as np

    with (folder / "temporal_features_staging.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with (folder / "outside_base_review.csv").open(encoding="utf-8") as f:
        outside = {r["repo_id"] for r in csv.DictReader(f)}
    names = [r["repo_id"] for r in rows]
    families = [
        ("90-day count", lambda n: n == "temporal__nonmerge_commits_90d"),
        (
            "Commit pilot",
            lambda n: (
                n.startswith("temporal__")
                and not any(x in n for x in ["issue_opened", "pr_opened", "releases", "forks", "nonmerge_commits_90d"])
            ),
        ),
        ("Issues / PRs", lambda n: "issue_opened" in n or "pr_opened" in n),
        ("Releases", lambda n: "__releases_" in n),
        ("Forks", lambda n: "__forks_" in n),
    ]
    columns = [[n for n in rows[0] if test(n)] for _, test in families]
    matrix = [[sum(r[n] != "" for n in group) / len(group) for group in columns] for r in rows]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(12, 8.3))
    fig.subplots_adjust(left=0.32, right=0.95, top=0.77, bottom=0.24)
    ax.imshow(
        np.array(matrix),
        cmap=LinearSegmentedColormap.from_list("coverage", ["#edf0f4", "#77b7b0", "#188577"]),
        vmin=0,
        vmax=1,
        aspect="auto",
    )
    for y, r in enumerate(rows):
        for x, group in enumerate(columns):
            number = sum(r[n] != "" for n in group)
            ax.text(
                x,
                y,
                f"{number}/{len(group)}",
                ha="center",
                va="center",
                color="white" if matrix[y][x] > 0.6 else "#14283f",
                fontsize=12,
            )
    ax.set_yticks(range(len(rows)), [n + (" *" if n in outside else "") for n in names])
    ax.set_xticks(range(5), [name for name, _ in families])
    ax.tick_params(length=0)
    ax.set_xticks([x - 0.5 for x in range(6)], minor=True)
    ax.set_yticks([y - 0.5 for y in range(len(rows) + 1)], minor=True)
    ax.grid(which="minor", color="white", linewidth=3)
    ax.tick_params(which="minor", length=0)
    fig.suptitle(
        "Temporal handoff: where measurements actually exist",
        x=0.05,
        ha="left",
        y=0.96,
        fontsize=21,
        weight="bold",
        color="#14283f",
    )
    fig.text(
        0.05,
        0.85,
        "Cells show populated fields / defined fields in each family. This is availability, not trust.\n* = outside the frozen 166-repository base; Task 4 review is required before inclusion.",
        fontsize=12,
        color="#14283f",
    )
    fig.text(
        0.05,
        0.065,
        "A measured zero is populated: h11 and Rich each have a verified zero 90-day count.\nGray cells mean no populated measurements, including missing, incomplete or out-of-scope observations.\nOnly two base repositories have new exact counts; staging coverage must not be presented as a complete training dataset.",
        fontsize=10,
        color="#14283f",
    )
    target = folder / "charts"
    target.mkdir(exist_ok=True)
    fig.savefig(target / "integration_coverage.png", dpi=180, facecolor="white")
    fig.savefig(target / "integration_coverage.svg", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", type=Path, required=True)
    main(p.parse_args().bundle)
