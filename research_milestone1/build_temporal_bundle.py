"""Build a portable review bundle without changing canonical lists or labels."""

import argparse
import csv
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import shutil
import zipfile


def key(value):
    return value.strip().lower().removeprefix("https://github.com/").rstrip("/").removesuffix(".git")


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def unique(rows, column):
    seen = set()
    for row in rows:
        value = key(row[column])
        if not value or value in seen:
            raise ValueError("Missing or duplicate " + column + ": " + value)
        seen.add(value)
    return seen


def guarded_join(base, wide):
    """One-to-one exact normalized-name preview; no additions or label remapping."""
    unique(base, "full_name")
    unique(wide, "repo_id")
    index = {key(r["repo_id"]): r for r in wide}
    joined = []
    for row in base:
        result = {
            "repo_id": key(row["full_name"]),
            "snapshot_label": row["label"],
            "snapshot_dataset_source": row["dataset_source"],
        }
        for name, value in index.get(result["repo_id"], {}).items():
            if name in ("label", "snapshot_label", "dataset_source", "snapshot_dataset_source"):
                raise ValueError("Feature source attempted label/provenance overwrite")
            if name != "repo_id":
                result[name] = value
        joined.append(result)
    if len(joined) != len(base):
        raise ValueError("Merge changed base row count")
    return joined


