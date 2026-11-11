"""Consolidate supplied repository lists and optional teammate feature exports."""

import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
from typing import Any
from urllib.parse import urlsplit
import uuid

import numpy as np
import pandas as pd

VERSION = "2.2.0"
OWNERS = {"task1": "Ethan", "task2": "Elizabeth", "task3": "Stefan", "task4": "Zara"}
ALIASES = {
    "repo_id": ["repo_id", "repo", "repository", "full_name", "repo_name", "repo_url", "html_url"],
    "label": ["label", "repository_label", "trust_label"],
    "dataset_source": ["dataset_source", "source_file"],
    "discovery_source": ["discovery_source", "inclusion_source"],
    "reason": ["reason", "inclusion_reason", "dataset_reason"],
}
BASE_COLUMNS = ["repo_id", "label", "dataset_source", "discovery_source", "reason", "label_origin"]
RESERVED = {alias for values in ALIASES.values() for alias in values} | {
    "collected_at",
    "window_start",
    "window_end",
    "github_id",
    "github_repo_id",
    "owner",
    "name",
    "url",
    "split",
    "target",
    "prediction",
    "predicted_label",
    "repo_id_raw",
    "label_origin",
    "review_status",
    "source",
    "record",
    "y_good",
    "score_0_100",
    "prediction_probability",
    "predicted_probability",
}
ISSUE_COLUMNS = ["severity", "source", "owner", "code", "repo_id", "column", "record", "value", "message"]
DICT_COLUMNS = [
    "output_column",
    "role",
    "source",
    "owner",
    "input_file",
    "input_column",
    "dtype",
    "schema_origin",
    "description",
    "unit",
    "minimum",
    "maximum",
    "nullable",
]


