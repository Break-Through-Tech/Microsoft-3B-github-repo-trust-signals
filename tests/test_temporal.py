"""Contract tests for the temporal integration and its packaged evidence."""

from collections.abc import Callable
from pathlib import Path
import shutil
import statistics

import pytest

from gh_signals.temporal import ValidationError, integrate, load_handoff, read_csv, repo_key, write_csv

ROOT = Path(__file__).resolve().parents[1] / "examples/task6"


@pytest.fixture
def handoff(tmp_path: Path) -> Path:
    destination = tmp_path / "handoff"
    shutil.copytree(ROOT / "temporal", destination)
    return destination


def edit_csv(path: Path, edit: Callable[[list[dict[str, str]]], None]) -> None:
    header, rows = read_csv(path)
    edit(rows)
    write_csv(path, header, rows)


def test_working_base_is_preserved(tmp_path: Path) -> None:
    base = ROOT / "expected_baseline.csv"
    result = integrate(base, ROOT / "temporal", tmp_path / "out", "repo_id", "working_preview")
    header, before = read_csv(base)
    _, after = read_csv(tmp_path / "out/integration_preview.csv")
    assert [{c: r[c] for c in header} for r in after] == before
    assert result["base_rows"] == result["output_rows"] == 106
    assert result["repositories_with_observed_temporal_values"] == 0
    assert result["outside_selected_base_review_rows"] == 11
    assert result["long_records_retained"] == result["evidence_values_verified"] == 93
    assert not result["model_ready"]
    assert result["source_scope_blank_records"] == 3
    _, provenance = read_csv(tmp_path / "out/per_feature_provenance.csv")
    _, original = read_csv(ROOT / "temporal/inputs/temporal_features_long.csv")
    assert [{k: v for k, v in r.items() if k != "in_selected_base"} for r in provenance] == original


def test_reference_zero_and_lower_bound(tmp_path: Path) -> None:
    result = integrate(
        ROOT / "temporal/inputs/frozen_repositories_REFERENCE.csv",
        ROOT / "temporal",
        tmp_path / "out",
        "full_name",
        "reference_only",
    )
    _, rows = read_csv(tmp_path / "out/integration_preview.csv")
    by_id = {r["repo_id"]: r for r in rows}
    assert result["base_rows"] == 166
    assert result["populated_temporal_cells"] == 2
    for key in ["python-hyper/h11", "textualize/rich"]:
        assert by_id[key]["temporal__nonmerge_commits_90d"] == "0"
    for key in [
        "burntsushi/ripgrep",
        "rust-lang/regex",
        "pallets/flask",
        "microsoft/ml-for-beginners",
    ]:
        assert by_id[key]["temporal__nonmerge_commits_90d"] == ""
    assert sum(bool(r["github_repo_id"]) for r in rows) == 6


@pytest.mark.parametrize(
    "value",
    ["Python-Hyper/h11", "https://github.com/python-hyper/h11.git", "github.com/python-hyper/h11/"],
)
def test_normalized_key(value: str) -> None:
    assert repo_key(value) == "python-hyper/h11"


@pytest.mark.parametrize("value", ["", "a", "a/b/c", "https://evil.example/a/b", "https://github.com/a/b?q=1", "../b"])
def test_bad_key(value: str) -> None:
    with pytest.raises(ValidationError):
        repo_key(value)


def test_alias_resolution_preserves_input(tmp_path: Path) -> None:
    base = tmp_path / "base.csv"
    write_csv(base, ["repo_id", "label"], [{"repo_id": "qwibitai/nanoclaw", "label": "uncertain"}])
    integrate(base, ROOT / "temporal", tmp_path / "out", "repo_id", "alias_test")
    _, rows = read_csv(tmp_path / "out/integration_preview.csv")
    assert rows[0]["repo_id"] == "qwibitai/nanoclaw"
    assert rows[0]["github_repo_id"] == "1146738089"
    _, identities = read_csv(tmp_path / "out/identity_reconciliation.csv")
    assert identities[0]["resolved_repo_id"] == "nanocoai/nanoclaw"
    _, outside = read_csv(tmp_path / "out/outside_selected_base_review.csv")
    assert "nanocoai/nanoclaw" not in {r["repo_id"] for r in outside}


