# Temporal feature integration handoff

The temporal evidence is packaged as validated staging, with a row-preserving merge preview and a proposed Task 6 source mapping. It is ready for owner review, not canonical publication or model use. No dataset membership, labels, original notebook or model was changed, and no team messages were sent.

Bundle folder: `temporal_bundle_20261021T000300Z`. Final archive: `temporal_bundle_20261021T000300Z_review.zip`, built October 20, 2026, America/Chicago. The ZIP is approximately 10 MB and includes enough evidence to rebuild the core tables offline with Python's standard library. A separate replay produced identical hashes for the long features, staging table, merge preview, identity registry and dictionary. The coverage chart is included as PNG and editable SVG.

## What is inside

| Artifact | Purpose |
|---|---|
| temporal_features_long.csv | 93 per-feature records with exact window, availability time, coverage, source scope, head SHA and portable evidence reference |
| temporal_features_staging.csv | Nine measured repositories, 30 explicitly declared candidate feature columns; no labels or model predictions |
| feature_dictionary.csv | Types, units, formulas, minimums, missingness and ownership; these are proposed measurements, not model-selected features |
| identity_registry.csv | 13 numeric GitHub identities, including measurement and provenance-review candidates |
| base_identity_crosswalk.csv | All 166 base names; numeric IDs resolved for six, explicitly uncollected for the other 160 |
| alias_crosswalk.csv | Requested qwibitai/nanoclaw resolves to nanocoai/nanoclaw; numeric identity kept separate |
| outside_base_review.csv | Seven outside-base identities for Task 4 review, with no proposed trust labels |
| base166_merge_preview.csv | Exactly 166 base rows in their original order, unchanged snapshot labels/source, with unobserved measurements blank |
| coverage_summary.csv | Populated staging/base fields, explicitly showing sparse base coverage |
| task6_source_spec_PROPOSED.json | Explicit source schema matching the supplied consolidation notebook's naming conventions; not owner-approved or executed there |
| validation_report.json / manifest.json | Scope checks, model-ready=false, owner-confirmed=false, file hashes |
| evidence/ | Source tables, raw context, public API metadata, commit logs, method reports and review evidence; no bare Git stores or plotting dependencies |

## The important merge result

None of OpenClaw, DeepSeek-R1 or REA matches the frozen 166-repository base. Their pilot measurements cannot enter that base simply by adding feature columns. Task 4 must decide identity/list additions and labels. Four other provenance-review projects are also outside the base; they have no numeric temporal feature rows in this package.

The six low-activity leads already belong to the base. Of those, h11 and Rich have exact full-history-verified 90-day counts, both zero. The other four only have observed lower bounds sufficient to fail the provisional screen; the exact-count feature is blank for them. No lower bound was promoted to an exact value, and no missing value was changed to zero.

Consequently, only two of the 166 base rows have a newly populated temporal measurement. This sparse integration preview is useful for validation, but it is not a complete model dataset. Its provenance and coverage fields must remain visible during review.

## Schema alignment with Darren's supplied notebook

The supplied Task 6 notebook uses repo_id for lowercase owner/name, not GitHub's numeric ID. The bundle follows that convention and stores the numeric identifier in github_repo_id. This avoids a silent numeric/string identity mismatch. The proposed spec explicitly declares 30 feature columns and ignores metadata fields; it does not enable automatic feature inference or import labels/predictions as predictors.

The long feature table is authoritative. The wide table's collected_at is the latest contributing availability time; it does not imply all features were collected together or share a single time window. The Task 6 spec therefore does not invent one shared window for 90-day and event-relative features. The owners need to agree how their consolidation pipeline preserves the long-form windows, source scopes, coverage and availability.

Keep canonical_confirmed and contract_confirmed false until Tasks 4/6 agree. The provided source spec includes outside-base pilots, so a correctly strict pipeline should require reconciliation, not silently add them. The supplied Task 6 notebook itself was inspected, not executed or modified. Local validation is not a claim of owner confirmation.

## Measurement boundaries

- Commit features use current frozen default-branch reachable histories, roots/one-parent commits, committer UTC, fixed week/window conventions and creation-aware coverage. They do not recreate original collection branch states.
- Issue and PR creation totals are current search-index counts, not response or merge evidence. Public release counts include prereleases. Fork features use currently visible API-listed scope and retain incomplete pagination as missing exact values.
- Star-anchor UTC boundaries remain provisional. Historical window dates and actual feature-availability dates are separate. Eight-week summaries are unavailable at the peak itself.
- Candidate interpretations, identity-review status, source labels and model predictions are not predictor features in the staging export. Vidal owns feature selection, preprocessing, fitting and evaluation.
- Archived source reports retain their original workspace paths and dates as context; exported source_artifact references point to files inside the portable bundle.

## Validation and replay

All 33 tests passed. Join tests reject duplicate normalized keys and label overwrite, preserve base order/labels, and distinguish a measured zero from a missing field. Bundle checks additionally validate identity consistency, integer/range/time constraints, unique repository-feature pairs, no row additions and explicit source references. Core exported tables matched an offline self-contained rebuild byte for byte.

Extract the ZIP into a new folder, then run from inside it:

```text
python build_temporal_bundle.py --from-bundle . --output ../rebuilt_temporal_bundle
python validate_temporal_bundle.py --bundle .
```

Choose a fresh directory outside the source bundle. Rebuild requires no network, model libraries, Git executable or project code execution. Plotting dependencies are needed only to recreate the separate coverage chart, not to rebuild the integration data.

## Remaining owner actions

- Task 4: reconcile seven outside-base identities, candidate inclusion and labels; confirm the actual current canonical list.
- Task 6: approve the key/schema/version contract and preserve per-feature provenance/coverage while integrating.
- Vidal: review sparse/missing coverage, collection availability and selection shortcuts before any feature/model use.
- Ethan/user: interpret low-activity and provenance findings and clarify the intended prototype decision with David.

No owner agreement has been inferred from a successful local merge. This milestone completes the documented temporal staging handoff; actual canonical integration remains open.
