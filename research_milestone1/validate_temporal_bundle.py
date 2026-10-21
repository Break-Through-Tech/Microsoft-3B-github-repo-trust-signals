"""Validate exported bundle integrity and row-preserving staging invariants."""

import argparse
import csv
import hashlib
import json
from pathlib import Path


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def validate(folder):
    folder = folder.resolve()
    for item in json.loads((folder / "manifest.json").read_text()):
        path = (folder / item["path"]).resolve()
        if not path.is_relative_to(folder):
            raise ValueError("Manifest path outside bundle")
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Hash mismatch: " + item["path"])
    mapping = json.loads((folder / "source_map.json").read_text())
    base = rows(folder / mapping["snapshot"])
    preview = rows(folder / "base166_merge_preview.csv")
    assert len(base) == len(preview) == 166
    for a, b in zip(base, preview, strict=False):
        assert a["full_name"].strip().lower() == b["repo_id"]
        assert a["label"] == b["snapshot_label"]
        assert a["dataset_source"] == b["snapshot_dataset_source"]
    long = rows(folder / "temporal_features_long.csv")
    assert len({(r["repo_id"], r["feature_name"]) for r in long}) == len(long)
    for r in long:
        assert (folder / r["source_artifact"]).is_file()
        assert r["model_approved"] == "False"
        if r["value"] != "":
            assert float(r["value"]) >= 0
            assert r["feature_available_at_utc"]
    staging = rows(folder / "temporal_features_staging.csv")
    assert len({r["repo_id"] for r in staging}) == len(staging)
    assert not {"label", "y_good", "score_0_100", "prediction"} & set(staging[0])
    print("PASS: manifest, evidence references, 166-row order/labels, unique keys and staging boundaries")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", type=Path, default=Path.cwd())
    validate(p.parse_args().bundle)