def canonical_repo(value: Any) -> str:
    if pd.isna(value) or not str(value).strip():
        raise ValueError("Repository identifier is empty")
    text = str(value).strip()
    if text.lower().startswith(("github.com/", "www.github.com/")):
        text = "https://" + text
    if "://" in text:
        parsed = urlsplit(text)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.netloc.lower() not in {"github.com", "www.github.com"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use a GitHub repository URL without a query or fragment")
        text = parsed.path.strip("/")
    else:
        text = text.rstrip("/")
    if text.lower().endswith(".git"):
        text = text[:-4]
    pieces = text.split("/")
    if len(pieces) != 2 or any(p in {"", ".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in pieces):
        raise ValueError("Expected exactly owner/name; no branches, commits or issue paths")
    return text.lower()


def slug(value: Any) -> str:
    result = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    if not result:
        raise ValueError("Feature/source name must contain letters or digits")
    return result


def consolidate(
    config: dict[str, Any],
    input_dir: Path,
    output_root: Path,
    documentation: str = "",
    script_path: Path | None = None,
) -> dict[str, Any]:
    """Validate and merge declared feature exports without changing base membership.

    Returns the legacy notebook result, including DataFrames, a run directory,
    validation summary and archive. Validation errors suppress dataset outputs.
    """
    input_dir, output_root = Path(input_dir), Path(output_root)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ") + "_" + uuid.uuid4().hex[:6]
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True)
    issues, inventory, dictionary, coverage, source_stats, lineage = [], [], [], [], [], []
    outside_rows: list[dict[str, Any]] = []
    candidate_frames, base_frames, covered_tasks = [], [], set()
    master = merged = None
    owners = {"repository_lists": "Zara", "candidates": "Zara", "pipeline": "Darren"}
    feature_count, metadata_complete = 0, False

    def issue(
        severity: str,
        source: str,
        code: str,
        message: str,
        repo: Any = "",
        column: str = "",
        record: Any = "",
        value: Any = "",
    ) -> None:
        issues.append(
            dict(
                zip(
                    ISSUE_COLUMNS,
                    [
                        severity,
                        source,
                        owners.get(source, "Darren"),
                        code,
                        str(repo),
                        str(column),
                        str(record),
                        str(value),
                        message,
                    ],
                    strict=True,
                )
            )
        )

    def read_csv(spec: dict[str, Any], source: str) -> pd.DataFrame | None:
        filename = spec.get("file", "")
        if not filename or Path(filename).name != filename:
            raise ValueError("Use a filename inside the input directory")
        path = input_dir / filename
        if not path.is_file():
            issue("ERROR", source, "MISSING_FILE", f"Configured input {filename} is missing.")
            return None
        content = path.read_bytes()
        inventory.append(
            {"source": source, "file": filename, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        )
        try:
            rows = list(csv.reader(content.decode("utf-8-sig").splitlines(keepends=True), strict=True))
            if not rows:
                raise ValueError("Empty CSV")
            headers = [h.strip() for h in rows[0]]
            if not all(headers) or len({h.casefold() for h in headers}) != len(headers):
                raise ValueError("Blank or duplicate column names")
            rows = [r for r in rows[1:] if r and any(v.strip() for v in r)]
            if any(len(r) != len(headers) for r in rows):
                raise ValueError("Inconsistent CSV field counts")
            df = pd.DataFrame(rows, columns=headers, dtype="string")
            for col in df:
                df[col] = df[col].str.strip().replace("", pd.NA)
            inventory[-1]["rows"] = len(df)
            if df.empty:
                issue("ERROR", source, "EMPTY_TABLE", "The configured CSV has no data rows.")
            return df
        except (UnicodeError, ValueError, csv.Error) as exc:
            issue("ERROR", source, "INVALID_CSV", str(exc))
            return None

    def pick(df: pd.DataFrame, field: str, spec: dict[str, Any], source: str, required: bool = True) -> str | None:
        mapping = spec.get("columns", {})
        if field in mapping:
            selected = mapping[field]
            if selected in df:
                return selected
            issue("ERROR", source, "MISSING_COLUMN", f"Mapped column {selected!r} is absent.", column=field)
            return None
        lookup = {c.lower(): c for c in df}
        found = [lookup[c] for c in ALIASES[field] if c in lookup]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            issue(
                "ERROR", source, "AMBIGUOUS_COLUMN", f"Set columns[{field!r}] explicitly; found {found}.", column=field
            )
        elif required:
            issue("ERROR", source, "MISSING_COLUMN", f"Need a {field} column or explicit mapping.", column=field)
        return None

    def identify(df: pd.DataFrame, key_col: str, source: str) -> pd.Series:
        keys = []
        for idx, value in df[key_col].items():
            try:
                key = canonical_repo(value)
                keys.append(key)
                if str(value) != key:
                    issue(
                        "INFO",
                        source,
                        "ID_NORMALIZED",
                        "Standardized case/URL syntax. No lookup or rename matching performed.",
                        key,
                        key_col,
                        idx + 2,
                        value,
                    )
            except ValueError as exc:
                keys.append(pd.NA)
                issue("ERROR", source, "INVALID_REPO_ID", str(exc), column=key_col, record=idx + 2, value=value)
        keys = pd.Series(keys, index=df.index, dtype="string")
        for idx in keys[keys.notna() & keys.duplicated(keep=False)].index:
            issue(
                "ERROR",
                source,
                "DUPLICATE_REPO",
                "Resolve duplicate repository rows with the source owner; no arbitrary row is selected.",
                keys[idx],
                key_col,
                idx + 2,
            )
        return keys

    def fail_rows(
        mask: pd.Series, source: str, code: str, message: str, keys: pd.Series, column: str, raw: pd.Series
    ) -> None:
        for idx in mask.fillna(False)[lambda s: s].index:
            issue("ERROR", source, code, message, keys[idx], column, idx + 2, raw[idx])

    def as_feature(
        raw: pd.Series, rule: dict[str, Any], source: str, column: str, keys: pd.Series
    ) -> tuple[pd.Series, str, str]:
        dtype = rule.get("dtype", "auto")
        origin = "inferred" if dtype == "auto" else "declared"
        present = raw.dropna()
        if dtype == "auto":
            if not present.empty and present.str.lower().isin(["true", "false"]).all():
                dtype = "boolean"
            elif not present.empty and pd.to_numeric(present, errors="coerce").notna().all():
                dtype = "number"
            else:
                dtype = "string"
            issue(
                "INFO",
                source,
                "INFERRED_TYPE",
                f"Inferred {dtype}. Confirm with the feature owner or declare a type.",
                column=column,
            )
        if dtype in {"number", "integer"}:
            result = pd.to_numeric(raw, errors="coerce")
            bad = raw.notna() & (result.isna() | ~np.isfinite(result.astype(float)))
            fail_rows(
                bad,
                source,
                "INVALID_NUMBER",
                "Expected a finite numeric value; leave missing values blank.",
                keys,
                column,
                raw,
            )
            result = result.mask(bad)
            if dtype == "integer":
                bad = result.notna() & ((result % 1 != 0) | (result.abs() > 2**53 - 1))
                fail_rows(
                    bad,
                    source,
                    "INVALID_INTEGER",
                    "Expected an exact integer within +/- (2^53 - 1).",
                    keys,
                    column,
                    raw,
                )
                result = result.mask(bad).astype("Int64")
            else:
                result = result.astype("Float64")
            for name, operation in [("min", lambda x, b: x < b), ("max", lambda x, b: x > b)]:
                if name in rule:
                    fail_rows(
                        operation(result, rule[name]),
                        source,
                        "OUT_OF_RANGE",
                        f"Violates owner-declared {name}={rule[name]}.",
                        keys,
                        column,
                        raw,
                    )
        elif dtype == "boolean":
            result = raw.str.lower().map({"true": True, "false": False, "1": True, "0": False})
            fail_rows(
                raw.notna() & result.isna(), source, "INVALID_BOOLEAN", "Use true/false or 1/0.", keys, column, raw
            )
            result = result.astype("boolean")
        elif dtype == "string":
            result = raw.astype("string")
        else:
            raise ValueError(f"Invalid dtype {dtype!r}; use number, integer, boolean, string or auto")
        if not rule.get("nullable", True):
            fail_rows(raw.isna(), source, "REQUIRED_VALUE", "This column is declared non-nullable.", keys, column, raw)
        if "choices" in rule:
            fail_rows(
                raw.notna() & ~raw.isin([str(x) for x in rule["choices"]]),
                source,
                "INVALID_CATEGORY",
                "Value is outside the owner-declared choices.",
                keys,
                column,
                raw,
            )
        return result, dtype, origin

    try:
        allowed = config.get("allowed_labels", ["good", "uncertain"])
        if (
            not allowed
            or not isinstance(allowed, list)
            or not all(isinstance(v, str) and v.strip() == v and v for v in allowed)
        ):
            raise ValueError("allowed_labels must be a nonempty list of exact label strings")
        for flag in ["canonical_confirmed", "contract_confirmed"]:
            if not isinstance(config.get(flag, False), bool):
                raise ValueError(f"{flag} must be a Boolean")
        # Canonical files supersede the starter good/uncertain lists only when explicitly configured.
        specs = [config["canonical"]] if config.get("canonical") else config.get("repository_lists", [])
        if not specs:
            raise ValueError("Configure a canonical CSV or the existing good/uncertain list sources")
        for spec in specs:
            source = "repository_lists"
            df = read_csv(spec, source)
            if df is None:
                continue
            key_col = pick(df, "repo_id", spec, source)
            if key_col is None:
                continue
            keys = identify(df, key_col, source)
            label_col = pick(df, "label", spec, source, required="label" not in spec)
            label = df[label_col] if label_col else pd.Series(spec.get("label", pd.NA), index=df.index, dtype="string")
            if label_col and "label" in spec:
                fail_rows(
                    label.notna() & (label != spec["label"]),
                    source,
                    "LABEL_CONFLICT",
                    "Row label conflicts with the configured list label.",
                    keys,
                    label_col,
                    label,
                )
            fail_rows(
                label.isna() | ~label.isin(allowed),
                source,
                "INVALID_LABEL",
                f"Allowed labels: {allowed}. No remapping is performed.",
                keys,
                "label",
                label,
            )
            base = pd.DataFrame({"repo_id": keys, "label": label})
            for field in ["dataset_source", "discovery_source", "reason"]:
                column = pick(df, field, spec, source, required=False)
                base[field] = df[column] if column else (spec["file"] if field == "dataset_source" else pd.NA)
            base["label_origin"] = f"column:{label_col}" if label_col else f"configured file membership:{spec['file']}"
            base_frames.append(base)
            lineage.append(
                pd.DataFrame(
                    {
                        "repo_id": keys,
                        "source": source,
                        "input_file": spec["file"],
                        "record": df.index + 2,
                        "repo_id_raw": df[key_col],
                    }
                )
            )
        if base_frames:
            master = pd.concat(base_frames, ignore_index=True)
            for repo, group in master[master.repo_id.notna()].groupby("repo_id"):
                if len(group) > 1:
                    code = "LABEL_CONFLICT" if group.label.nunique() > 1 else "DUPLICATE_REPO"
                    issue(
                        "ERROR",
                        "repository_lists",
                        code,
                        "Repository appears in multiple base rows/lists; reconcile with Zara before merging.",
                        repo,
                    )
            if master.repo_id.isna().any() or master.repo_id.duplicated().any() or master.empty:
                master = None
            else:
                master = master[BASE_COLUMNS].sort_values("repo_id").reset_index(drop=True)
                merged = master.copy()
                metadata_complete = master[["dataset_source", "discovery_source", "reason"]].notna().all().all()
                for field in ["discovery_source", "reason"]:
                    n = int(master[field].isna().sum())
                    if n:
                        issue(
                            "WARNING",
                            "repository_lists",
                            "METADATA_PENDING",
                            f"{n} repositories lack {field}. Keep it blank until Zara supplies it; a filename is not a discovery rationale.",
                            column=field,
                        )
                for field in BASE_COLUMNS:
                    dictionary.append(
                        {
                            "output_column": field,
                            "role": "target"
                            if field == "label"
                            else "identifier"
                            if field == "repo_id"
                            else "provenance",
                            "source": "repository_lists",
                            "owner": "Zara",
                            "input_file": "See repository_provenance.csv",
                            "input_column": field,
                            "dtype": "string",
                            "schema_origin": "declared",
                            "description": "Repository metadata; never a model predictor",
                            "nullable": field in {"reason", "discovery_source"},
                        }
                    )

        for spec in config.get("candidate_lists", []):
            df = read_csv(spec, "candidates")
            if df is None:
                continue
            col = pick(df, "repo_id", spec, "candidates")
            if col is None:
                continue
            keys = identify(df, col, "candidates")
            existing = set() if master is None else set(master.repo_id)
            proposed = spec.get("proposed_label", "")
            candidate_frames.append(
                pd.DataFrame(
                    {
                        "repo_id": keys,
                        "repo_id_raw": df[col],
                        "source_file": spec["file"],
                        "proposed_label": proposed,
                        "already_in_base": keys.isin(existing),
                        "review_status": "pending Zara review",
                    }
                )
            )
            issue(
                "INFO",
                "candidates",
                "CANDIDATES_HELD_OUT",
                f"{len(df)} candidate rows are listed for review; none are added by this pipeline.",
            )

        if master is not None:
            assert merged is not None
            source_names = set()
            for spec in config.get("feature_sources", []):
                name = slug(spec["name"])
                if name in source_names:
                    raise ValueError("Each feature source needs a unique name after normalization")
                source_names.add(name)
                owners[name] = spec.get("owner", "Confirm with team")
                covers = spec.get("covers_tasks", [])
                if not isinstance(covers, list) or set(covers) - {"task1", "task2", "task3"}:
                    raise ValueError("covers_tasks must list task1/task2/task3; use [] for a Milestone 1 baseline")
                df = read_csv(spec, name)
                if df is None:
                    continue
                key_col = pick(df, "repo_id", spec, name)
                if key_col is None:
                    continue
                keys = identify(df, key_col, name)
                if keys.isna().any() or keys.duplicated().any():
                    continue
                unknown = ~keys.isin(master.repo_id)
                policy = spec.get("outside_base_policy", "error")
                if policy not in {"error", "review"}:
                    raise ValueError("outside_base_policy must be error or review")
                for idx in keys[unknown].index:
                    outside_rows.append(
                        {
                            "source": name,
                            "repo_id": keys[idx],
                            "input_file": spec["file"],
                            "record": idx + 2,
                            "action": "Review membership with Zara; not added to base",
                        }
                    )
                    issue(
                        "WARNING" if policy == "review" else "ERROR",
                        name,
                        "OUTSIDE_BASE_LIST",
                        "Repository is outside the selected base; retained for review and excluded from the merge.",
                        keys[idx],
                        key_col,
                        idx + 2,
                        df.loc[idx, key_col],
                    )
                missing = sorted(set(master.repo_id) - set(keys))
                for repo in missing:
                    issue(
                        "WARNING",
                        name,
                        "REPO_FEATURES_MISSING",
                        "No feature row supplied; the repository remains and its feature cells stay blank.",
                        repo,
                    )
                label_col = pick(df, "label", spec, name, required=False)
                if label_col:
                    expected = keys.map(master.set_index("repo_id").label)
                    fail_rows(
                        df[label_col].notna() & expected.notna() & (df[label_col] != expected),
                        name,
                        "LABEL_CONFLICT",
                        "Feature label disagrees with the base label; no overwrite performed.",
                        keys,
                        label_col,
                        df[label_col],
                    )
                provenance = pd.DataFrame(
                    {
                        "repo_id": keys,
                        "source": name,
                        "input_file": spec["file"],
                        "record": df.index + 2,
                        "repo_id_raw": df[key_col],
                    }
                )
                dates = {}
                for field in ["collected_at", "window_start", "window_end"]:
                    column = spec.get("columns", {}).get(field, field)
                    raw = (
                        df[column]
                        if column in df
                        else pd.Series(spec.get(field, pd.NA), index=df.index, dtype="string")
                    )
                    parsed = pd.to_datetime(
                        raw.map(lambda v: pd.NaT if pd.isna(v) else pd.to_datetime(v, errors="coerce", utc=True)),
                        utc=True,
                    )
                    fail_rows(
                        raw.notna() & parsed.isna(),
                        name,
                        "INVALID_DATE",
                        "Use an ISO-8601 date or timestamp.",
                        keys,
                        column,
                        raw,
                    )
                    dates[field] = parsed
                    provenance[field] = parsed.map(lambda v: "" if pd.isna(v) else v.isoformat())
                for left, right in [("window_start", "window_end"), ("window_end", "collected_at")]:
                    fail_rows(
                        dates[left] > dates[right],
                        name,
                        "INVALID_TIME_ORDER",
                        f"{left} must not follow {right}.",
                        keys,
                        left,
                        provenance[left],
                    )
                if dates["collected_at"].isna().any():
                    issue(
                        "WARNING",
                        name,
                        "COLLECTION_DATE_MISSING",
                        "Ask the feature owner for collected_at per row or per file.",
                    )
                if (dates["window_start"].isna() != dates["window_end"].isna()).any():
                    issue(
                        "WARNING", name, "INCOMPLETE_WINDOW", "Observation-window metadata have an unmatched start/end."
                    )
                lineage.append(provenance)
                excluded = (
                    RESERVED
                    | {str(v).lower() for v in spec.get("columns", {}).values()}
                    | {str(v).lower() for v in spec.get("ignore_columns", [])}
                )
                features = spec.get("features")
                if features is None:
                    features = {c: {"dtype": "auto"} for c in df if c.lower() not in excluded}
                else:
                    extra = [c for c in df if c.lower() not in excluded and c not in features]
                    if extra:
                        issue(
                            "ERROR",
                            name,
                            "UNDECLARED_FEATURES",
                            f"Add new columns to the agreed schema or ignore_columns: {extra}.",
                        )
                if not features:
                    issue(
                        "ERROR",
                        name,
                        "NO_FEATURES",
                        "This export has no feature columns; a repository list alone is not a feature table.",
                    )
                local = pd.DataFrame({"repo_id": keys})
                outputs = []
                for col, rule in features.items():
                    if col not in df:
                        issue("ERROR", name, "MISSING_FEATURE", "Declared feature column is missing.", column=col)
                        continue
                    if col.lower() in excluded:
                        issue(
                            "ERROR",
                            name,
                            "RESERVED_FEATURE",
                            "Labels, identifiers and metadata cannot be predictors.",
                            column=col,
                        )
                        continue
                    output = name + "__" + slug(rule.get("name", col))
                    if output in local:
                        issue(
                            "ERROR",
                            name,
                            "COLUMN_COLLISION",
                            "Two feature names normalize to the same column; choose distinct names.",
                            column=col,
                        )
                        continue
                    values, dtype, origin = as_feature(df[col], rule, name, col, keys)
                    local[output] = values
                    outputs.append(output)
                    if not rule.get("nullable", True) and missing:
                        issue(
                            "ERROR",
                            name,
                            "REQUIRED_FEATURE_COVERAGE",
                            "Some base repositories lack a row for this non-nullable feature.",
                            column=col,
                        )
                    dictionary.append(
                        {
                            "output_column": output,
                            "role": "feature",
                            "source": name,
                            "owner": owners[name],
                            "input_file": spec["file"],
                            "input_column": col,
                            "dtype": dtype,
                            "schema_origin": origin,
                            "description": rule.get("description", "Confirm definition with owner"),
                            "unit": rule.get("unit", ""),
                            "minimum": rule.get("min", ""),
                            "maximum": rule.get("max", ""),
                            "nullable": rule.get("nullable", True),
                        }
                    )
                local = local.loc[~unknown, ["repo_id", *sorted(outputs)]]
                merged = merged.merge(local, on="repo_id", how="left", validate="one_to_one", sort=False)
                feature_count += len(outputs)
                if outputs:
                    covered_tasks.update(covers)
                source_stats.append(
                    {
                        "source": name,
                        "owner": owners[name],
                        "input_rows": len(df),
                        "matched_repositories": int((~unknown).sum()),
                        "missing_repositories": len(missing),
                        "outside_base": int(unknown.sum()),
                        "feature_columns": len(outputs),
                        "covers_tasks": ";".join(covers),
                    }
                )
                for output in outputs:
                    n = int(merged[output].isna().sum())
                    coverage.append(
                        {
                            "source": name,
                            "column": output,
                            "repositories": len(master),
                            "nonmissing": len(master) - n,
                            "missing": n,
                            "missing_fraction": n / len(master),
                        }
                    )
                    if n == len(master):
                        issue(
                            "WARNING",
                            name,
                            "ALL_VALUES_MISSING",
                            "No observed values in the base dataset.",
                            column=output,
                        )
            if (
                len(merged) != len(master)
                or set(merged.repo_id) != set(master.repo_id)
                or merged.repo_id.duplicated().any()
            ):
                issue(
                    "ERROR",
                    "pipeline",
                    "ROW_INVARIANT",
                    "Merged rows must equal the unique base repository list exactly.",
                )
    except (ValueError, TypeError, KeyError, AttributeError, OSError, OverflowError) as exc:
        issue("ERROR", "pipeline", "CONFIG_OR_INPUT_ERROR", f"{type(exc).__name__}: {exc}")

    pending = [task for task in ["task1", "task2", "task3"] if task not in covered_tasks]
    for task in pending:
        issue(
            "WARNING",
            "pipeline",
            "FEATURE_EXPORT_PENDING",
            f"{OWNERS[task]}'s {task} output is not represented. Add an existing export when available; do not recreate it here.",
        )
    if not config.get("canonical_confirmed", False):
        issue(
            "WARNING",
            "repository_lists",
            "CANONICAL_REVIEW_PENDING",
            "Current base comes from supplied lists. Ask Zara to confirm the canonical list and metadata.",
        )
    if not config.get("contract_confirmed", False):
        issue(
            "WARNING",
            "pipeline",
            "AGREEMENT_PENDING",
            "Confirm repository IDs, file/column formats, feature definitions, windows and label semantics with task owners and Vidal.",
        )
    errors = sum(x["severity"] == "ERROR" for x in issues)
    warnings = sum(x["severity"] == "WARNING" for x in issues)
    if errors or master is None:
        status = "FAILED"
    elif feature_count == 0:
        status = "LISTS_ONLY"
    elif pending:
        status = "PARTIAL_FEATURES"
    elif not metadata_complete or not config.get("canonical_confirmed") or not config.get("contract_confirmed"):
        status = "REVIEW_REQUIRED"
    else:
        status = "PASS_WITH_WARNINGS" if warnings else "PASS"
    candidates = (
        pd.concat(candidate_frames, ignore_index=True)
        if candidate_frames
        else pd.DataFrame(
            columns=["repo_id", "repo_id_raw", "source_file", "proposed_label", "already_in_base", "review_status"]
        )
    )
    if not candidates.empty:
        candidates = candidates.sort_values(["repo_id", "source_file"], na_position="last")
    candidates.to_csv(run_dir / "candidate_review.csv", index=False)
    pd.DataFrame(outside_rows, columns=["source", "repo_id", "input_file", "record", "action"]).to_csv(
        run_dir / "outside_base_review.csv", index=False
    )
    dataset_files = []
    if not errors and master is not None:
        master.to_csv(run_dir / "repository_dataset.csv", index=False, lineterminator="\n")
        dataset_files.append("repository_dataset.csv")
        if feature_count and merged is not None:
            merged.to_csv(run_dir / "shared_features.csv", index=False, lineterminator="\n")
            dataset_files.append("shared_features.csv")
    pd.DataFrame(issues, columns=ISSUE_COLUMNS).to_csv(run_dir / "validation_issues.csv", index=False)
    pd.DataFrame(dictionary, columns=DICT_COLUMNS).to_csv(run_dir / "data_dictionary.csv", index=False)
    pd.DataFrame(
        coverage, columns=["source", "column", "repositories", "nonmissing", "missing", "missing_fraction"]
    ).to_csv(run_dir / "feature_coverage.csv", index=False)
    pd.DataFrame(
        source_stats,
        columns=[
            "source",
            "owner",
            "input_rows",
            "matched_repositories",
            "missing_repositories",
            "outside_base",
            "feature_columns",
            "covers_tasks",
        ],
    ).to_csv(run_dir / "source_coverage.csv", index=False)
    provenance_columns = [
        "repo_id",
        "source",
        "input_file",
        "record",
        "repo_id_raw",
        "collected_at",
        "window_start",
        "window_end",
    ]
    provenance = pd.concat(lineage, ignore_index=True) if lineage else pd.DataFrame(columns=provenance_columns)
    provenance.reindex(columns=provenance_columns).sort_values(["repo_id", "source"], na_position="last").to_csv(
        run_dir / "repository_provenance.csv", index=False
    )
    summary = {
        "run_id": run_id,
        "status": status,
        "handoff_ready": status in {"PASS", "PASS_WITH_WARNINGS"},
        "error_count": errors,
        "warning_count": warnings,
        "repository_count": 0 if master is None else len(master),
        "feature_count": feature_count,
        "pending_tasks": pending,
        "candidate_rows": len(candidates),
        "candidate_repositories": int(candidates.repo_id.nunique()),
        "candidates_added_by_pipeline": 0,
        "label_counts": {}
        if master is None
        else {str(k): int(v) for k, v in master.label.value_counts(dropna=False).items()},
        "metadata_complete": bool(metadata_complete),
        "dataset_files": dataset_files,
        "note": "Labels come from input data or explicit file-membership configuration. Uncertain is not a confirmed negative. No specialized features or models are created.",
    }
    config_text = json.dumps(config, indent=2, sort_keys=True)
    (run_dir / "config.json").write_text(config_text, encoding="utf-8")
    (run_dir / "validation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {
        "pipeline_version": VERSION,
        "run_id": run_id,
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "config_sha256": hashlib.sha256(config_text.encode()).hexdigest(),
        "inputs": inventory,
        "dataset_sha256": {name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest() for name in dataset_files},
    }
    if script_path:
        shutil.copy2(script_path, run_dir / "consolidate.py")
        manifest["pipeline_sha256"] = hashlib.sha256(Path(script_path).read_bytes()).hexdigest()
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "README.md").write_text(documentation, encoding="utf-8")
    agreement = [
        {
            "task": task,
            "owner": owner,
            "agreed_filename_or_source": "",
            "repo_key": "owner/name",
            "definitions_types_units": "",
            "collection_window": "",
            "confirmed_by": "",
            "confirmed_at": "",
        }
        for task, owner in OWNERS.items()
    ]
    agreement.append(
        {
            "task": "task5",
            "owner": "Vidal",
            "agreed_filename_or_source": "shared_features.csv",
            "repo_key": "owner/name",
            "definitions_types_units": "",
            "collection_window": "",
            "confirmed_by": "",
            "confirmed_at": "",
        }
    )
    pd.DataFrame(agreement).to_csv(run_dir / "input_agreement.csv", index=False)
    lines = [
        "# Task 6 validation report",
        "",
        f"Status: **{status}**",
        f"Handoff ready: **{summary['handoff_ready']}**",
        "",
        f"Base repositories: {summary['repository_count']}; labels: {summary['label_counts']}",
        f"Feature columns: {feature_count}",
        f"Candidates kept separate: {len(candidates)}; added by pipeline: 0",
        f"Validation errors: {errors}; warnings: {warnings}",
        "",
        "## Source coverage",
        "",
    ]
    if source_stats:
        lines += [
            "| Source | Input rows | Matched base rows | Missing base rows | Outside base | Feature columns |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        lines += [
            f"| {s['source']} | {s['input_rows']} | {s['matched_repositories']} | {s['missing_repositories']} | {s['outside_base']} | {s['feature_columns']} |"
            for s in source_stats
        ]
        lines += [
            "",
            "## Feature coverage",
            "",
            "| Feature column | Observed | Missing | Total base rows |",
            "|---|---:|---:|---:|",
        ]
        lines += [f"| {s['column']} | {s['nonmissing']} | {s['missing']} | {s['repositories']} |" for s in coverage]
        missing_rows = [s for s in issues if s["code"] == "REPO_FEATURES_MISSING"]
        if missing_rows:
            lines += ["", "Repositories with no source row (retained with missing features):", ""]
            lines += [f"- {s['source']}: `{s['repo_id']}`" for s in missing_rows]
    else:
        lines.append("No feature source was successfully inspected.")
    lines += ["", "## Remaining work", ""]
    if pending:
        lines.append("- Feature exports missing: " + ", ".join(f"{t} ({OWNERS[t]})" for t in pending) + ".")
    if not metadata_complete:
        lines.append("- Zara: provide original discovery source and inclusion reason; missing metadata remain blank.")
    if not config.get("canonical_confirmed", False):
        lines.append("- Zara: confirm the authoritative repository list and review the separate candidates.")
    if not config.get("contract_confirmed", False):
        lines.append("- Darren: agree on input formats, keys, feature definitions/windows and handoff with Tasks 1-5.")
    if not pending and metadata_complete and config.get("canonical_confirmed") and config.get("contract_confirmed"):
        lines.append("- Review validation issues and hand off the dataset with its reports.")
    lines += ["", "## Issue counts", ""]
    counts = {}
    for entry in issues:
        key = (entry["severity"], entry["source"], entry["code"])
        counts[key] = counts.get(key, 0) + 1
    lines += [f"- {severity} / {source} / {code}: {n}" for (severity, source, code), n in sorted(counts.items())]
    lines += [
        "",
        "Detailed records: validation_issues.csv. Errors block both repository and feature dataset files.",
        "LISTS_ONLY means no feature exports have been provided. The repository table is not a completed feature dataset.",
        "PARTIAL_FEATURES/REVIEW_REQUIRED are work in progress, not final ML handoff. No source files are modified.",
    ]
    (run_dir / "validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    archive = shutil.make_archive(str(run_dir), "zip", run_dir)
    return {
        "run_dir": str(run_dir),
        "archive": archive,
        "summary": summary,
        "repositories": master if not errors else None,
        "features": merged if not errors and feature_count else None,
        "candidates": candidates,
    }
