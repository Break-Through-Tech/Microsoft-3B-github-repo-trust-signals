"""Validate Ethan's handoff and append temporal columns to a selected Task 6 base.

Standard-library runtime only. No network requests, label changes, or model fitting.
"""

from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.parse import urlsplit

Row = dict[str, str]
MISSING_STATUSES = {
    "ineligible_period",
    "creation_or_followup_coverage_insufficient",
    "page_cap_lower_bound",
    "fork_window_not_reached",
    "filtered_api_complete",  # Screening lower bounds are not exact 90-day counts.
}
OBSERVED_STATUSES = {
    "complete_current_branch_recount",
    "complete",
    "indexed_count_complete_response",
    "all_current_public_records",
    "visible_forks_period_enumerated",
    "complete_reachable_history",
    "complete_git_reachable_history",
}


class ValidationError(ValueError):
    """An input violates the declared integration contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def read_csv(path: Path) -> tuple[list[str], list[Row]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        raw = [row for row in csv.reader(stream, strict=True) if row]
    require(bool(raw), f"Empty CSV: {path}")
    header = raw[0]
    require(all(header), f"Blank header: {path}")
    require(len({h.casefold() for h in header}) == len(header), f"Duplicate header: {path}")
    require(all(len(row) == len(header) for row in raw[1:]), f"Ragged CSV: {path}")
    return header, [dict(zip(header, row, strict=True)) for row in raw[1:]]


def write_csv(path: Path, header: list[str], rows: list[Row]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def repo_key(value: str) -> str:
    text = value.strip()
    if text.lower().startswith(("github.com/", "www.github.com/")):
        text = "https://" + text
    if "://" in text:
        parsed = urlsplit(text)
        require(
            parsed.scheme in {"http", "https"}
            and parsed.netloc.lower() in {"github.com", "www.github.com"}
            and not parsed.query
            and not parsed.fragment,
            f"Invalid GitHub URL: {value}",
        )
        text = parsed.path.strip("/")
    text = text.rstrip("/")
    if text.lower().endswith(".git"):
        text = text[:-4]
    require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text)), f"Invalid repo: {value}")
    require(all(part not in {".", ".."} for part in text.split("/")), f"Invalid repo: {value}")
    return text.lower()


def numeric_id(value: str) -> str:
    require(bool(re.fullmatch(r"[1-9][0-9]*", value)), f"Invalid numeric GitHub ID: {value}")
    return value


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"Invalid timestamp: {value}") from exc
    require(result.tzinfo is not None and result.utcoffset() is not None, f"Naive time: {value}")
    offset = result.utcoffset()
    require(offset is not None and offset.total_seconds() == 0, f"Expected UTC: {value}")
    return result


def number(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ValidationError(f"Invalid number: {value}") from exc
    require(math.isfinite(result), f"Nonfinite number: {value}")
    return result


def same_number(left: str, right: str) -> bool:
    if left == "" or right == "":
        return left == right
    return math.isclose(number(left), number(right), rel_tol=1e-12, abs_tol=1e-12)


def unique(rows: list[Row], column: str, aliases: dict[str, str] | None = None) -> dict[str, Row]:
    result: dict[str, Row] = {}
    for row in rows:
        require(column in row, f"Missing key column: {column}")
        key = repo_key(row[column])
        key = (aliases or {}).get(key, key)
        require(key not in result, f"Duplicate or alias-colliding repository key: {key}")
        result[key] = row
    return result


def identities(root: Path) -> tuple[dict[str, str], dict[str, str], list[Row]]:
    _, registry = read_csv(root / "inputs/identity_registry.csv")
    by_name = unique(registry, "repo_id")
    ids = {key: numeric_id(row["github_repo_id"]) for key, row in by_name.items()}
    require(len(set(ids.values())) == len(ids), "Two canonical names share a numeric identity")
    _, alias_rows = read_csv(root / "inputs/alias_crosswalk.csv")
    aliases: dict[str, str] = {}
    for row in alias_rows:
        old, new = repo_key(row["requested_repo_id"]), repo_key(row["canonical_repo_id"])
        require(old not in aliases and old != new, "Duplicate/self alias")
        require(new in ids and ids[new] == row["github_repo_id"], "Alias numeric ID conflict")
        require(old not in ids, "Alias collides with a registered canonical name")
        aliases[old] = new
    require(not set(aliases.values()).intersection(aliases), "Alias chains/cycles require review")
    _, crosswalk = read_csv(root / "inputs/base_identity_crosswalk.csv")
    unique(crosswalk, "repo_id", aliases)
    for row in crosswalk:
        key = aliases.get(repo_key(row["repo_id"]), repo_key(row["repo_id"]))
        if row["github_repo_id"]:
            require(ids.get(key) == numeric_id(row["github_repo_id"]), "Crosswalk identity conflict")
    return ids, aliases, crosswalk


def source_value(row: Row, root: Path) -> str:
    """Look up the owner's measurement in the supplied evidence, without new collection."""
    key, feature, artifact = row["repo_id"], row["feature_name"], row["source_artifact"]
    if artifact == "evidence/candidate_results.json":
        candidates = json.loads((root / artifact).read_text(encoding="utf-8"))
        matches = [c for c in candidates if repo_key(c["canonical_full_name"]) == key]
        require(len(matches) == 1, f"Missing/duplicate candidate evidence: {key}")
        candidate = matches[0]
        require(str(candidate["repo_id"]) == row["github_repo_id"], "Evidence identity mismatch")
        require(candidate["head_sha"] == row["head_sha"], "Evidence head SHA mismatch")
        require(candidate["coverage"] == row["coverage_status"], "Candidate coverage mismatch")
        require(candidate["window_start"] == row["window_start_utc"], "Candidate window mismatch")
        require(
            candidate["window_end_exclusive"] == row["window_end_exclusive_utc"],
            "Candidate end mismatch",
        )
        value = candidate["nonmerge_commits_90d"]
        return "" if value is None else str(value)
    _, evidence = read_csv(root / artifact)
    matches = [r for r in evidence if repo_key(r["repository"]) == key]
    require(
        all(r["repo_id"] == row["github_repo_id"] for r in matches),
        "Evidence numeric identity mismatch",
    )
    if artifact == "evidence/pilot_features.csv":
        require(len(matches) == 1, f"Pilot source identity mismatch: {key}")
        source = matches[0]
        mapping = {
            "temporal__pre_median_weekly_commits": "pre_median",
            "temporal__post_median_weekly_commits_8w": "post_median_8w",
            "temporal__post_pre_commit_ratio": "post_pre_ratio",
            "temporal__post_active_week_share_8w": "post_active_week_share_8w",
        }
        require(feature in mapping, f"Undeclared pilot feature: {feature}")
        require(source["head_sha"] == row["head_sha"], "Pilot head mismatch")
        require(
            source["feature_available_at_utc"] == row["feature_available_at_utc"],
            "Pilot availability mismatch",
        )
        return source[mapping[feature]]
    if artifact == "evidence/pilot_weeks.csv":
        matches = [r for r in matches if r["weeks_from_peak"] == "0"]
        require(len(matches) == 1, f"Peak week evidence mismatch: {key}")
        source = matches[0]
        require(source["head_sha"] == row["head_sha"], "Peak head mismatch")
        require(source["week_start_utc"] == row["window_start_utc"], "Peak window mismatch")
        require(source["week_end_exclusive_utc"] == row["window_end_exclusive_utc"], "Peak end mismatch")
        return source["nonmerge_commits_committer_utc"]
    require(artifact == "evidence/engagement.csv", f"Unmapped evidence source: {artifact}")
    suffix = feature.removeprefix("temporal__")
    match = re.fullmatch(r"(issue_opened|pr_opened|releases|forks)_(pre_4w|peak_1w|post_8w)_(count|per_week)", suffix)
    require(match is not None, f"Unmapped engagement feature: {feature}")
    assert match is not None
    event, period, kind = match.groups()
    matches = [r for r in matches if r["event_kind"] == event and r["period"] == period]
    require(len(matches) == 1, f"Engagement source match failure: {key}/{feature}")
    source = matches[0]
    require(source["period_start_utc"] == row["window_start_utc"], "Engagement window mismatch")
    require(
        source["period_end_exclusive_utc"] == row["window_end_exclusive_utc"],
        "Engagement end mismatch",
    )
    require(
        source["feature_available_at_utc"] == row["feature_available_at_utc"],
        "Engagement availability mismatch",
    )
    require(source["source_scope"] == row["source_scope"], "Engagement scope mismatch")
    if row["coverage_status"] in MISSING_STATUSES:
        return ""
    require(source["full_period_eligible"] == "True", "Observed ineligible engagement period")
    require(source["coverage"] == row["coverage_status"], "Engagement coverage mismatch")
    return source["reported_count" if kind == "count" else "count_per_week"]