@pytest.mark.parametrize(
    "kind",
    ["duplicate", "label_conflict", "alias_collision", "numeric_conflict", "column_collision"],
)
def test_reject_bad_base(tmp_path: Path, kind: str) -> None:
    rows = [{"repo_id": "python-hyper/h11", "label": "good"}]
    header = ["repo_id", "label"]
    if kind in {"duplicate", "label_conflict"}:
        rows.append(
            {
                "repo_id": "PYTHON-HYPER/h11",
                "label": "uncertain" if kind == "label_conflict" else "good",
            }
        )
    elif kind == "alias_collision":
        rows = [
            {"repo_id": "qwibitai/nanoclaw", "label": "good"},
            {"repo_id": "nanocoai/nanoclaw", "label": "good"},
        ]
    elif kind == "numeric_conflict":
        header.append("github_repo_id")
        rows[0]["github_repo_id"] = "12345"
    else:
        header.append("temporal__nonmerge_commits_90d")
        rows[0]["temporal__nonmerge_commits_90d"] = "1"
    write_csv(tmp_path / "base.csv", header, rows)
    with pytest.raises(ValidationError):
        integrate(tmp_path / "base.csv", ROOT / "temporal", tmp_path / "out", "repo_id", "bad_base")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate_long",
        "negative",
        "nan",
        "fractional_integer",
        "share_above_one",
        "reversed_window",
        "naive_time",
        "early_availability",
        "ineligible_value",
        "missing_evidence",
        "changed_evidence",
        "identity_conflict",
        "alias_conflict",
        "extra_staging_column",
        "long_wide_mismatch",
    ],
)
def test_reject_bad_handoff(handoff: Path, kind: str) -> None:
    long_path = handoff / "inputs/temporal_features_long.csv"
    header, rows = read_csv(long_path)
    if kind == "duplicate_long":
        rows.append(dict(rows[0]))
    elif kind in {"negative", "nan"}:
        rows[0]["value"] = "-1" if kind == "negative" else "nan"
    elif kind == "fractional_integer":
        rows[4]["value"] = "1.5"
    elif kind == "share_above_one":
        rows[3]["value"] = "1.1"
    elif kind == "reversed_window":
        rows[0]["window_start_utc"] = rows[0]["window_end_exclusive_utc"]
    elif kind == "naive_time":
        rows[0]["feature_available_at_utc"] = "2026-10-20T00:00:00"
    elif kind == "early_availability":
        rows[0]["feature_available_at_utc"] = rows[0]["window_start_utc"]
    elif kind == "ineligible_value":
        next(r for r in rows if r["value"] == "")["value"] = "0"
    elif kind == "missing_evidence":
        rows[0]["source_artifact"] = "../not_allowed.csv"
    elif kind == "changed_evidence":
        edit_csv(handoff / "evidence/pilot_features.csv", lambda r: r[0].update(pre_median="99"))
    elif kind == "identity_conflict":
        rows[0]["github_repo_id"] = "12345"
    elif kind == "alias_conflict":
        edit_csv(handoff / "inputs/alias_crosswalk.csv", lambda r: r[0].update(github_repo_id="12345"))
    elif kind == "extra_staging_column":
        p = handoff / "inputs/temporal_features_staging.csv"
        h, r = read_csv(p)
        write_csv(p, [*h, "prediction"], [{**x, "prediction": "0.9"} for x in r])
    elif kind == "long_wide_mismatch":
        p = handoff / "inputs/temporal_features_staging.csv"
        edit_csv(p, lambda r: r[0].update(temporal__pre_median_weekly_commits="999"))
    write_csv(long_path, header, rows)
    with pytest.raises(ValidationError):
        load_handoff(handoff)


def test_no_metadata_is_a_predictor(tmp_path: Path) -> None:
    handoff = load_handoff(ROOT / "temporal")
    rules = handoff["rules"]
    assert len(rules) == 30
    assert not {
        "label",
        "review_status",
        "reason",
        "prediction",
        "github_repo_id",
        "model_approved",
        "collected_at",
    }.intersection(rules)


def test_weekly_evidence_supports_pilot_aggregates() -> None:
    _, weeks = read_csv(ROOT / "temporal/evidence/pilot_weeks.csv")
    _, pilots = read_csv(ROOT / "temporal/evidence/pilot_features.csv")
    for pilot in pilots:
        selected = [r for r in weeks if r["repository"] == pilot["repository"]]
        pre = [
            int(r["nonmerge_commits_committer_utc"])
            for r in selected
            if -4 <= int(r["weeks_from_peak"]) <= -1 and r["coverage_status"] == "complete"
        ]
        post = [
            int(r["nonmerge_commits_committer_utc"])
            for r in selected
            if 1 <= int(r["weeks_from_peak"]) <= 8 and r["coverage_status"] == "complete"
        ]
        assert len(pre) == int(pilot["full_pre_weeks"])
        assert len(post) == int(pilot["full_post_weeks"])
        if len(pre) == 4:
            assert statistics.median(pre) == float(pilot["pre_median"])
        if len(post) == 8:
            assert statistics.median(post) == float(pilot["post_median_8w"])
            assert sum(v > 0 for v in post) / 8 == float(pilot["post_active_week_share_8w"])


def test_repo_lists_match_saved_working_membership() -> None:
    for new, old in [
        ("good_repos.csv", "good_repos(1).csv"),
        ("uncertain.csv", "uncertain(1).csv"),
    ]:
        _, repo = read_csv(ROOT.parents[1] / "data" / new)
        _, saved = read_csv(ROOT / "inputs" / old)
        assert [repo_key(r["repo"]) for r in repo] == [repo_key(r["repo"]) for r in saved]


def test_output_directory_cannot_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        integrate(ROOT / "expected_baseline.csv", ROOT / "temporal", output, "repo_id", "test")
    assert marker.read_text(encoding="utf-8") == "keep"
