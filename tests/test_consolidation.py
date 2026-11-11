"""Regression and failure tests against the original consolidation outputs."""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from gh_signals.consolidation import consolidate

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/task6"


def test_original_baseline_is_unchanged(tmp_path: Path) -> None:
    config = json.loads((EXAMPLE / "config.json").read_text())
    result = consolidate(config, EXAMPLE / "inputs", tmp_path / "runs")
    actual = pd.read_csv(Path(result["run_dir"]) / "shared_features.csv")
    expected = pd.read_csv(EXAMPLE / "expected_baseline.csv")
    pd.testing.assert_frame_equal(actual, expected)
    assert result["summary"]["repository_count"] == 106
    assert result["summary"]["feature_count"] == 9
    assert result["summary"]["error_count"] == 0
    assert result["summary"]["candidate_rows"] == 30
    assert not result["summary"]["handoff_ready"]


@pytest.fixture
def config(tmp_path: Path) -> dict[str, Any]:
    (tmp_path / "base.csv").write_text("repo,label\na/b,good\nc/d,uncertain\n")
    (tmp_path / "features.csv").write_text("repo,count\na/b,0\nc/d,\n")
    return {
        "canonical": {"file": "base.csv", "columns": {"repo_id": "repo"}},
        "feature_sources": [
            {
                "name": "owner",
                "owner": "Team",
                "file": "features.csv",
                "features": {"count": {"dtype": "integer", "min": 0}},
            }
        ],
    }


def test_zero_and_missing_survive_csv_round_trip(tmp_path: Path, config: dict[str, Any]) -> None:
    result = consolidate(config, tmp_path, tmp_path / "runs")
    rows = pd.read_csv(Path(result["run_dir"]) / "shared_features.csv", keep_default_na=False)
    assert rows["owner__count"].tolist() == ["0", ""]
    assert rows["repo_id"].tolist() == ["a/b", "c/d"]


@pytest.mark.parametrize(
    "bad_input",
    [
        "repo,count\na/b,1\nA/B,2\n",
        "repo,count\na/b,-1\n",
        "repo,count\na/b,NaN\n",
        "repo,count\na/b,0.5\n",
        "repo,count\na/b,inf\n",
        "repo,count\nx/y,1\n",
    ],
)
def test_invalid_features_block_dataset_publication(tmp_path: Path, config: dict[str, Any], bad_input: str) -> None:
    (tmp_path / "features.csv").write_text(bad_input)
    result = consolidate(config, tmp_path, tmp_path / "runs")
    assert result["summary"]["status"] == "FAILED"
    assert not (Path(result["run_dir"]) / "shared_features.csv").exists()
    assert (Path(result["run_dir"]) / "validation_issues.csv").exists()


def test_label_conflict_blocks_publication(tmp_path: Path, config: dict[str, Any]) -> None:
    (tmp_path / "features.csv").write_text("repo,count,label\na/b,0,uncertain\n")
    result = consolidate(config, tmp_path, tmp_path / "runs")
    issues = pd.read_csv(Path(result["run_dir"]) / "validation_issues.csv")
    assert "LABEL_CONFLICT" in set(issues["code"])
    assert result["summary"]["status"] == "FAILED"


def test_explicit_outside_review_preserves_base_and_quarantines_rows(tmp_path: Path, config: dict[str, Any]) -> None:
    config["feature_sources"][0]["outside_base_policy"] = "review"
    (tmp_path / "features.csv").write_text("repo,count\na/b,0\nx/y,9\n")
    result = consolidate(config, tmp_path, tmp_path / "runs")
    assert result["summary"]["error_count"] == 0
    run_dir = Path(result["run_dir"])
    assert pd.read_csv(run_dir / "shared_features.csv")["repo_id"].tolist() == ["a/b", "c/d"]
    assert pd.read_csv(run_dir / "outside_base_review.csv")["repo_id"].tolist() == ["x/y"]


def test_contributor_preview_keeps_membership_and_excludes_overlap_and_logins(tmp_path: Path) -> None:
    config = json.loads((EXAMPLE / "config_contributors_preview.json").read_text())
    result = consolidate(config, EXAMPLE / "inputs", tmp_path / "runs")
    assert result["summary"]["error_count"] == 0
    assert result["summary"]["repository_count"] == 106
    assert result["summary"]["feature_count"] == 23
    columns = result["features"].columns
    assert not any("other_good" in column or "login" in column or "y_good" in column for column in columns)
