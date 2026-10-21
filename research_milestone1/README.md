# Temporal and low-activity repository research

Ethan's research contribution for Microsoft 3B, Break Through Tech AI Studio. Start with [findings](FINDINGS.md) for the main charts and limitations.

## Run the checks

From the repository root, with Python 3.13 or later and uv installed:

```sh
uv sync --frozen --all-extras --all-groups
uv run pytest research_milestone1 -q
uv run ruff format --check
uv run ruff check
uv run ty check
```

The 33 research tests cover UTC boundaries, merge exclusion, duplicate handling, incomplete coverage, creation-limited periods, identity normalization, and preservation of base labels and row order. They use cached fixtures and make no network requests. Plotting dependencies are in the optional `research` extra.

The cleaned notebook is [002_temporal_research.ipynb](../notebooks/002_temporal_research.ipynb). Its saved outputs and session metadata were cleared, and formatting and local import compatibility were updated. It retains historical Drive paths, preserved-table fallbacks, live API cells, and Drive writes. It was statically checked, not rerun end to end. Supply the original snapshot and temporal evidence before executing it, and inspect live collection cells against `AGENTS.md` first. The standalone scripts and saved findings include subsequent methods work beyond this notebook.

## Code and outputs

- `screening.py` and `collect_candidates.py`: coverage-aware 90-day activity screening.
- `collect_adoption.py`, `collect_clone_candidates.py`, and `clone_history_context.py`: historical evidence-collection scripts.
- `collect_pilot_histories.py` and `standardize_pilots.py`: reachable-history collection and common commit-count definitions.
- `analyze_rea_daily.py`: daily source validation and boundary sensitivity.
- `collect_engagement.py` and `build_engagement.py`: issues, pull requests, releases, and capped fork coverage.
- `audit_vidal_handoff.py`: static notebook/data audit; does not train models.
- `build_temporal_bundle.py`, `validate_temporal_bundle.py`, and `chart_temporal_bundle.py`: proposed integration, integrity checks, and coverage charts.
- `results/integration/`: derived review tables and proposed Task 6 specification.
- `figures/`: saved research charts.

Run individual scripts with `--help` to inspect their inputs. Original evidence archives, model notebooks, API caches, commit histories, and the full portable replay bundle remain in the shared Drive handoff. This checkout alone cannot reproduce every collection or chart. Rebuilding the integration tables requires the complete portable bundle and its evidence; the selected CSVs here are not that bundle. Historical scripts retain the original input-layout assumptions. Use fresh output directories to preserve prior evidence.

The repository's `AGENTS.md` forbids downloading or executing investigated repository contents. Do not run collectors that fetch README/manifests, patches, or repository objects under this workflow. Historical collectors are included for method review; the test suite does not invoke them. Review collection scope with the team before any new live collection.

## Data contract and decisions

`repo_id` is a normalized owner/name key; `github_repo_id` is a separately recorded numeric identity. Long-form feature records preserve each value's window, collection time, source, definition, and coverage. Missing or incomplete observations stay null; partial counts are lower bounds rather than exact zeroes.

The integration preview preserves the historical 166-row snapshot. It is not the team's approved canonical dataset. The three temporal pilots are outside that snapshot, and only h11 and Rich receive exact 90-day values in its preview. Keep provenance, discovery cohorts, review status, and labels out of automatic predictor selection. Zara owns inclusion and label decisions, Darren owns canonical integration, and Vidal owns modeling and evaluation.

No trust score, approved labels, reproduced model performance, or causal claims are delivered by this contribution.