def main(args):
    out = args.output.resolve()
    if args.from_bundle and out.is_relative_to(args.from_bundle.resolve()):
        raise ValueError("Rebuild output must be outside the source bundle")
    out.mkdir(parents=True, exist_ok=False)
    evidence = out / "evidence"
    evidence.mkdir()
    if args.from_bundle:
        sources = json.loads((args.from_bundle / "source_map.json").read_text())
        shutil.copytree(args.from_bundle / "evidence", evidence, dirs_exist_ok=True)
    else:
        root = args.root.resolve()
        research = root / "research_milestone1"

        def latest(name):
            return research / (research / name).read_text().strip()

        pilots = latest("latest_pilot_methods.txt")
        engagement = latest("latest_engagement.txt")
        candidates = latest("latest_collection.txt")
        clones = latest("latest_clone_collection.txt")
        snapshot = next((root / "local_evidence_20261014_01").glob("snapshots-*/snapshots/*/repositories.csv"))
        selected = {
            "snapshot": snapshot,
            "pilot_features": pilots / "pilot_features_standardized.csv",
            "pilot_weeks": pilots / "standardized_event_weeks.csv",
            "pilot_manifest": pilots / "history_manifest.json",
            "engagement": engagement / "engagement_features.csv",
            "engagement_raw": engagement / "streams.json",
            "engagement_search": engagement / "search_counts.json",
            "candidate_results": candidates / "verified_activity_results.json",
            "candidate_adoption": candidates / "reviewed_adoption_evidence.json",
            "clone_review": clones / "reviewed_provenance.json",
        }
        sources = {}
        for name, path in selected.items():
            relative = "evidence/" + name + path.suffix
            sources[name] = relative
            shutil.copy2(path, out / relative)
        # Supporting artifacts are copied explicitly, avoiding runtime dependencies and bare Git stores.
        supporting = []
        for repo in ["openclaw_openclaw", "deepseek-ai_DeepSeek-R1", "morluto_rea"]:
            supporting += [
                (pilots / repo / "all_reachable_commits.tsv", "histories/" + repo + ".tsv"),
                (pilots / repo / "metadata.json", "histories/" + repo + "_metadata.json"),
                (pilots / repo / "head.json", "histories/" + repo + "_head.json"),
            ]
        for filename in [
            "discrepancy_audit.json",
            "discrepancy_daily_diagnostic.csv",
            "deepseek_cached_validation.json",
        ]:
            supporting.append((pilots / filename, "methods/" + filename))
        temporal = next((root / "local_evidence_20261014_01").glob("temporal-*/temporal"))
        for path in temporal.rglob("*.json"):
            supporting.append((path, "original_pilots/" + str(path.relative_to(temporal))))
        for path in candidates.glob("*/*.json"):
            supporting.append((path, "candidate_raw/" + str(path.relative_to(candidates))))
        for path in candidates.rglob("full_git_commit_log.tsv"):
            supporting.append((path, "candidate_raw/" + str(path.relative_to(candidates))))
        for name in [
            "PILOT_METHOD_FINDINGS.md",
            "ENGAGEMENT_FINDINGS.md",
            "REA_DAILY_FINDINGS.md",
            "LOW_ACTIVITY_FINDINGS.md",
            "CLONE_FINDINGS.md",
            "VIDAL_AUC_HANDOFF.md",
        ]:
            supporting.append((research / name, "reports/" + name))
        for path, relative in supporting:
            target = evidence / relative
            target.parents[0].mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    (out / "source_map.json").write_text(json.dumps(sources, indent=2))

    def csv_source(name):
        return read_csv(out / sources[name])

    def json_source(name):
        return json.loads((out / sources[name]).read_text())

    base = csv_source("snapshot")
    unique(base, "full_name")
    basekeys = {key(r["full_name"]) for r in base}
    pilots = csv_source("pilot_features")
    weekly = csv_source("pilot_weeks")
    events = csv_source("engagement")
    candidate = json_source("candidate_results")
    clones = json_source("clone_review")
    history = json_source("pilot_manifest")
    identities = {}
    aliases = []

    def identity(name, numeric, source, requested=None):
        name = key(name)
        numeric = int(numeric)
        if name in identities and identities[name]["github_repo_id"] != numeric:
            raise ValueError("Identity conflict: " + name)
        identities[name] = {
            "repo_id": name,
            "github_repo_id": numeric,
            "in_frozen_base": name in basekeys,
            "identity_status": "resolved_public_metadata",
        }
        if requested and key(requested) != name:
            aliases.append(
                {
                    "requested_repo_id": key(requested),
                    "canonical_repo_id": name,
                    "github_repo_id": numeric,
                    "source": source,
                }
            )

    for r in history:
        identity(r["canonical_full_name"], r["repo_id"], "pilot_manifest", r["requested_full_name"])
    for r in candidate:
        identity(r["canonical_full_name"], r["repo_id"], "candidate_results", r["requested_full_name"])
    for r in clones:
        identity(r["canonical_full_name"], r["repo_id"], "clone_review", r["requested_full_name"])
    if len({r["github_repo_id"] for r in identities.values()}) != len(identities):
        raise ValueError("One numeric ID has multiple unresolved canonical names")
    long = []
    dictionary = {}

    def add(
        repo,
        name,
        value,
        coverage,
        start,
        end,
        available,
        source,
        unit,
        dtype="number",
        head=None,
        scope="",
        review="method_review_pending",
    ):
        repo = key(repo)
        if repo not in identities:
            raise ValueError("Unresolved feature identity")
        if value == "":
            value = None
        if value is not None:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("Nonfinite observed value")
            if dtype == "integer":
                if not value.is_integer():
                    raise ValueError("Fractional count")
                value = int(value)
            if value < 0:
                raise ValueError("Negative feature")
        if value is not None and not available:
            raise ValueError("Observed feature lacks availability time")
        if available and end and stamp(end) > stamp(available) and value is not None:
            raise ValueError("Feature predates observation-window end")
        long.append(
            {
                "repo_id": repo,
                "github_repo_id": identities[repo]["github_repo_id"],
                "feature_name": name,
                "value": value,
                "coverage_status": coverage,
                "window_start_utc": start,
                "window_end_exclusive_utc": end,
                "feature_available_at_utc": available,
                "head_sha": head,
                "source_artifact": sources[source],
                "source_scope": scope,
                "review_status": review,
                "model_approved": False,
            }
        )
        dictionary[name] = {
            "feature_name": name,
            "dtype": dtype,
            "unit": unit,
            "minimum": 0,
            "maximum": 1 if "active_week_share" in name else None,
            "owner": "Ethan / Task 1",
            "missingness": "Blank means no qualifying/full observation; never impute in this handoff",
            "description": definition(name),
            "model_status": "candidate_definition_for_Vidal_review_not_selected",
        }

    for r in pilots:
        peak = stamp(r["peak_week_utc"])
        pre = (peak - timedelta(weeks=4)).isoformat()
        post = (peak + timedelta(weeks=1)).isoformat()
        end = (peak + timedelta(weeks=9)).isoformat()
        r["original_reference_utc"]
        mapping = [
            ("pre_median", "pre_median_weekly_commits", pre, peak.isoformat(), "commits/week"),
            ("post_median_8w", "post_median_weekly_commits_8w", post, end, "commits/week"),
            ("post_pre_ratio", "post_pre_commit_ratio", pre, end, "ratio"),
            ("post_active_week_share_8w", "post_active_week_share_8w", post, end, "fraction"),
        ]
        for col, name, start, stop, unit in mapping:
            value = r[col]
            status = "complete_current_branch_recount" if value != "" else "creation_or_followup_coverage_insufficient"
            add(
                r["repository"],
                "temporal__" + name,
                value,
                status,
                start,
                stop,
                r["feature_available_at_utc"],
                "pilot_features",
                unit,
                head=r["head_sha"],
                scope="Current frozen branch recount; nominal star anchor; not original historical branch state",
            )
        peak_row = next(w for w in weekly if w["repository"] == r["repository"] and w["weeks_from_peak"] == "0")
        add(
            r["repository"],
            "temporal__peak_week_nonmerge_commits",
            peak_row["nonmerge_commits_committer_utc"],
            peak_row["coverage_status"],
            peak.isoformat(),
            post,
            r["feature_available_at_utc"],
            "pilot_weeks",
            "commits",
            "integer",
            r["head_sha"],
        )
    for r in events:
        eligible = r["full_period_eligible"] == "True"
        for column, suffix, unit, dtype in [
            ("reported_count", "count", "events", "integer"),
            ("count_per_week", "per_week", "events/week", "number"),
        ]:
            value = r[column] if eligible else None
            add(
                r["repository"],
                f"temporal__{r['event_kind']}_{r['period']}_{suffix}",
                value,
                r["coverage"] if eligible else "ineligible_period",
                r["period_start_utc"],
                r["period_end_exclusive_utc"],
                r["feature_available_at_utc"],
                "engagement",
                unit,
                dtype,
                scope=r["source_scope"],
            )
    for r in candidate:
        value = r["nonmerge_commits_90d"]
        available = r.get("git_verified_at_utc") or r["metadata_collected_at_utc"]
        # Metadata predates full-history pages: use the latest preserved per-response time when present.
        original = args.root / "research_milestone1"
        if not args.from_bundle:
            source_dir = (
                original
                / (original / "latest_collection.txt").read_text().strip()
                / r["requested_full_name"].replace("/", "_")
            )
            times = [json.loads(p.read_text()).get("collected_at_utc", "") for p in source_dir.glob("*.json")]
            available = max([available] + [t for t in times if t])
        else:
            times = [
                json.loads(p.read_text()).get("collected_at_utc", "")
                for p in (evidence / "candidate_raw" / r["requested_full_name"].replace("/", "_")).glob("*.json")
            ]
            available = max([available] + [t for t in times if t])
        add(
            r["canonical_full_name"],
            "temporal__nonmerge_commits_90d",
            value,
            r["coverage"],
            r["window_start"],
            r["window_end_exclusive"],
            available,
            "candidate_results",
            "commits",
            "integer",
            r["head_sha"],
            scope="Full history exact counts only; lower bounds retained in review evidence",
            review="candidate_interpretation_pending",
        )
    keys = [(r["repo_id"], r["feature_name"]) for r in long]
    if len(keys) != len(set(keys)):
        raise ValueError("Multiple feature versions require explicit reconciliation")
    allfeatures = sorted(dictionary)
    measured = {r["repo_id"] for r in long}
    wide = []
    for repo in sorted(measured):
        group = [r for r in long if r["repo_id"] == repo]
        [r for r in group if r["value"] is not None]
        wide.append(
            {
                "repo_id": repo,
                "github_repo_id": identities[repo]["github_repo_id"],
                **{name: next((r["value"] for r in group if r["feature_name"] == name), None) for name in allfeatures},
                "collected_at": max(
                    (r["feature_available_at_utc"] for r in group if r["feature_available_at_utc"]), default=None
                ),
                "review_status": "staging_only_owner_agreement_pending",
            }
        )
    preview = guarded_join(base, wide)
    for row in preview:
        for name in allfeatures:
            row.setdefault(name, None)
        row.setdefault("github_repo_id", None)
        row.setdefault("collected_at", None)
        row.setdefault("review_status", "no_temporal_collection")
    write_csv(out / "temporal_features_long.csv", long)
    write_csv(out / "feature_dictionary.csv", list(dictionary.values()))
    write_csv(out / "temporal_features_staging.csv", wide)
    write_csv(out / "base166_merge_preview.csv", preview)
    write_csv(out / "identity_registry.csv", sorted(identities.values(), key=lambda r: r["repo_id"]))
    write_csv(
        out / "base_identity_crosswalk.csv",
        [
            {
                "repo_id": key(r["full_name"]),
                "github_repo_id": identities.get(key(r["full_name"]), {}).get("github_repo_id"),
                "identity_status": "resolved_public_metadata"
                if key(r["full_name"]) in identities
                else "numeric_ID_not_collected",
            }
            for r in base
        ],
    )
    write_csv(
        out / "alias_crosswalk.csv", aliases, ["requested_repo_id", "canonical_repo_id", "github_repo_id", "source"]
    )
    outside = [
        {
            "repo_id": r["repo_id"],
            "github_repo_id": r["github_repo_id"],
            "has_feature_rows": r["repo_id"] in measured,
            "action": "Task 4 identity/list/label review; not added",
            "proposed_label": "",
        }
        for r in identities.values()
        if not r["in_frozen_base"]
    ]
    write_csv(out / "outside_base_review.csv", outside)
    coverage = []
    for name in allfeatures:
        group = [r for r in long if r["feature_name"] == name]
        coverage.append(
            {
                "feature_name": name,
                "observed_staging_repositories": sum(r["value"] is not None for r in group),
                "observed_in_frozen_base": sum(r["value"] is not None and r["repo_id"] in basekeys for r in group),
                "frozen_base_n": len(base),
                "missing_in_frozen_base": sum(missing_row.get(name) is None for missing_row in preview),
            }
        )
    write_csv(out / "coverage_summary.csv", coverage)
    spec = {
        "name": "ethan_temporal",
        "owner": "Ethan",
        "file": "temporal_features_staging.csv",
        "covers_tasks": ["task1"],
        "columns": {"repo_id": "repo_id", "collected_at": "collected_at"},
        "ignore_columns": ["github_repo_id", "review_status"],
        "features": {
            name: {
                "dtype": rule["dtype"],
                "min": rule["minimum"],
                "unit": rule["unit"],
                "description": rule["description"],
            }
            for name, rule in dictionary.items()
        },
    }
    (out / "task6_source_spec_PROPOSED.json").write_text(json.dumps(spec, indent=2))
    checks = {
        "base_rows": len(base),
        "merge_preview_rows": len(preview),
        "base_labels_unchanged": all(
            str(a["label"]) == str(b["snapshot_label"]) for a, b in zip(base, preview, strict=False)
        ),
        "base_order_preserved": all(key(a["full_name"]) == b["repo_id"] for a, b in zip(base, preview, strict=False)),
        "measured_repository_rows": len(wide),
        "long_feature_rows": len(long),
        "candidate_feature_columns": len(dictionary),
        "resolved_identities": len(identities),
        "aliases": len(aliases),
        "outside_base_review_rows": len(outside),
        "pilot_repositories_matching_frozen_base": sum(key(r["repository"]) in basekeys for r in pilots),
        "base_repositories_with_any_observed_temporal_value": sum(
            any(row.get(name) is not None for name in allfeatures) for row in preview
        ),
        "nulls_imputed": False,
        "models_run": False,
        "new_labels_assigned": False,
        "canonical_dataset_changed": False,
        "team_contract_confirmed": False,
        "model_ready": False,
        "status": "VALIDATED_STAGING_REQUIRES_OWNER_REVIEW",
    }
    assert checks["base_rows"] == checks["merge_preview_rows"] == 166
    assert checks["base_labels_unchanged"]
    assert checks["base_order_preserved"]
    (out / "validation_report.json").write_text(json.dumps(checks, indent=2))
    documentation(out, checks)
    shutil.copy2(Path(__file__), out / "build_temporal_bundle.py")
    manifest = [
        {
            "path": str(p.relative_to(out)).replace("\\", "/"),
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in out.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    ]
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    archive = out.with_suffix(".zip")
    if archive.exists():
        raise FileExistsError("Archive exists")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for p in out.rglob("*"):
            if p.is_file():
                z.write(p, str(p.relative_to(out)))
    print(json.dumps(checks, indent=2))
    print("Archive:", archive)


def documentation(out, checks):
    text = """# Temporal integration review bundle

This is a validated staging package for Tasks 4 and 6 and Vidal. It does not publish a canonical dataset, assign labels, select model features or claim team agreement.

Use `repo_id` as lowercase owner/name to match the supplied Task 6 notebook; `github_repo_id` is a separate numeric GitHub identity. `identity_registry.csv` and `alias_crosswalk.csv` preserve resolved identities. The frozen base lacks numeric IDs for most rows; do not imply that all 166 identities have been verified by ID.

The three temporal pilots do not match any row in the frozen 166. Their measurements stay in `temporal_features_staging.csv`; Task 4 must review additions/labels before they enter the canonical base. Other outside-base provenance candidates are listed separately. No proposed trust label is supplied. Six low-activity screening repos already match the base, but only two have exact 90-day counts; four counts remain blank because their evidence is only a lower bound.

`base166_merge_preview.csv` preserves exactly the 166 names, order and labels, and leaves unobserved temporal values blank. It is a mechanical preview, not an approved training table. It includes snapshot labels only for verification; staging feature exports contain no target or prediction fields. No missing value was replaced by zero.

`temporal_features_long.csv` is authoritative for per-feature windows, availability, coverage, source scope and evidence. The wide staging export loses per-feature metadata, so it MUST travel with the long table and dictionary. One row-wide collected_at is only the latest contributing availability, not a common collection date. Do not invent a shared window for mixed 90-day and peak-relative features.

The Task 6 source specification is PROPOSED and uses explicit allowed feature names and ignored metadata; it was checked against the supplied notebook's source contract, not executed inside that notebook. That notebook prefixes columns by feature source. Keep canonical_confirmed and contract_confirmed false until the owners agree. A merge using the original base should flag outside-base pilots; do not silently add them or drop those errors. Do not enable automatic feature inference.

Definitions are candidate measurement definitions, not a model-selected feature set. Counts are committer UTC non-merges, search-index creation totals, current public release records, or currently visible forks as documented. Missingness, source scope and lifecycle differences remain material. Full-history counts refer to newly frozen branch heads, not exact original historical branch states. Exact star-source UTC alignment is unverified. Current search and listing scope does not recover deleted/private historical events. Eight-week features are retrospective and unavailable at the peak itself. Use per-feature availability times for any time-aware evaluation; Vidal owns that design.

## Rebuild offline

Python 3 standard library only; no API requests, model/runtime dependencies or downloaded project execution:

```
python build_temporal_bundle.py --from-bundle . --output ../rebuilt_temporal_bundle
```

Choose a fresh output path. The package includes source tables, supporting commit logs/API evidence, method reports, input mapping and checksums; bare Git stores and installed dependencies are omitted. Archived source reports refer to their original workspace paths; bundle source_artifact fields are portable relative paths. The snapshot evidence is unchanged.

## Owner decisions still required

- Task 4: reconcile seven outside-base identities, approve any additions and supply labels; review candidate interpretation.
- Task 6: agree on key/schema/version, explicit feature declarations and preservation of long-form coverage/availability; integrate into the actual canonical dataset.
- Vidal: evaluate feature availability, source/missingness shortcuts and any model feature use. No model is included.
- Ethan/user: interpret counterexamples and limitations; confirm readiness for the intended workflow with David.

No teammate messages have been sent. Schema alignment with supplied code is not confirmation by its owner.
"""
    (out / "README.md").write_text(text, encoding="utf-8")


def definition(name):
    exact = {
        "temporal__pre_median_weekly_commits": "Median of four complete pre-peak UTC weeks of root/one-parent commits reachable from the frozen head; null if any baseline week is ineligible.",
        "temporal__post_median_weekly_commits_8w": "Median of eight complete follow-up UTC weekly non-merge counts; null if the full follow-up is unobserved.",
        "temporal__post_pre_commit_ratio": "Eight-week post median / four-week pre median; requires both complete windows and positive pre median. Not a trust score.",
        "temporal__post_active_week_share_8w": "Number of complete follow-up weeks with positive non-merge counts divided by eight; null unless all eight weeks are observed.",
        "temporal__peak_week_nonmerge_commits": "Unique root/one-parent commits reachable from frozen head with UTC committer timestamp in the nominal peak week [start,end).",
        "temporal__nonmerge_commits_90d": "Exact unique root/one-parent commit count in the frozen 90-day UTC window, only with complete reachable-history verification; lower bounds are null here.",
    }
    if name in exact:
        return exact[name]
    source = (
        "Current GitHub search-index issue creations excluding PRs"
        if "issue_opened" in name
        else "Current GitHub search-index PR creations, not merges"
        if "pr_opened" in name
        else "Currently visible public non-draft GitHub releases by published_at, including prereleases; not tags"
        if "__releases_" in name
        else "Currently visible API-listed forks by created_at, only when the period is fully reached; not all historical forks"
    )
    return source + (
        "; divided by nominal window weeks only for a full eligible period."
        if name.endswith("_per_week")
        else "; count within explicit start-inclusive/end-exclusive UTC window; ineligible or incomplete source coverage remains null."
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--from-bundle", type=Path)
    main(p.parse_args())
