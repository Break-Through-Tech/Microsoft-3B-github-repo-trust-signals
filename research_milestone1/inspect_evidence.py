"""Offline evidence inspection; never executes notebooks or repository code."""

import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


def inspect(root, output):
    output.mkdir(parents=True, exist_ok=False)
    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and output not in p.parents and ".git" not in p.parts and "research_milestone1" not in p.parts
    )
    manifest = []
    for p in files:
        manifest.append(
            {
                "path": str(p.relative_to(root)),
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
        )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    snapshot = next(p for p in files if p.name == "repositories.csv")
    notes = json.loads(snapshot.with_name("snapshot_notes.json").read_text(encoding="utf-8"))
    with snapshot.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == notes["repository_count"] == 166
    assert len({r["full_name"].strip().lower() for r in rows}) == 166
    assert dict(collections.Counter(r["dataset_source"] for r in rows)) == notes["cohort_counts"]
    from datetime import datetime

    as_of = datetime.fromisoformat(notes["analysis_as_of"])
    for r in rows:
        assert datetime.fromisoformat(r["analysis_as_of"]) == as_of
        assert int(r["label"]) == (
            0 if r["dataset_source"] in ("original_uncertain", "maintenance_counterexample") else 1
        )
        age = (as_of - datetime.fromisoformat(r["created_at"])).total_seconds() / 86400
        push = (as_of - datetime.fromisoformat(r["pushed_at"])).total_seconds() / 86400
        expected = {
            "repo_age_days": age,
            "days_since_push": push,
            "star_fork_ratio": int(r["stargazers_count"]) / (int(r["forks_count"]) + 1),
            "stars_per_day": int(r["stargazers_count"]) / max(age, 1),
        }
        for key, value in expected.items():
            assert math.isclose(float(r[key]), value, rel_tol=1e-9, abs_tol=1e-9), (r["full_name"], key)
    notebook_summary = []
    for p in files:
        if p.suffix == ".ipynb":
            nb = json.loads(p.read_text(encoding="utf-8"))
            source = "\n".join("".join(c.get("source", [])) for c in nb["cells"])
            notebook_summary.append(
                {
                    "path": str(p.relative_to(root)),
                    "cells": len(nb["cells"]),
                    "mentions_snapshot": notes["snapshot_id"] in source,
                    "mentions_REA": "morluto/rea" in source,
                    "colab_paths": "/content/drive" in source,
                }
            )
    documents = []
    for p in files:
        if p.suffix == ".docx":
            with zipfile.ZipFile(p) as z:
                xml = ET.fromstring(z.read("word/document.xml"))
                paragraphs = [
                    "".join(n.itertext())
                    for n in xml.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                ]
            text = "\n".join(paragraphs)
            target = output / (p.stem + ".txt")
            target.write_text(text, encoding="utf-8")
            documents.append({"source": str(p.relative_to(root)), "extracted_text": target.name})
    # Screening queue is a prioritization aid, not a low-commit measurement or a label.
    eligible = [r for r in rows if r["label"] == "1" and float(r["repo_age_days"]) >= 1826.25]
    eligible.sort(key=lambda r: (-float(r["days_since_push"]), r["full_name"].lower()))
    fields = [
        "full_name",
        "dataset_source",
        "snapshot_age_days",
        "snapshot_days_since_push",
        "screening_basis",
        "nonmerge_commits_90d",
        "commit_coverage",
        "independent_evidence",
        "review_status",
    ]
    with (output / "screening_queue.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in eligible[:6]:
            w.writerow(
                {
                    "full_name": r["full_name"],
                    "dataset_source": r["dataset_source"],
                    "snapshot_age_days": r["repo_age_days"],
                    "snapshot_days_since_push": r["days_since_push"],
                    "screening_basis": "existing label=1; provisional age threshold; descending push recency",
                    "nonmerge_commits_90d": "",
                    "commit_coverage": "not_collected",
                    "independent_evidence": "",
                    "review_status": "unverified; user review required before inclusion",
                }
            )
    summary = {
        "snapshot": notes,
        "snapshot_checks": "passed",
        "notebooks": notebook_summary,
        "documents": documents,
        "queue_size": min(6, len(eligible)),
        "candidate_names": [r["full_name"] for r in eligible[:6]],
        "activity_measurement": "unavailable: snapshot push timestamps do not count commits",
    }
    (output / "inspection.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inspect(args.root.resolve(), args.output.resolve())
