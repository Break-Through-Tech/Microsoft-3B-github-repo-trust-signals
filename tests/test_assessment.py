"""Assessment contracts prevent label leakage and preserve missing measurements."""

from collections.abc import Mapping
import json
from pathlib import Path
from types import ModuleType

import pytest

from gh_signals.assessment import FeatureDefinition, FeatureValue, ModelContract, assess_repository, read_feature_row
from gh_signals.cli import main


class RecordingAssessor:
    """Test adapter only; its fixed score is not a repository trust model."""

    contract = ModelContract(
        model_id="test-only",
        model_version="1",
        features=(
            FeatureDefinition(name="test__count", description="Observed count", unit="count", dtype="integer"),
            FeatureDefinition(name="test__share", description="Observed share", unit="fraction", nullable=True),
        ),
    )

    def __init__(self, output: float = 73.0) -> None:
        self.seen: dict[str, FeatureValue] | None = None
        self.output = output

    def score(self, features: Mapping[str, FeatureValue]) -> float:
        self.seen = dict(features)
        return self.output


def test_model_receives_only_declared_features_and_distinguishes_zero_from_missing() -> None:
    model = RecordingAssessor()
    result = assess_repository(
        "https://github.com/Owner/Repo.git",
        {"test__count": "0", "test__share": "", "label": "good", "score_0_100": "100"},
        model,
    )
    assert result.status == "scored"
    assert result.score_0_100 == 73.0
    assert result.repo_id == "owner/repo"
    assert model.seen == {"test__count": 0, "test__share": None}
    assert result.missing_features == ("test__share",)


def test_required_missing_does_not_call_model() -> None:
    model = RecordingAssessor()
    result = assess_repository("a/b", {"test__count": "", "test__share": "0.5"}, model)
    assert result.status == "insufficient_evidence"
    assert result.score_0_100 is None
    assert model.seen is None


def test_no_model_never_produces_score() -> None:
    result = assess_repository("a/b", {"stars": 900000})
    assert result.status == "unscored_model_missing"
    assert result.score_0_100 is None


@pytest.mark.parametrize("value", ["NaN", "inf", "0.1", True])
def test_bad_integer_values_are_rejected(value: str | bool) -> None:
    with pytest.raises(ValueError, match="Expected"):
        assess_repository("a/b", {"test__count": value}, RecordingAssessor())


@pytest.mark.parametrize("score", [-0.1, 100.1, float("nan"), float("inf"), True])
def test_invalid_model_scores_are_rejected(score: float) -> None:
    with pytest.raises(ValueError, match="model score"):
        assess_repository("a/b", {"test__count": "0"}, RecordingAssessor(score))


@pytest.mark.parametrize("name", ["label", "task__y_good", "task__score_0_100", "repo_id", "reason"])
def test_model_cannot_select_targets_or_metadata(name: str) -> None:
    with pytest.raises(ValueError, match="Metadata"):
        FeatureDefinition(name=name, description="Forbidden input", unit="none")


def test_csv_rejects_duplicate_normalized_keys(tmp_path: Path) -> None:
    path = tmp_path / "features.csv"
    path.write_text("repo_id,value\na/b,0\nhttps://github.com/A/B.git,1\n")
    with pytest.raises(ValueError, match="Duplicate"):
        read_feature_row(path, "a/b")


def test_cli_and_library_return_identical_assessment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = ModuleType("selected_model_test")
    model = RecordingAssessor()
    module.__dict__["assessor"] = model
    import sys

    monkeypatch.setitem(sys.modules, "selected_model_test", module)
    path = tmp_path / "features.csv"
    path.write_text("repo_id,test__count,test__share,label\na/b,0,,good\n")
    output = tmp_path / "result.json"
    code = main(
        [
            "assess",
            "A/B",
            "--features",
            str(path),
            "--assessor",
            "selected_model_test:assessor",
            "--output",
            str(output),
        ]
    )
    actual = json.loads(capsys.readouterr().out)
    expected = assess_repository("a/b", read_feature_row(path, "a/b"), model).model_dump(mode="json")
    assert code == 0
    assert {key: actual[key] for key in expected} == expected
    assert actual["api_usage"]["requests"] == 0
    assert json.loads(output.read_text()) == actual


def test_cli_reports_missing_model_with_distinct_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "features.csv"
    path.write_text("repo_id,test__count\na/b,0\n")
    assert main(["assess", "a/b", "--features", str(path)]) == 3
    assert json.loads(capsys.readouterr().out)["score_0_100"] is None
