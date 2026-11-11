# Shared pipeline and assessment CLI

The `gh_signals` package combines supplied repository features and exposes one assessment function for terminal and website callers.
The frozen examples preserve the existing 106 repositories, their labels and missing values.
Contributor and temporal exports are research previews; they are not automatically approved model inputs.

## Setup

Use Python 3.13 or later and run from the repository root:

```bash
uv sync --frozen --all-groups
uv run gh-signals --help
```

## Consolidation

Reproduce the original nine-feature dataset:

```bash
uv run gh-signals consolidate --config examples/task6/config.json --input-dir examples/task6/inputs --output-dir runs/baseline
```

Use `config_contributors_preview.json` instead to append 14 contributor measurements from Elizabeth's frozen export.
Columns involving overlap with the known-good class, account logins and study labels are excluded from that preview's predictors.
Source definitions and limits are in the config; source commits are recorded in `examples/task6/SOURCES.json`.
Source exports remain unchanged.

Each run has a unique directory containing `shared_features.csv`, repository and candidate tables, validation issues, feature definitions, coverage, row provenance and input hashes.
Validation errors prevent publication of the dataset.
Warnings describe missing measurements and pending handoffs.
`handoff_ready` stays false until the declared task coverage, repository metadata and team confirmations are complete.
Successful consolidation therefore does not establish model readiness.

The selected base controls membership and labels.
Feature columns have source prefixes to prevent collisions.
Blank values remain blank and real zeros remain zero.
New columns must be declared or explicitly ignored.
An outside repository is an error by default; a source configured with `outside_base_policy: "review"` quarantines it in `outside_base_review.csv` without adding a row to the dataset.

Existing callers can import the same implementation:

```python
from pathlib import Path
import json
from gh_signals.consolidation import consolidate

config = json.loads(Path("examples/task6/config.json").read_text())
result = consolidate(config, Path("examples/task6/inputs"), Path("runs"))
```

## Temporal integration

Replace `RUN_DIRECTORY` below with the `run_dir` printed by consolidation:

```bash
uv run gh-signals temporal --base RUN_DIRECTORY/shared_features.csv --handoff-dir examples/task6/temporal --output-dir runs/temporal
```

The adapter verifies numeric repository identities, explicit aliases, time windows, coverage statuses, long-form provenance and measurements against the supplied evidence.
It preserves the base rows, order, values and labels, and appends 30 declared temporal columns.
Outside identities remain in a review table.
Use the resulting `integration_preview.csv` as the assessment input when a selected model requires temporal columns.
The frozen 106-repository base has no observed temporal measurements; all 30 appended columns are missing for that base.
The separate 166-repository reference is an example of a different membership set, not an automatic expansion of this dataset.

## Assessments

Assess one repository using an existing feature CSV:

```bash
uv run gh-signals assess microsoft/vscode --features RUN_DIRECTORY/shared_features.csv --output runs/assessment.json
```

Until a model adapter is configured, the response has status `unscored_model_missing`, a null score and exit code 3.
Add `--assessor trusted_package.module:object` when Vidal supplies the selected assessment implementation.
Only its declared features reach the model.
Missing required values produce `insufficient_evidence`; nullable values reach the model as `None`.
Fitted preprocessing and the composite score belong in that adapter.
See [the adapter contract](model-adapter.md).

A Python backend for Elizabeth's website imports the same function and serializes the same result:

```python
from pathlib import Path
from gh_signals.assessment import assess_repository, read_feature_row

features = read_feature_row(Path("shared_features.csv"), "microsoft/vscode")
result = assess_repository("microsoft/vscode", features)
response = result.model_dump(mode="json")
```

Pass the selected adapter as the third argument when available.
The supplied React frontend currently calls GitHub and builds its origin report in JavaScript; a backend route is required to call this Python implementation from that frontend.
The assessment library performs no network requests.
A score expresses confidence in a good repository under the selected model, not a maliciousness determination.

## Runtime and API usage

Offline consolidation, temporal integration and CSV assessment make zero GitHub API requests.
CLI JSON includes elapsed wall time and API counters.
The manifest identifies input bytes independently of variable run IDs and timing.

`assess owner/repo --live` uses the existing GitHub client to collect only `github__stars` and `github__forks` from repository metadata.
It does not collect the other baseline or specialized features.
A fresh uncached success makes one GET request; a fresh cache hit makes zero requests.
One rate-limit retry can add a second request.
The default cache lifetime is 24 hours, request timeout is 30 seconds and total allowed rate-limit waiting per client is 60 seconds.
Usage counters count HTTP attempts, cache hits and requested wait seconds.
Set `GITHUB_TOKEN` or use the existing GitHub CLI authentication setup for higher rate limits.
Only metadata are fetched; repository source, archives and git histories are not downloaded.

Consolidation cost grows with CSV rows, declared feature cells and report output, plus sorting repository keys.
Temporal validation checks each evidence-linked measurement and scans source tables, so cost also grows with the evidence bundle.
CSV assessment scans the file to reject duplicate identities and then evaluates only the model's declared features; model runtime depends on the adapter.

## Checks and remaining integration

```bash
uv run ruff format
uv run ruff check --fix
uv run ty check
uv run pytest
```

Tests compare the new baseline with the saved notebook output, check null and zero handling, reject invalid or conflicting rows, corrupt temporal evidence, compare website and CLI assessment results, and count HTTP attempts and cache hits using a local test server.

The selected model artifact, fitted preprocessing, approved feature definitions and composite-score implementation are still needed from Vidal.
Stefan's organization export and the final repository/schema confirmations are also pending.
The library accepts declared exports through configuration; it does not choose new features, train a substitute model or change repository membership.
