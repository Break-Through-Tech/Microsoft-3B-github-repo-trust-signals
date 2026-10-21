"""Offline data-quality audit. Never fits a model or executes notebook cells."""

import argparse
import collections
import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import statistics
from typing import Any

from standardize_pilots import write_csv


def key(name):
    return name.strip().lower().removeprefix("https://github.com/").rstrip("/").removesuffix(".git")


def duplicates(rows):
    groups = collections.defaultdict(list)
    for i, row in enumerate(rows):
        groups[key(row["full_name"])].append(i + 2)
    return [{"canonical_name_key": k, "csv_lines": v} for k, v in groups.items() if len(v) > 1]


def missing(value):
    return value is None or str(value).strip().lower() in ("", "nan", "none", "null")


def main(args):
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    snapshot = next(args.evidence.glob("snapshots-*/snapshots/*/repositories.csv"))
    features = next(args.evidence.glob("Microsoft*/Microsoft*/Documents/CSV Files/features.csv"))

    def load(p):
        return list(csv.DictReader(p.open(encoding="utf-8-sig")))

    frozen = load(snapshot)
    model = load(features)
    frozen_by = {key(r["full_name"]): r for r in frozen}
    model_by = {key(r["full_name"]): r for r in model}
    common = sorted(frozen_by.keys() & model_by.keys())
    conflicts = [
        {"full_name": name, "snapshot_label": frozen_by[name]["label"], "features_y_good": model_by[name]["y_good"]}
        for name in common
        if int(frozen_by[name]["label"]) != int(model_by[name]["y_good"])
    ]
    cohort = []
    for source in sorted({r["dataset_source"] for r in frozen}):
        group = [r for r in frozen if r["dataset_source"] == source]
        cohort.append(
            {
                "dataset_source": source,
                "n": len(group),
                "label_1": sum(r["label"] == "1" for r in group),
                "label_0": sum(r["label"] == "0" for r in group),
                "archived": sum(r["archived"].lower() == "true" for r in group),
                "median_age_years": statistics.median(float(r["repo_age_days"]) for r in group) / 365.25,
                "median_days_since_push": statistics.median(float(r["days_since_push"]) for r in group),
            }
        )
    missingness = []
    fields = [
        "contributor_count",
        "issue_close_rate",
        "pr_merge_count",
        "days_since_last_merge",
        "repo_age_days",
        "days_since_push",
        "star_fork_ratio",
        "score_0_100",
    ]
    for label in ["0", "1"]:
        group = [r for r in model if r["y_good"] == label]
        for field in fields:
            missingness.append(
                {
                    "features_y_good": label,
                    "field": field,
                    "n": len(group),
                    "missing": sum(missing(r.get(field)) for r in group),
                }
            )
    owners = collections.defaultdict(list)
    for r in frozen:
        owners[key(r["full_name"]).split("/")[0]].append(r)
    owner_groups = [
        {
            "owner": owner,
            "n": len(group),
            "label_1": sum(r["label"] == "1" for r in group),
            "label_0": sum(r["label"] == "0" for r in group),
            "repositories": [r["full_name"] for r in group],
            "interpretation": "Shared owner only; relatedness and split leakage not established",
        }
        for owner, group in owners.items()
        if len(group) > 1
    ]
    fingerprints = collections.defaultdict(list)
    numeric_fields = ["repo_age_days", "days_since_push", "stargazers_count", "forks_count", "size"]
    for r in frozen:
        fingerprints[tuple(r[f] for f in numeric_fields)].append(r["full_name"])
    exact_vectors = [names for names in fingerprints.values() if len(names) > 1]
    notebooks: list[dict[str, Any]] = []
    evidence_snippets = []
    inputs = [snapshot, features, snapshot.with_name("snapshot_notes.json")]
    for p in sorted(args.evidence.rglob("*Logistic*.ipynb")):
        inputs.append(p)
        nb = json.loads(p.read_text(encoding="utf-8"))
        item = {"path": str(p), "name": p.name, "cells": len(nb["cells"]), "outputs": [], "static_findings": []}
        allsource = "\n".join("".join(c.get("source", [])) for c in nb["cells"])
        if re.search(r"fillna\(df\[feature_cols\]\.median", allsource):
            item["static_findings"].append("whole_dataframe_imputation_before_train_test_split")
        if "PR_ISSUE_CAP" in allsource:
            item["static_findings"].append("row_order_dependent_sampling_cap")
        if "DEMO_SYNTHETIC" in allsource:
            item["static_findings"].append("label_conditioned_synthetic_fallback_exists_not_proof_used")
        if "stratify=y" in allsource:
            item["static_findings"].append("row_split_stratifies_class_no_repo_family_group_visible")
        if "pd.Timestamp.now" in allsource:
            item["static_findings"].append("runtime_reference_time_or_cached_time_features")
        for cell_index, cell in enumerate(nb["cells"], 1):
            source = "".join(cell.get("source", []))
            for line_index, line in enumerate(source.splitlines(), 1):
                if re.search(
                    r'fillna\(df\[feature_cols\]|PR_ISSUE_CAP\s*=|n_idx\s*<|train_test_split\(|stratify=y|load_label_file\(COURSE|source\s*=\s*"DEMO_SYNTHETIC"|feat\.dropna\(subset|\.merge\(labels|predict_proba\(X_test\)|score_0_100.*proba_full',
                    line,
                ) and not re.search(r"token|secret|password|authorization|api_key", line, re.I):
                    evidence_snippets.append(
                        {
                            "notebook": str(p),
                            "cell_one_based": cell_index,
                            "line_in_cell_one_based": line_index,
                            "source": line.strip(),
                        }
                    )
            for output in cell.get("outputs", []):
                text = "".join(output.get("text", []))
                if not text:
                    continue
                for line in text.splitlines():
                    if re.search(
                        r"^n=|^Data source:|^Logistic holdout|^RandomForest holdout|^AUC with|^AUC without", line
                    ):
                        item["outputs"].append({"cell_one_based": cell_index, "text": line.strip()})
        notebooks.append(item)
    combined = next(n for n in notebooks if n["name"] == "Logistic_Regression_Zara_and_Vidal.ipynb")
    n_line = next(o["text"] for o in combined["outputs"] if o["text"].startswith("n="))
    match = re.search(r"n=\s*(\d+)\s+good=\s*(\d+)\s+uncertain=\s*(\d+)", n_line)
    assert match
    run_n, run_good, run_comparison = map(int, match.groups())
    result = {
        "audit_created_at_utc": datetime.now(UTC).isoformat(),
        "scope": "Data/provenance audit only; saved outputs inspected; no model execution, evaluation or feature selection",
        "snapshot_rows": len(frozen),
        "snapshot_unique_names": len(frozen_by),
        "snapshot_duplicates": duplicates(frozen),
        "features_rows": len(model),
        "features_unique_names": len(model_by),
        "features_duplicates": duplicates(model),
        "features_snapshot_overlap": len(common),
        "features_only_names": sorted(model_by.keys() - frozen_by.keys()),
        "snapshot_only_names": sorted(frozen_by.keys() - model_by.keys()),
        "shared_name_label_conflicts": conflicts,
        "same_numeric_vector_groups": exact_vectors,
        "cohorts": cohort,
        "shared_owner_groups": owner_groups,
        "features_score_present": sum(not missing(r.get("score_0_100")) for r in model),
        "combined_notebook_saved_run_n": run_n,
        "combined_notebook_saved_run_good": run_good,
        "combined_notebook_saved_run_comparison": run_comparison,
        "saved_model_run_full_row_table_and_split_manifest_supplied": False,
        "name_deduplication_limitation": "Frozen table lacks numeric repo IDs; transfers, forks and code-family duplicates not excluded",
        "row_cap_source_observation": "Combined notebook concatenates good then uncertain labels and gates PR/issue fetch by input index <106; printed input labels are 82 good and 48 uncertain",
        "row_cap_inference": "If current code is run with that order, all last 24 input rows are uncertain and skip PR/issue fetch. Does not prove exact source/output correspondence.",
        "notebooks": notebooks,
    }
    (out / "audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out / "notebook_source_evidence.json").write_text(json.dumps(evidence_snippets, indent=2), encoding="utf-8")
    write_csv(out / "cohort_summary.csv", cohort)
    write_csv(out / "features_missingness.csv", missingness)
    write_csv(out / "shared_owner_review.csv", owner_groups)
    write_csv(
        out / "repository_overlap.csv",
        [
            {"full_name": name, "in_snapshot": name in frozen_by, "in_features": name in model_by}
            for name in sorted(frozen_by.keys() | model_by.keys())
        ],
    )
    charts(out, frozen, model, cohort, run_n, run_good, run_comparison)
    manifests = [
        {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
        for p in inputs
    ]
    (out / "input_manifest.json").write_text(json.dumps(manifests, indent=2))
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ["notebooks", "snapshot_only_names", "shared_owner_groups", "cohorts"]
            },
            indent=2,
        )
    )


