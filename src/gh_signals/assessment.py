"""Shared assessment entry point for the CLI and website."""

from collections.abc import Mapping
import csv
import math
from pathlib import Path
from typing import Literal, Protocol, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gh_signals.consolidation import RESERVED, canonical_repo

FeatureValue = float | int | bool | None


class FeatureDefinition(BaseModel):
    """A selected model input, including the owner's missing-value policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    dtype: Literal["number", "integer", "boolean"] = "number"
    nullable: bool = False

    @model_validator(mode="after")
    def reject_metadata(self) -> Self:
        """Prevent identifiers, study labels and previous scores from entering a model."""
        if self.name.lower().split("__")[-1] in RESERVED:
            raise ValueError(f"Metadata cannot be a model feature: {self.name}")
        return self


class ModelContract(BaseModel):
    """Feature and version definitions shipped with Vidal's assessment adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    features: tuple[FeatureDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_features(self) -> Self:
        if len({feature.name for feature in self.features}) != len(self.features):
            raise ValueError("Model feature names must be unique")
        return self


class _AssessmentFields(TypedDict):
    repo_id: str
    model_id: str
    model_version: str
    features_used: dict[str, FeatureValue]
    missing_features: tuple[str, ...]


class Assessor(Protocol):
    """Adapter around the selected model, its fitted preprocessing and composite score."""

    @property
    def contract(self) -> ModelContract: ...

    def score(self, features: Mapping[str, FeatureValue]) -> float:
        """Return confidence in a good repository on the selected 0 to 100 scale."""
        ...


class Assessment(BaseModel):
    """Serializable result returned identically to website and CLI callers."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    repo_id: str
    status: Literal["scored", "unscored_model_missing", "insufficient_evidence"]
    score_0_100: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    model_id: str | None = None
    model_version: str | None = None
    features_used: dict[str, FeatureValue] = Field(default_factory=dict)
    missing_features: tuple[str, ...] = ()
    message: str


def _parse(value: str | FeatureValue, feature: FeatureDefinition) -> FeatureValue:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if feature.dtype == "boolean":
        if value in (True, 1, "true", "True", "1"):
            return True
        if value in (False, 0, "false", "False", "0"):
            return False
        raise ValueError(f"Expected a Boolean for {feature.name}")
    if isinstance(value, bool):
        raise ValueError(f"Expected a numeric value for {feature.name}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected a finite value for {feature.name}")
    if feature.dtype == "integer":
        if not number.is_integer() or abs(number) > 2**53 - 1:
            raise ValueError(f"Expected an exact integer for {feature.name}")
        return int(number)
    return number


def assess_repository(
    repo: str,
    features: Mapping[str, str | FeatureValue],
    assessor: Assessor | None = None,
) -> Assessment:
    """Score declared inputs without inferring features, fitting a model or imputing nulls.

    The supplied adapter owns fitted preprocessing and composite-score logic.
    Missing required values block scoring. Missing nullable values reach the
    adapter as None. Study labels and provenance never reach its score method.
    """
    key = canonical_repo(repo)
    if assessor is None:
        return Assessment(
            repo_id=key,
            status="unscored_model_missing",
            message="No selected model adapter is configured. Measurements are available without a trust score.",
        )
    contract = assessor.contract
    if not isinstance(contract, ModelContract):
        raise ValueError("The model adapter must expose a ModelContract")
    values = {feature.name: _parse(features.get(feature.name), feature) for feature in contract.features}
    missing = tuple(name for name, value in values.items() if value is None)
    required_missing = [
        feature.name for feature in contract.features if not feature.nullable and feature.name in missing
    ]
    common: _AssessmentFields = {
        "repo_id": key,
        "model_id": contract.model_id,
        "model_version": contract.model_version,
        "features_used": values,
        "missing_features": missing,
    }
    if required_missing or all(value is None for value in values.values()):
        return Assessment(
            **common,
            status="insufficient_evidence",
            message="Required measurements are missing or no selected feature was observed. No score was produced.",
        )
    raw_score = assessor.score(values)
    if isinstance(raw_score, bool):
        raise ValueError("The model score must be a number from 0 to 100")
    score = float(raw_score)
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError("The model score must be finite and between 0 and 100")
    return Assessment(
        **common,
        status="scored",
        score_0_100=score,
        message="Confidence in a good repository under the selected model; this is not a maliciousness verdict.",
    )


def read_feature_row(path: Path, repo: str, key_column: str = "repo_id") -> dict[str, str]:
    """Select one CSV record, rejecting duplicate normalized keys and malformed rows."""
    target = canonical_repo(repo)
    selected: dict[str, str] | None = None
    seen: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader, [])
        if not header or not all(header) or len({column.casefold() for column in header}) != len(header):
            raise ValueError("Feature CSV needs nonempty, unique column names")
        if key_column not in header:
            raise ValueError(f"Missing repository key column: {key_column}")
        for raw in reader:
            if not raw or not any(value.strip() for value in raw):
                continue
            if len(raw) != len(header):
                raise ValueError("Feature CSV has inconsistent field counts")
            row = dict(zip(header, raw, strict=True))
            key = canonical_repo(row[key_column])
            if key in seen:
                raise ValueError(f"Duplicate repository key: {key}")
            seen.add(key)
            if key == target:
                selected = row
    if selected is None:
        raise ValueError(f"Repository is absent from feature CSV: {target}")
    return selected