def load_handoff(root: Path) -> dict[str, Any]:
    ids, aliases, crosswalk = identities(root)
    spec = json.loads((root / "inputs/task6_source_spec_PROPOSED.json").read_text(encoding="utf-8"))
    rules = spec["features"]
    require(isinstance(rules, dict) and len(rules) == 30, "Expected 30 explicitly declared features")
    require(
        all(re.fullmatch(r"temporal__[a-z0-9_]+", k) for k in rules),
        "Metadata/label requested as feature",
    )
    _, dictionary = read_csv(root / "inputs/feature_dictionary.csv")
    require(len(dictionary) == len(rules), "Feature dictionary size mismatch")
    require({r["feature_name"] for r in dictionary} == set(rules), "Feature dictionary mismatch")
    for entry in dictionary:
        rule = rules[entry["feature_name"]]
        require(
            rule["dtype"] == entry["dtype"] and rule["unit"] == entry["unit"],
            "Feature type/unit mismatch",
        )
    header, staging = read_csv(root / "inputs/temporal_features_staging.csv")
    require(
        set(header) == set(rules) | {"repo_id", "github_repo_id", "collected_at", "review_status"},
        "Undeclared staging columns",
    )
    wide = unique(staging, "repo_id", aliases)
    for key, row in wide.items():
        require(ids.get(key) == numeric_id(row["github_repo_id"]), f"Staging identity conflict: {key}")
    long_header, long = read_csv(root / "inputs/temporal_features_long.csv")
    expected_long = {
        "repo_id",
        "github_repo_id",
        "feature_name",
        "value",
        "coverage_status",
        "window_start_utc",
        "window_end_exclusive_utc",
        "feature_available_at_utc",
        "head_sha",
        "source_artifact",
        "source_scope",
        "review_status",
        "model_approved",
    }
    require(set(long_header) == expected_long, "Long-table schema drift")
    values: dict[tuple[str, str], Row] = {}
    warnings: list[Row] = []
    for row in long:
        key = aliases.get(repo_key(row["repo_id"]), repo_key(row["repo_id"]))
        require(key == row["repo_id"], "Long table must use resolved lowercase keys")
        feature = row["feature_name"]
        require(feature in rules, f"Undeclared feature: {feature}")
        require((key, feature) not in values, f"Duplicate repo-feature key: {key}/{feature}")
        require(ids.get(key) == numeric_id(row["github_repo_id"]), "Long-table identity conflict")
        require(key in wide, f"Long key absent from staging: {key}")
        start, end = timestamp(row["window_start_utc"]), timestamp(row["window_end_exclusive_utc"])
        require(start < end, f"Reversed/empty observation window: {key}/{feature}")
        available = timestamp(row["feature_available_at_utc"]) if row["feature_available_at_utc"] else None
        status, value = row["coverage_status"], row["value"]
        require(status in MISSING_STATUSES | OBSERVED_STATUSES, f"Unknown coverage status: {status}")
        require(
            (value == "") == (status in MISSING_STATUSES),
            f"Coverage/value mismatch: {key}/{feature}",
        )
        if value:
            rule = rules[feature]
            number_value = number(value)
            require(number_value >= rule.get("min", 0), "Value below minimum")
            if "max" in rule:
                require(number_value <= rule["max"], "Value above maximum")
            if rule["dtype"] == "integer":
                require(number_value % 1 == 0 and number_value <= 2**53 - 1, "Invalid exact integer")
            if feature.endswith("share_8w"):
                require(number_value <= 1, "Share exceeds one")
            require(available is not None and available >= end, "Measurement unavailable at window end")
        if row["head_sha"]:
            require(bool(re.fullmatch(r"[0-9a-f]{40}", row["head_sha"])), "Invalid head SHA")
        if "commits" in feature or feature in {
            "temporal__post_pre_commit_ratio",
            "temporal__post_active_week_share_8w",
        }:
            require(bool(row["head_sha"]), "Commit-derived feature missing head SHA")
        artifact = (root / row["source_artifact"]).resolve()
        require(
            artifact.is_relative_to((root / "evidence").resolve()) and artifact.is_file(),
            "Invalid/missing portable evidence path",
        )
        if not row["source_scope"]:
            warnings.append(
                {
                    "repo_id": key,
                    "feature_name": feature,
                    "code": "SOURCE_SCOPE_BLANK",
                    "message": "Original long row has no scope text; retained blank. See linked peak-week evidence and method proposal.",
                }
            )
        require(same_number(value, source_value(row, root)), f"Evidence value mismatch: {key}/{feature}")
        require(same_number(value, wide[key][feature]), f"Long/wide mismatch: {key}/{feature}")
        values[key, feature] = row
    for key, row in wide.items():
        availability = [
            timestamp(r["feature_available_at_utc"])
            for r in long
            if r["repo_id"] == key and r["feature_available_at_utc"]
        ]
        require(
            bool(availability) and timestamp(row["collected_at"]) == max(availability),
            "Staging collected_at is not latest per-feature availability",
        )
        for feature in rules:
            if (key, feature) not in values:
                require(row[feature] == "", "Staging value lacks long-form provenance")
    return {
        "ids": ids,
        "aliases": aliases,
        "crosswalk": crosswalk,
        "rules": rules,
        "long_header": long_header,
        "long": long,
        "wide": wide,
        "warnings": warnings,
    }