def charts(out, frozen, model, cohort, run_n, run_good, run_comparison):

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.patches import Patch
    import matplotlib.pyplot as plt

    folder = out / "charts"
    folder.mkdir()
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "svg.fonttype": "none",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    navy, blue, orange = "#14283f", "#3277b3", "#bd6327"
    counts = [
        (sum(r["label"] == "1" for r in frozen), sum(r["label"] == "0" for r in frozen)),
        (sum(r["y_good"] == "1" for r in model), sum(r["y_good"] == "0" for r in model)),
        (run_good, run_comparison),
    ]
    fig, ax = plt.subplots(figsize=(12, 6.8))
    fig.subplots_adjust(left=0.28, right=0.95, top=0.72, bottom=0.28)
    for i, (good, comparison) in enumerate(counts):
        ax.barh(i, good, color=blue, height=0.55)
        ax.barh(i, comparison, left=good, color=orange, height=0.55)
        ax.text(good / 2, i, str(good), ha="center", va="center", color="white", weight="bold")
        ax.text(good + comparison / 2, i, str(comparison), ha="center", va="center", color="white", weight="bold")
        ax.text(good + comparison + 2, i, f"n={good + comparison}", va="center", fontsize=12, color=navy)
    ax.set_yticks(range(3), ["Frozen research snapshot", "Supplied features.csv", "Saved model-run output"])
    ax.invert_yaxis()
    ax.set_xlim(0, 190)
    ax.set_xlabel("Repository rows")
    ax.grid(axis="x", alpha=0.12)
    ax.set_axisbelow(True)
    fig.legend(
        handles=[
            Patch(color=blue, label="Label 1 / known-good comparison"),
            Patch(color=orange, label="Label 0 / uncertain comparison"),
        ],
        loc="upper center",
        bbox_to_anchor=(0.60, 0.83),
        ncol=2,
        frameon=False,
        fontsize=10,
    )
    fig.suptitle(
        "Three evidence versions, three different datasets",
        x=0.05,
        ha="left",
        y=0.96,
        fontsize=22,
        weight="bold",
        color=navy,
    )
    fig.text(
        0.05,
        0.87,
        "The near-perfect model output cannot be attributed to the 166-row snapshot without a run manifest.",
        fontsize=12,
        color=navy,
    )
    fig.text(
        0.05,
        0.065,
        "The 126-row run is a preserved notebook output, not a newly rerun or independently validated experiment.\nThe supplied 103-row table is not its full training table. Label 0 does not mean malicious.\nNo models were trained and no AUC values were recomputed in this audit.",
        fontsize=10,
        color=navy,
    )
    save(fig, folder, "dataset_versions", plt)
    fig, axes = plt.subplots(1, 2, figsize=(13, 7))
    fig.subplots_adjust(left=0.1, right=0.97, top=0.77, bottom=0.37, wspace=0.3)
    ordered = sorted(
        cohort,
        key=lambda r: {
            "original_good": 0,
            "original_uncertain": 1,
            "teammate_good": 2,
            "maintenance_counterexample": 3,
        }[r["dataset_source"]],
    )
    labels = ["Original good\nn=82", "Original uncertain\nn=24", "Teammate good\nn=30", "Maintenance examples\nn=30"]
    groups = [
        [float(r["days_since_push"]) for r in frozen if r["dataset_source"] == c["dataset_source"]] for c in ordered
    ]
    axes[0].boxplot(groups, showfliers=True)
    axes[0].set_yscale("symlog", linthresh=1)
    axes[0].set_ylabel("Days since push (symlog scale)")
    axes[0].set_title("Push recency varies with selection source", fontsize=12, weight="bold")
    percentages = [100 * c["archived"] / c["n"] for c in ordered]
    axes[1].bar(range(1, 5), percentages, color=[blue, orange, blue, orange])
    for i, c in enumerate(ordered, 1):
        axes[1].text(i, percentages[i - 1] + 2, f"{c['archived']}/{c['n']}", ha="center")
    axes[1].set_ylim(0, 112)
    axes[1].set_ylabel("Archived repositories (%)")
    axes[1].set_title("Archival is concentrated in the selected cohort", fontsize=12, weight="bold")
    for ax in axes:
        ax.set_xticks(range(1, 5), labels, rotation=25, ha="right")
        ax.grid(axis="y", alpha=0.13)
        ax.set_axisbelow(True)
    fig.suptitle(
        "Selection can make the dataset easier than the real task",
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
        "Maintenance counterexamples were deliberately selected; 29 of 30 are archived.",
        fontsize=12,
        color=navy,
    )
    fig.text(
        0.05,
        0.065,
        "This is a descriptive cohort audit, not feature ranking, a new classifier or an evaluation result.\nSource groups encode labels by construction; source/reason fields belong in provenance, not predictor inputs.\nArchival can reflect a legitimate project's lifecycle. It does not establish maliciousness or lack of usefulness.",
        fontsize=10,
        color=navy,
    )
    save(fig, folder, "selection_shortcuts", plt)
    # Schema diagram: deterministic input-index gate, not measured missingness from the unavailable 126-row table.
    fig, ax = plt.subplots(figsize=(12, 6.8))
    fig.subplots_adjust(left=0.1, right=0.95, top=0.77, bottom=0.28)
    ax.broken_barh([(0, 82)], (0.6, 0.5), facecolors=blue)
    ax.broken_barh([(82, 24)], (0.6, 0.5), facecolors=orange)
    ax.broken_barh([(106, 24)], (0.6, 0.5), facecolors="#e7b891", hatch="///")
    ax.axvline(106, color=navy, ls="--", lw=2)
    ax.text(41, 0.85, "82 good inputs", ha="center", va="center", color="white", weight="bold")
    ax.text(94, 1.25, "24 uncertain\neligible", ha="center", fontsize=11)
    ax.text(118, 1.25, "24 uncertain\nnot fetched", ha="center", fontsize=11)
    ax.text(53, 0.27, "PR/issue endpoint fetches allowed by index gate", ha="center", fontsize=11)
    ax.text(118, 0.27, "Skipped by gate", ha="center", fontsize=11)
    ax.set_xlim(-1, 132)
    ax.set_ylim(0, 1.9)
    ax.set_yticks([])
    ax.set_xlabel("Input list index (zero based); API failures may remove rows later")
    ax.set_xticks([0, 82, 106, 130])
    ax.grid(axis="x", alpha=0.1)
    fig.suptitle(
        "A collection cap can encode the class ordering",
        x=0.05,
        ha="left",
        y=0.96,
        fontsize=22,
        weight="bold",
        color=navy,
    )
    fig.text(
        0.05,
        0.87,
        "Saved code: concatenate good inputs first, then fetch PR/issue features only for index <106.",
        fontsize=12,
        color=navy,
    )
    fig.text(
        0.05,
        0.06,
        "Illustration of saved code with its printed 82-good / 48-uncertain input list; not a measured confusion matrix.\nThe 126-row feature table is absent, so exact missingness and split effects cannot be reconstructed.\nVidal should inspect collection coverage by class/source before attributing the high AUC to useful signals.",
        fontsize=10,
        color=navy,
    )
    save(fig, folder, "collection_order_cap", plt)


def save(fig, folder, name, plt):
    fig.savefig(folder / (name + ".png"), dpi=180, facecolor="white")
    fig.savefig(folder / (name + ".svg"), facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--evidence", type=Path, default=Path("local_evidence_20261014_01"))
    p.add_argument("--output", type=Path, required=True)
    main(p.parse_args())