def integrate(base: Path, root: Path, output: Path, key_column: str, scope: str) -> dict[str, Any]:
    """Append only declared temporal measurements, preserving original columns and order."""
    handoff = load_handoff(root)
    header, base_rows = read_csv(base)
    require(bool(base_rows), "Base dataset has no rows")
    require(key_column in header and "label" in header, "Explicit base key and label required")
    aliases, ids, rules = handoff["aliases"], handoff["ids"], handoff["rules"]
    base_index = unique(base_rows, key_column, aliases)
    require(
        not set(header).intersection(rules),
        "Temporal output column already exists; choose an unmodified base",
    )
    require(all(r["label"] != "" for r in base_rows), "Missing base label")
    supplied_numeric = [r["github_repo_id"] for r in base_rows if r.get("github_repo_id")]
    require(len(supplied_numeric) == len(set(supplied_numeric)), "Duplicate base numeric identity")
    output_header = list(header)
    if "repo_id" not in header:
        output_header.append("repo_id")
    if "github_repo_id" not in header:
        output_header.append("github_repo_id")
    output_header.extend(rules)
    merged: list[Row] = []
    reconciliation: list[Row] = []
    for row in base_rows:
        normalized = repo_key(row[key_column])
        key = aliases.get(normalized, normalized)
        if "repo_id" in row:
            require(repo_key(row["repo_id"]) == normalized, "Conflicting base name columns")
        if row.get("github_repo_id"):
            given = numeric_id(row["github_repo_id"])
            require(key not in ids or ids[key] == given, "Base numeric identity conflicts with registry")
        result = dict(row)
        if "repo_id" not in header:
            result["repo_id"] = key
        if "github_repo_id" not in header:
            result["github_repo_id"] = ids.get(key, "")
        source = handoff["wide"].get(key, {})
        result.update({feature: source.get(feature, "") for feature in rules})
        merged.append(result)
        reconciliation.append(
            {
                "input_repo_id": row[key_column],
                "normalized_repo_id": normalized,
                "resolved_repo_id": key,
                "github_repo_id": ids.get(key, row.get("github_repo_id", "")),
                "status": "alias_resolved"
                if normalized != key
                else "registered"
                if key in ids
                else "numeric_ID_not_collected",
            }
        )
    require(len(merged) == len(base_rows), "Row count changed")
    require(
        all({c: new[c] for c in header} == old for old, new in zip(base_rows, merged, strict=True)),
        "Original values/order changed",
    )
    for key, row in base_index.items():
        if row.get("github_repo_id"):
            matching = [k for k, v in ids.items() if v == row["github_repo_id"]]
            require(not matching or matching == [key], "Base numeric/name collision")
    _, reviews = read_csv(root / "inputs/outside_base_review.csv")
    review_index = unique(reviews, "repo_id", aliases)
    review_keys = (set(handoff["wide"]) | set(review_index)) - set(base_index)
    review_rows: list[Row] = []
    for key in sorted(review_keys):
        source = handoff["wide"].get(key, {})
        review_rows.append(
            {
                "repo_id": key,
                "github_repo_id": ids[key],
                "has_feature_rows": str(key in handoff["wide"]),
                "populated_features": str(sum(bool(source.get(f)) for f in rules)),
                "in_frozen_reference": str(any(repo_key(r["repo_id"]) == key for r in handoff["crosswalk"])),
                "proposed_label": "",
                "action": "Zara: confirm membership and label; no automatic inclusion",
            }
        )
    coverage: list[Row] = []
    for feature in rules:
        populated = sum(bool(r[feature]) for r in merged)
        incomplete = sum(
            (key, feature) in {(r["repo_id"], r["feature_name"]) for r in handoff["long"] if r["value"] == ""}
            for key in base_index
        )
        coverage.append(
            {
                "feature_name": feature,
                "base_rows": str(len(base_rows)),
                "populated": str(populated),
                "missing_or_ineligible": str(incomplete),
                "not_collected": str(len(base_rows) - populated - incomplete),
            }
        )
    selected_long = [{**r, "in_selected_base": str(r["repo_id"] in base_index)} for r in handoff["long"]]
    summary = {
        "status": "VALIDATED_PREVIEW_REQUIRES_OWNER_REVIEW",
        "scope": scope,
        "base_rows": len(base_rows),
        "output_rows": len(merged),
        "row_order_preserved": True,
        "original_columns_preserved": True,
        "labels_preserved": True,
        "temporal_feature_columns": len(rules),
        "matched_staging_repositories": len(set(base_index) & set(handoff["wide"])),
        "repositories_with_observed_temporal_values": sum(any(r[f] for f in rules) for r in merged),
        "populated_temporal_cells": sum(bool(r[f]) for r in merged for f in rules),
        "outside_selected_base_review_rows": len(review_rows),
        "evidence_values_verified": len(handoff["long"]),
        "long_records_retained": len(selected_long),
        "source_scope_blank_records": len(handoff["warnings"]),
        "canonical_confirmed": False,
        "contract_confirmed": False,
        "model_ready": False,
        "models_run": False,
        "nulls_imputed": False,
        "label_counts": dict(Counter(r["label"] for r in base_rows)),
    }
    # Validate everything before creating any output dataset.
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / "integration_preview.csv", output_header, merged)
    write_csv(
        output / "per_feature_provenance.csv",
        handoff["long_header"] + ["in_selected_base"],
        selected_long,
    )
    write_csv(
        output / "outside_selected_base_review.csv",
        [
            "repo_id",
            "github_repo_id",
            "has_feature_rows",
            "populated_features",
            "in_frozen_reference",
            "proposed_label",
            "action",
        ],
        review_rows,
    )
    write_csv(output / "identity_reconciliation.csv", list(reconciliation[0]), reconciliation)
    write_csv(output / "coverage.csv", list(coverage[0]), coverage)
    write_csv(
        output / "validation_warnings.csv",
        ["repo_id", "feature_name", "code", "message"],
        handoff["warnings"],
    )
    write_json(output / "validation_report.json", summary)
    write_json(
        output / "predictor_columns_PROPOSED.json",
        {
            "candidate_temporal_columns": list(rules),
            "selection_owner": "Vidal",
            "approved": False,
            "exclude": [
                "label",
                "github_repo_id",
                "review_status",
                "source_scope",
                "model_approved",
                "predictions",
                "reason",
            ],
        },
    )
    # Keep relative evidence links valid in each preview directory.
    shutil.copytree(root / "evidence", output / "evidence")
    inventory = [{"path": str(base.resolve()), "sha256": hashlib.sha256(base.read_bytes()).hexdigest()}]
    for path in sorted(root.rglob("*")):
        if path.is_file():
            inventory.append(
                {
                    "path": str(path.relative_to(root)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    write_json(output / "input_versions.json", inventory)
    return summary
